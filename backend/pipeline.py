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

from models import GradingSession
from firestore_service import (
    get_all_papers,
    get_question_by_id,
    get_questions_for_paper,
)
from prompts import (
    get_maths_prompt,
    get_physics_theory_prompt,
    get_physics_atp_prompt,
    get_chemistry_theory_prompt,
    get_chemistry_atp_prompt,
)
from agents.vision_extractor import extract_and_grade
from agents.feedback_generator import generate_feedback
from agents.image_preprocess import enhance_image_base64


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


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _calc_cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * INPUT_COST_PER_TOKEN) + (
        output_tokens * OUTPUT_COST_PER_TOKEN
    )


def _log_cost(label: str, cost: float, running_total: float) -> None:
    print(f"[COST] {label}: ${cost:.4f}  (running total: ${running_total:.4f})")


def _load_mark_scheme_points(mark_scheme_rows: list[dict]) -> list[dict]:
    return [
        {
            "point_number": i + 1,
            "description": row.get("description", ""),
            "marks_for_point": row.get("marks_for_point", 1),
            "acceptable_alternatives": row.get("acceptable_alternatives") or "",
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
    question = get_question_by_id(question_id)
    if question is None:
        raise ValueError(f"Question {question_id} not found")

    question_int_id: int = int(question["id"])
    question_text: str = question["question_text"]
    mark_scheme_points = _load_mark_scheme_points(question.get("mark_scheme", []))
    marks_available: int = int(question["marks_available"])

    grading_session = GradingSession(question_id=question_int_id)
    db.add(grading_session)
    db.commit()
    db.refresh(grading_session)

    running_cost: float = 0.0

    try:
        print(
            f"[Pipeline] Call 1 — extract_and_grade "
            f"(question_id={question_int_id}, marks_available={marks_available})"
        )
        grade_result = extract_and_grade(
            image_base64=image_base64,
            question_text=question_text,
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

        # The [illegible] token is preserved in extracted_text (shown to the
        # teacher); log which question it appeared in for manual review.
        if "[illegible]" in extracted_text.lower():
            print(
                f"[WARN] [illegible] token(s) found in question {question_int_id}. "
                f"Teacher should check this answer manually."
            )

        print("[Pipeline] Call 2 — generate_feedback")
        feedback_result = generate_feedback(
            question_text=question_text,
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
            "question_id": question_int_id,
            "question_text": question_text,
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
    uid: str,
    progress_callback=None,
    inline_paper: dict | None = None,
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
    # Strip whitespace/newlines — Railway env vars sometimes include a trailing
    # \n from copy-paste, which httpx rejects as an illegal header value and
    # surfaces as the deeply misleading "APIConnectionError: Connection error."
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    if inline_paper is not None:
        # Generated (ad-hoc) paper from the Custom Paper Generator. Its paper
        # meta + questions/mark schemes are supplied inline rather than looked up
        # by paper_id (these papers are not stored in the papers collection). The
        # shape mirrors get_all_papers() / get_questions_for_paper() so the rest
        # of the function is unchanged: paper has subject_code, paper_number,
        # session, year, tier, total_marks; each question has question_number,
        # marks_available, question_text, and mark_scheme=[{description}].
        paper = inline_paper["paper"]
        questions: list[dict] = inline_paper.get("questions", [])
        if not questions:
            raise ValueError("inline_paper provided with no questions")
    else:
        papers = get_all_papers()
        paper = next((p for p in papers if str(p["id"]) == str(paper_id)), None)
        if paper is None:
            raise ValueError(f"Paper {paper_id} not found")

        questions = get_questions_for_paper(str(paper_id))
        if not questions:
            raise ValueError(f"No questions found for paper_id={paper_id}")

    # --- Select the subject/paper-specific examiner prompt ---
    # Route on (subject_code, paper_number) to the correct marking conventions.
    # Anything unrecognised falls back to the Maths prompt.
    subject_code = str(paper["subject_code"])
    paper_number = int(paper["paper_number"])
    if subject_code == "0580":
        system_prompt, marking_instructions = get_maths_prompt()
    elif subject_code == "0625" and paper_number == 4:
        system_prompt, marking_instructions = get_physics_theory_prompt()
    elif subject_code == "0625" and paper_number == 6:
        system_prompt, marking_instructions = get_physics_atp_prompt()
    elif subject_code == "0620" and paper_number == 4:
        system_prompt, marking_instructions = get_chemistry_theory_prompt()
    elif subject_code == "0620" and paper_number == 6:
        system_prompt, marking_instructions = get_chemistry_atp_prompt()
    else:
        system_prompt, marking_instructions = get_maths_prompt()

    # --- Build the complete mark scheme block ---
    ms_blocks: list[str] = []
    for q in questions:
        q_marks = int(q["marks_available"])
        criteria = [f"    * {ms.get('description', '')}" for ms in q.get("mark_scheme", [])]
        criteria_str = (
            "\n".join(criteria)
            if criteria
            else "    (no explicit mark points — award for a correct answer)"
        )
        ms_blocks.append(
            f"Q{q['question_number']} [{q_marks} mark"
            f"{'s' if q_marks != 1 else ''}]:\n{criteria_str}"
        )
    mark_scheme_full = "\n\n".join(ms_blocks)

    # --- Build content: intro, all page images, then mark scheme + instructions ---
    intro = (
        f"You are grading IGCSE {paper['subject_code']} Paper {paper['paper_number']} "
        f"({paper['session']} {paper['year']}, {paper['tier']}, total {paper['total_marks']} marks). "
        f"There are {len(questions)} question parts.\n"
        f"Below are {len(page_images)} photographed page(s) of the student's "
        f"handwritten answer booklet, followed by the mark scheme."
    )

    content: list[dict] = [{"type": "text", "text": intro}]
    for page_b64 in page_images:
        # Enhance each page for handwriting legibility before sending it to the
        # model. enhance_image_base64 always returns high-quality JPEG bytes.
        enhanced_b64 = enhance_image_base64(_strip_data_uri(page_b64))
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": enhanced_b64,
            },
        })

    instructions = (
        f"\nMARK SCHEME (apply Cambridge rules strictly — {marking_instructions}):\n\n"
        f"{mark_scheme_full}\n\n"
        "MAXIMUM MARKS: The maximum marks available for each question are stated "
        "directly in the mark scheme above — the number shown in square brackets "
        "next to the question (e.g. '[4 marks]'). Read that number exactly as "
        "written. You must NOT infer, calculate, adjust, or redistribute marks "
        "between questions. Whatever the mark scheme states as the total for a "
        "question is the total for that question, no exceptions, and the marks "
        "you award for a question must never exceed it.\n\n"
        "You must base your marking decision entirely on what the student has "
        "written. Do not perform independent verification of the answer. Do not "
        "recalculate. If you calculated something yourself and it differs from "
        "what the student wrote, ignore your calculation entirely and mark only "
        "what the student wrote against the mark scheme criteria.\n\n"
        "HANDWRITING: The image contains handwritten student answers. "
        "Handwriting quality may vary significantly between students. Some "
        "handwriting may be messy, rushed, or unconventional. Read every "
        "written character as carefully as possible. If a word or number is "
        "genuinely impossible to interpret after careful analysis, write the "
        "token [illegible] in place of that word. Do not skip any written "
        "content and do not guess randomly. Apply extra attention to numbers, "
        "units, and technical scientific terms as these are the most critical "
        "parts of student answers.\n\n"
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
        f"{paper['subject_code']}/{paper['paper_number']}, "
        f"{len(questions)} questions, {len(page_images)} page(s)"
    )

    if progress_callback:
        progress_callback("Reading handwriting")

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=16000,
            temperature=0,
            system=system_prompt,
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

    if progress_callback:
        progress_callback("Applying mark scheme")

    raw_results = parsed.get("results", [])
    if not isinstance(raw_results, list):
        raise RuntimeError("Grading response missing 'results' list")

    # Index the model's results for matching. We keep an exact index plus a
    # "normalized leading number" index so we can recover from the model keying
    # a result by a sub-part (e.g. returning "1a"/"1(a)(i)" for our question
    # "1") — common for generated papers whose mark-scheme text carries the
    # source paper's sub-part labels. Normalization is the FALLBACK only; an
    # exact question_number match always wins. We normalise to the FIRST run of
    # digits found anywhere in the key — the whole run, so Q10–Q13 don't
    # collapse into Q1 — which maps "1a", "1(a)(i)", and prefixed forms the
    # model sometimes emits ("Q1", "Q13") all back to the leading number.
    def _norm_qnum(value: str) -> str:
        m = re.search(r"\d+", str(value))
        return m.group(0) if m else str(value).strip().lower()

    model_results = [
        r for r in raw_results
        if isinstance(r, dict) and str(r.get("question_number", "")).strip()
    ]
    exact_index: dict[str, int] = {}
    norm_index: dict[str, list[int]] = {}
    for i, r in enumerate(model_results):
        rq = str(r["question_number"]).strip()
        exact_index.setdefault(rq, i)
        norm_index.setdefault(_norm_qnum(rq), []).append(i)

    # A model result is consumed once matched, so the same entry is never
    # aggregated into two of our questions (guards the inverse case where the
    # model lumps several stored sub-questions under one number).
    consumed: set[int] = set()

    # --- Build final results in stored question order, persist sessions ---
    results: list[dict] = []
    total_awarded: int = 0
    illegible_questions: list[str] = []

    for q in questions:
        qnum = q["question_number"]
        marks_available = int(q["marks_available"])

        # 1) Exact match wins. 2) Fallback: every still-unconsumed model result
        # whose leading number normalises to this question (aggregated).
        matched: list[dict] = []
        exact_i = exact_index.get(qnum)
        if exact_i is not None and exact_i not in consumed:
            matched.append(model_results[exact_i])
            consumed.add(exact_i)
        else:
            for i in norm_index.get(_norm_qnum(qnum), []):
                if i not in consumed:
                    matched.append(model_results[i])
                    consumed.add(i)

        if not matched:
            results.append({
                "question_number": qnum,
                "question_text": q["question_text"],
                "extracted_answer": "",
                "marks_awarded": 0,
                "marks_available": marks_available,
                "mark_breakdown": [],
                "feedback": "Not graded (missing from AI response).",
                "has_illegible": False,
            })
            continue

        # Aggregate across matched results (usually one; >1 when the model split
        # this question into sub-parts).
        awarded = 0
        extracted_parts: list[str] = []
        feedback_parts: list[str] = []
        breakdown: list = []
        for r in matched:
            try:
                part_awarded = int(r.get("marks_awarded", 0))
            except (TypeError, ValueError):
                part_awarded = 0
            awarded += max(0, part_awarded)
            ex = str(r.get("extracted_answer", "")).strip()
            if ex:
                extracted_parts.append(ex)
            fb = str(r.get("feedback", "")).strip()
            if fb:
                feedback_parts.append(fb)
            bd = r.get("mark_breakdown", [])
            if isinstance(bd, list):
                breakdown.extend(bd)

        awarded = max(0, min(awarded, marks_available))
        total_awarded += awarded
        extracted = "\n".join(extracted_parts)
        feedback = " ".join(feedback_parts)

        # Flag questions where the model could not read part of the answer, so
        # the teacher knows to check that question manually.
        has_illegible = "[illegible]" in extracted.lower()
        if has_illegible:
            illegible_questions.append(qnum)

        # Generated papers' question IDs are not rows in the SQLite Question
        # table, so skip the analytics GradingSession write for inline papers —
        # int(q["id"]) would fail and the question_id FK would be invalid.
        if inline_paper is None:
            db.add(GradingSession(
                question_id=int(q["id"]),
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
            "question_text": q["question_text"],
            "extracted_answer": extracted,
            "marks_awarded": awarded,
            "marks_available": marks_available,
            "mark_breakdown": breakdown,
            "feedback": feedback,
            "has_illegible": has_illegible,
        })

    db.commit()

    if progress_callback:
        progress_callback("Calculating scores")

    # Log which questions contained illegible content so it is visible in logs
    # as well as in the result returned to the teacher.
    if illegible_questions:
        print(
            f"[WARN] [illegible] token(s) found in paper {paper_id} for "
            f"question(s): {', '.join(illegible_questions)}. "
            f"Flagging those questions for manual review."
        )

    # Authoritative paper total comes from Paper.total_marks, not summed parts
    total_available = int(paper["total_marks"])
    # Clamp awarded just in case mis-parsed mark counts let it overshoot
    total_awarded = min(total_awarded, total_available)

    # --- Validate per-question maxima against the authoritative paper total ---
    # The maximum marks for each question come straight from the mark scheme
    # (Firestore). Their sum must equal the paper's stored total_marks. If it
    # doesn't, the mark scheme is internally inconsistent (e.g. a 4-mark
    # question stored as 3), so individual question totals may be wrong even
    # when the paper total happens to add up. We flag this (but never block the
    # result) so the frontend can warn the user.
    expected_total = total_available
    returned_total = sum(int(q["marks_available"]) for q in questions)
    marks_total_mismatch = returned_total != expected_total
    if marks_total_mismatch:
        print(
            f"[WARN] marks total mismatch for paper {paper_id}: "
            f"expected total {expected_total} (paper.total_marks) but per-question "
            f"maxima sum to {returned_total}. Flagging marks_total_mismatch=true."
        )

    print(
        f"[Pipeline] FINAL: {total_awarded}/{total_available} marks, "
        f"${cost:.4f}"
    )

    final_result = {
        "paper_id": paper_id,
        "total_marks_awarded": total_awarded,
        "total_marks_available": total_available,
        "cost_usd": round(cost, 6),
        "results": results,
        "cost_cap_reached": cost_cap_reached,
        "marks_total_mismatch": marks_total_mismatch,
    }

    return final_result
