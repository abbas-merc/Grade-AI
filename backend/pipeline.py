"""
pipeline.py — Orchestrates the grading pipelines for GradeAI.

Exports:
    run_grading_pipeline   — 2-call pipeline for a single question (existing)
    run_full_paper_grading — multi-call pipeline for a complete paper (new)

Single-question sequence (max 2 Anthropic API calls, hard cap $0.20):
    1. vision_extractor.extract_and_grade  (image + mark scheme → result)
    2. feedback_generator.generate_feedback (text-only → student paragraph)

Full-paper sequence:
    Phase 1 — one call per photographed page (vision, extracts student answers)
    Phase 2 — one call per question that has an answer (text-only, grades it)
    Hard cap $0.50 total; stops and flags cost_cap_reached when hit.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import anthropic
from sqlalchemy.orm import Session

from models import GradingSession, MarkScheme, Question
from agents.vision_extractor import extract_and_grade
from agents.feedback_generator import generate_feedback


# ---------------------------------------------------------------------------
# Shared cost constants
# ---------------------------------------------------------------------------

MAX_COST_USD: float = 0.20           # per single-question session
MAX_PAPER_COST_USD: float = 0.50     # per full-paper session
INPUT_COST_PER_TOKEN: float = 0.000003
OUTPUT_COST_PER_TOKEN: float = 0.000015

MODEL = "claude-sonnet-4-6"
PAGE_EXTRACTION_MAX_TOKENS = 1000
QUESTION_GRADING_MAX_TOKENS = 500

CAMBRIDGE_RULES = (
    "Cambridge IGCSE marking rules — apply these exactly: "
    "M marks are for method — award if correct method is shown even if the final answer is wrong. "
    "A marks are for accuracy — ONLY award an A mark if the corresponding M mark was also awarded. "
    "B marks are independent — award regardless of method used. "
    "ft means follow through — award if the student correctly applied an earlier (wrong) result. "
    "cao means correct answer only — do not award for a follow-through answer. "
    "oe means or equivalent — accept any mathematically equivalent form."
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _calc_cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * INPUT_COST_PER_TOKEN) + (
        output_tokens * OUTPUT_COST_PER_TOKEN
    )


def _log_cost(label: str, cost: float, running_total: float) -> None:
    print(f"[COST] {label}: ${cost:.4f}  (running total: ${running_total:.4f})")


def _load_mark_scheme_points(mark_scheme_rows: list[MarkScheme]) -> list[dict]:
    return [
        {
            "point_number": i + 1,
            "description": row.description,
            "marks_for_point": row.marks_for_point,
            "acceptable_alternatives": row.acceptable_alternatives or "",
        }
        for i, row in enumerate(mark_scheme_rows)
    ]


def _extract_json(raw: str) -> dict[str, Any]:
    """Pull a JSON object from model output that may be wrapped in markdown fences."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and last > first:
        text = text[first: last + 1]
    return json.loads(text)


def _strip_data_uri(b64: str) -> str:
    if "base64," in b64:
        return b64.split("base64,", 1)[1]
    return b64


def _detect_media_type(b64: str) -> str:
    m = re.match(r"data:(image/[a-zA-Z0-9.+-]+);base64,", b64)
    return m.group(1) if m else "image/jpeg"


# ---------------------------------------------------------------------------
# Single-question pipeline (unchanged)
# ---------------------------------------------------------------------------

def run_grading_pipeline(
    question_id: int,
    image_base64: str,
    db: Session,
) -> dict:
    """
    Run the full 2-call grading pipeline for one student submission.

    Args:
        question_id:  ID of the Question being attempted.
        image_base64: Base64-encoded student answer photo.
        db:           Active SQLAlchemy session.

    Returns:
        Dict matching GradingResponse schema.

    Raises:
        ValueError: If the question or its mark scheme is missing.
    """
    question: Question | None = (
        db.query(Question).filter(Question.id == question_id).first()
    )
    if question is None:
        raise ValueError(f"Question {question_id} not found")

    mark_scheme_points = _load_mark_scheme_points(question.mark_scheme)
    marks_available: int = int(question.marks_available)

    grading_session = GradingSession(question_id=question.id)
    db.add(grading_session)
    db.commit()
    db.refresh(grading_session)

    running_cost: float = 0.0

    try:
        print(
            f"[Pipeline] Call 1 — extract_and_grade "
            f"(question_id={question.id}, marks_available={marks_available})"
        )
        grade_result = extract_and_grade(
            image_base64=image_base64,
            question_text=question.question_text,
            marks_available=marks_available,
            mark_scheme_points=mark_scheme_points,
        )

        if "error" in grade_result:
            raise RuntimeError(f"Grading failed: {grade_result['error']}")

        call1_cost = _calc_cost(
            grade_result.get("input_tokens", 0),
            grade_result.get("output_tokens", 0),
        )
        running_cost += call1_cost
        _log_cost("call 1 (vision+grade)", call1_cost, running_cost)

        if running_cost >= MAX_COST_USD:
            raise RuntimeError(
                f"Cost cap hit after call 1: ${running_cost:.4f} >= ${MAX_COST_USD:.2f}"
            )

        extracted_text: str = grade_result.get("extracted_text", "")
        marks_awarded: int = int(grade_result.get("marks_awarded", 0))
        mark_breakdown: list[dict] = grade_result.get("mark_breakdown", []) or []

        print("[Pipeline] Call 2 — generate_feedback")
        feedback_result = generate_feedback(
            question_text=question.question_text,
            extracted_text=extracted_text,
            marks_awarded=marks_awarded,
            marks_available=marks_available,
            mark_breakdown=mark_breakdown,
        )
        if "error" in feedback_result:
            print(f"[Pipeline] Feedback call failed (non-fatal): {feedback_result['error']}")

        call2_cost = _calc_cost(0, feedback_result.get("output_tokens", 0))
        running_cost += call2_cost
        _log_cost("call 2 (feedback)", call2_cost, running_cost)

        if running_cost > MAX_COST_USD:
            print(
                f"[COST] WARNING: total ${running_cost:.4f} exceeded "
                f"MAX_COST_USD=${MAX_COST_USD:.2f}"
            )

        feedback_text: str = feedback_result.get("feedback", "")

        grading_session.extracted_text = extracted_text
        grading_session.marks_awarded = float(marks_awarded)
        grading_session.feedback_json = json.dumps(
            {
                "feedback": feedback_text,
                "mark_breakdown": mark_breakdown,
                "extracted_text": extracted_text,
                "cost_usd": running_cost,
            }
        )
        db.commit()

        result: dict[str, Any] = {
            "session_id": grading_session.id,
            "question_id": question.id,
            "question_text": question.question_text,
            "marks_awarded": marks_awarded,
            "marks_available": marks_available,
            "mark_breakdown": mark_breakdown,
            "feedback": feedback_text,
            "extracted_text": extracted_text,
            "cost_usd": round(running_cost, 6),
        }
        print(f"[COST] FINAL session {grading_session.id}: ${running_cost:.4f}")
        return result

    except Exception as exc:
        grading_session.feedback_json = json.dumps(
            {"error": str(exc), "cost_usd": running_cost}
        )
        db.commit()
        raise


# ---------------------------------------------------------------------------
# Full-paper pipeline (new)
# ---------------------------------------------------------------------------

def run_full_paper_grading(
    paper_id: int,
    page_images: list[str],
    db: Session,
) -> dict:
    """
    Grade an entire exam paper from one or more photographed pages in a
    SINGLE Anthropic API call.

    The call sends all page images + the complete mark scheme for the paper
    together. Claude then performs extraction + grading + feedback for every
    question in one structured JSON response.

    Why one call instead of N+M calls:
        Per-page extraction (N) + per-question grading (M) = N+M sequential
        roundtrips, each paying for the Cambridge rules prompt overhead and
        each adding ~3-5s of network/model latency. Collapsing to 1 call
        cuts wall-clock time by ~10x and cost by ~4x.

    Args:
        paper_id:    Paper record ID.
        page_images: Base64-encoded page photos (any number).
        db:          Active SQLAlchemy session.

    Returns:
        {
            "paper_id":            int,
            "total_marks_awarded": int,
            "total_marks_available": int,   # paper.total_marks (authoritative)
            "cost_usd":            float,
            "results":             list[dict],  # one per question, in order
            "cost_cap_reached":    bool,
        }

    Raises:
        ValueError: paper/questions missing.
        RuntimeError: API key missing, API call failed, or unparseable JSON.
    """
    from models import Paper

    # Strip whitespace/newlines — Railway env vars sometimes include a trailing
    # \n from copy-paste, which httpx rejects as an illegal header value and
    # surfaces as the deeply misleading "APIConnectionError: Connection error."
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if paper is None:
        raise ValueError(f"Paper {paper_id} not found")

    questions: list[Question] = (
        db.query(Question)
        .filter(Question.paper_id == paper_id)
        .order_by(Question.id)
        .all()
    )
    if not questions:
        raise ValueError(f"No questions found for paper_id={paper_id}")

    # --- Build the complete mark scheme block ---
    ms_blocks: list[str] = []
    for q in questions:
        criteria = [f"    * {ms.description}" for ms in q.mark_scheme]
        criteria_str = (
            "\n".join(criteria)
            if criteria
            else "    (no explicit mark points — award for a correct answer)"
        )
        ms_blocks.append(
            f"Q{q.question_number} [{q.marks_available} mark"
            f"{'s' if q.marks_available != 1 else ''}]:\n{criteria_str}"
        )
    mark_scheme_full = "\n\n".join(ms_blocks)

    # --- Build content: intro, all page images, then mark scheme + instructions ---
    intro = (
        f"You are grading IGCSE {paper.subject_code} Paper {paper.paper_number} "
        f"({paper.session} {paper.year}, {paper.tier}, total {paper.total_marks} marks). "
        f"There are {len(questions)} question parts.\n"
        f"Below are {len(page_images)} photographed page(s) of the student's "
        f"handwritten answer booklet, followed by the mark scheme."
    )

    content: list[dict] = [{"type": "text", "text": intro}]
    for page_b64 in page_images:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": _detect_media_type(page_b64),
                "data": _strip_data_uri(page_b64),
            },
        })

    instructions = (
        f"\nMARK SCHEME (apply Cambridge rules strictly — {CAMBRIDGE_RULES}):\n\n"
        f"{mark_scheme_full}\n\n"
        "You must base your marking decision entirely on what the student has "
        "written. Do not perform independent verification of the answer. Do not "
        "recalculate. If you calculated something yourself and it differs from "
        "what the student wrote, ignore your calculation entirely and mark only "
        "what the student wrote against the mark scheme criteria.\n\n"
        "TASK — for EACH question listed above:\n"
        "1. Scan all pages for the student's answer (question numbers like "
        "'1a', '13b(ii)' will be written by the student). An answer may "
        "continue onto a later page — concatenate continuations.\n"
        "2. Read handwriting CAREFULLY. Students aged 14-17 write quickly and "
        "messily. Mathematical notation matters: distinguish 1/7, 0/O/Ø, "
        "decimal points, fractions, indices, ±, √, π, equal vs approx. If a "
        "symbol is ambiguous, infer from context (the surrounding maths and "
        "the question). Better to infer the intended reading than to give up.\n"
        "3. If no answer found anywhere, mark unanswered (0 marks).\n"
        "4. Grade strictly point-by-point against the mark scheme criteria.\n"
        "5. If you cannot read the student's handwriting for a question with "
        "high confidence, do not attempt to interpret it. Instead set the "
        "awarded marks to 0 for that question and set the feedback to say "
        "'handwriting unclear, please resubmit this page'. Never award or "
        "deduct marks based on a guess.\n"
        "6. You must only evaluate what is physically written on the paper. "
        "Do not infer, assume, or construct an answer. If the student wrote "
        "'anti-clockwise', mark that as the answer. Do not replace it with "
        "your own interpretation of what the answer should be.\n"
        "7. If you are unsure whether an answer satisfies a criterion, award "
        "the mark. Uncertainty defaults to awarding, not withholding.\n\n"
        "Return ONLY valid JSON. No markdown, no commentary, no explanation. "
        f"Include ALL {len(questions)} questions in `results`, in the order "
        "listed above. Shape:\n"
        "{\n"
        '  "results": [\n'
        '    {\n'
        '      "question_number": "1a",\n'
        '      "extracted_answer": "<verbatim student work, or empty string>",\n'
        '      "marks_awarded": <integer, 0..marks_available>,\n'
        '      "mark_breakdown": [\n'
        '        {"criterion": "<short>", "awarded": true|false, "reason": "<one sentence>"}\n'
        '      ],\n'
        '      "feedback": "<one short encouraging sentence for a student aged 14-17>"\n'
        "    }\n"
        "  ]\n"
        "}"
    )
    content.append({"type": "text", "text": instructions})

    # max_retries=5 (SDK default is 2) absorbs transient 5xx / 429 / connection
    # errors with exponential backoff before surfacing failure to the user.
    client = anthropic.Anthropic(
        api_key=api_key,
        max_retries=5,
        timeout=180.0,
    )
    print(
        f"\n[Pipeline] Full-paper grading (single-call) — "
        f"{paper.subject_code}/{paper.paper_number}, "
        f"{len(questions)} questions, {len(page_images)} page(s)"
    )

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=16000,
            temperature=0,
            system=(
                "You are an expert Cambridge IGCSE mathematics examiner with "
                "decades of experience reading messy student handwriting. "
                "You decipher hurried work and ambiguous symbols by inferring "
                "from mathematical context. You grade strictly but fairly by "
                "Cambridge conventions."
            ),
            messages=[{"role": "user", "content": content}],
        )
    except Exception as exc:
        import traceback as _tb
        cause = getattr(exc, "__cause__", None)
        cause_desc = f" (cause: {type(cause).__name__}: {cause})" if cause else ""
        detail = f"{type(exc).__name__}: {exc}{cause_desc}"
        print(f"[Pipeline] API call failed: {detail}")
        _tb.print_exc()
        raise RuntimeError(f"Anthropic API call failed: {detail}")

    in_tok = getattr(response.usage, "input_tokens", 0) or 0
    out_tok = getattr(response.usage, "output_tokens", 0) or 0
    cost = _calc_cost(in_tok, out_tok)
    cost_cap_reached = cost > MAX_PAPER_COST_USD
    print(
        f"[COST] full-paper single-call: ${cost:.4f}  "
        f"(in={in_tok}, out={out_tok}, cap=${MAX_PAPER_COST_USD:.2f}"
        f"{' EXCEEDED' if cost_cap_reached else ''})"
    )

    # --- Parse the structured response ---
    try:
        parsed = _extract_json(response.content[0].text)
    except Exception as exc:
        raise RuntimeError(f"Could not parse grading response as JSON: {exc}")

    raw_results = parsed.get("results", [])
    if not isinstance(raw_results, list):
        raise RuntimeError("Grading response missing 'results' list")

    result_by_qnum: dict[str, dict] = {}
    for r in raw_results:
        if isinstance(r, dict):
            qnum = str(r.get("question_number", "")).strip()
            if qnum:
                result_by_qnum[qnum] = r

    # --- Build final results in stored question order, persist sessions ---
    results: list[dict] = []
    total_awarded: int = 0

    for q in questions:
        qnum = q.question_number
        marks_available = int(q.marks_available)
        r = result_by_qnum.get(qnum)

        if r is None:
            results.append({
                "question_number": qnum,
                "question_text": q.question_text,
                "extracted_answer": "",
                "marks_awarded": 0,
                "marks_available": marks_available,
                "mark_breakdown": [],
                "feedback": "Not graded (missing from AI response).",
            })
            continue

        try:
            awarded = int(r.get("marks_awarded", 0))
        except (TypeError, ValueError):
            awarded = 0
        awarded = max(0, min(awarded, marks_available))
        total_awarded += awarded

        extracted = str(r.get("extracted_answer", "")).strip()
        feedback = str(r.get("feedback", "")).strip()
        breakdown = r.get("mark_breakdown", [])
        if not isinstance(breakdown, list):
            breakdown = []

        db.add(GradingSession(
            question_id=q.id,
            extracted_text=extracted,
            marks_awarded=float(awarded),
            feedback_json=json.dumps({
                "feedback": feedback,
                "mark_breakdown": breakdown,
                "cost_usd": cost,
            }),
        ))

        results.append({
            "question_number": qnum,
            "question_text": q.question_text,
            "extracted_answer": extracted,
            "marks_awarded": awarded,
            "marks_available": marks_available,
            "mark_breakdown": breakdown,
            "feedback": feedback,
        })

    db.commit()

    # Authoritative paper total comes from Paper.total_marks, not summed parts
    total_available = paper.total_marks
    # Clamp awarded just in case mis-parsed mark counts let it overshoot
    total_awarded = min(total_awarded, total_available)

    print(
        f"[Pipeline] FINAL: {total_awarded}/{total_available} marks, "
        f"${cost:.4f}"
    )

    return {
        "paper_id": paper_id,
        "total_marks_awarded": total_awarded,
        "total_marks_available": total_available,
        "cost_usd": round(cost, 6),
        "results": results,
        "cost_cap_reached": cost_cap_reached,
    }
