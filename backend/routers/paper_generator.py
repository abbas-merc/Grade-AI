"""
routers/paper_generator.py — Custom IGCSE paper generator.

Endpoints (mounted under /api by main.py):
  POST /api/generate-paper
      Select a set of questions from the Firestore `questions` collection that
      match the requested subject / topics / difficulty, renumber them from 1,
      and return the paper plus its mark scheme.
  POST /api/generate-paper/download-question-paper
      Render a generate-paper response to a question-paper PDF (file download).
  POST /api/generate-paper/download-mark-scheme
      Render a generate-paper response to a mark-scheme PDF (file download).
  POST /api/generate-paper/partlevel
      Topic-safe generation over the part-level bank.
  POST /api/generate-paper/partlevel/download-question-paper
  POST /api/generate-paper/partlevel/download-mark-scheme
      The same PDFs for a part-level (possibly assembled) paper.
  GET  /api/generate-paper/typesetting-status
      Whether the LaTeX engine and the school's font are present on this deploy.

Diagram questions (hasImage == true) are now included: each carries an
`imageUrl` ("/diagrams/<id>.png") pointing at the figure extracted from the
source paper. The app renders it in the preview card.

PDF rendering is XeLaTeX typesetting (utils/latex): real maths notation, ruled
answer space sized from the mark allocation, and the school's own font. The
previous reportlab renderer — which pasted a screenshot of each question — is
still wired up as an instant rollback via GA_PDF_ENGINE=images or ?engine=images.
Both return the identical response shape (raw PDF bytes + a Content-Disposition
attachment header), so the app's download flow is unchanged either way.
"""
from __future__ import annotations

import random
import uuid
from itertools import zip_longest
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from firebase_admin import firestore
from pydantic import BaseModel, Field

from auth import get_current_uid
from firestore_service import _get_client
from partlevel_selection import expand_allowed, select_paper
from utils.latex import service as latex_service
from utils.latex.service import PaperBuildError
from utils.pdf_generator import (
    generate_mark_scheme_pdf,
    generate_question_paper_pdf,
)

router = APIRouter(tags=["paper-generator"])

_QUESTIONS_COLLECTION = "questions"

# --------------------------------------------------------------------------- #
# Part-level topic taxonomy (Stage 5 filter rewrite)
# --------------------------------------------------------------------------- #
# The app's topic chips are the old broad buckets; each maps to one or more
# official 0580 syllabus sections. A teacher who selects "geometry" is taught to
# mean sections 4 (Geometry) + 5 (Mensuration); the part-level filter then admits
# a question only if EVERY sub-part's syllabus code sits in the allowed sections.
_TOPIC_SECTIONS: dict[str, set[int]] = {
    "number": {1},
    "algebra": {2, 3},
    "geometry": {4, 5},
    "trigonometry": {6},
    "vectors": {7},
    "probability": {8},
    "statistics": {9},
    "calculus": {2, 3},  # legacy bucket; 0580 has no calculus section
}

import json as _json  # noqa: E402
import os as _os  # noqa: E402

_SYLLABUS_PATH = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                               "scripts", "syllabus_codes.json")
try:
    _FLAT_CODES = _json.load(open(_SYLLABUS_PATH, encoding="utf-8"))["flat_codes"]
except Exception:  # taxonomy file missing -> part-level endpoint degrades gracefully
    _FLAT_CODES = []


def _allowed_codes_from_topics(topics: list[str]) -> set[str]:
    """Broad topic allow-list -> the set of syllabus codes it permits."""
    sections: set[int] = set()
    for t in topics:
        sections |= _TOPIC_SECTIONS.get((t or "").lower(), set())
    return {c["code"] for c in _FLAT_CODES if c["section"] in sections}
# A generated paper must contain at least this many and at most this many
# questions. The selector never exceeds the requested total marks.
_MIN_QUESTIONS = 3
_MAX_QUESTIONS = 12


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class GeneratePaperRequest(BaseModel):
    # Pydantic enforces these and FastAPI auto-returns 422 with a clear message
    # if any fail: subject must be a known value, at least one topic must be
    # supplied, and the mark total must sit in a sane range.
    subject: Literal["math", "physics", "chemistry"] = "math"
    # Calculator mode: "P2" = a non-calculator paper (pool restricted to
    # calculatorStatus == "non_calc_safe", source-agnostic); "P4"/"both" = a
    # calculator paper (any question eligible). See _fetch_pool.
    paperType: Literal["P2", "P4", "both"] = "both"
    topics: list[str] = Field(min_length=1)
    totalMarks: int = Field(ge=20, le=200)
    difficulty: Literal["mixed", "easy", "medium", "hard"] = "mixed"
    # Optional school name, echoed into the response so it rides through to the
    # PDF header on download. Empty string when not provided.
    schoolName: str = ""


class GeneratedQuestion(BaseModel):
    assignedNumber: int
    originalPaperCode: str
    # Which source paper type this question came from ("P2" | "P4").
    paperType: str
    # True when sourced from a specimen paper (vs a past exam).
    isSpecimen: bool = False
    marks: int
    topic: str
    difficulty: str
    # Every question now IS an image: questionImageUrl is the host-agnostic path
    # ("/question_snippets/<id>.png") the app prepends BASE_URL to and the PDF
    # generator resolves to a local file under backend/static.
    questionImageUrl: str


class MarkSchemeItem(BaseModel):
    questionNumber: int
    marks: int
    markSchemeText: str


class GeneratePaperResponse(BaseModel):
    paperId: str
    subject: str
    totalMarks: int
    numQuestions: int
    questions: list[GeneratedQuestion]
    markScheme: list[MarkSchemeItem]
    # Echoed from the request so downstream PDF downloads (which receive this
    # object back) can print it in the header. Optional / defaults empty.
    schoolName: str = ""
    # Teacher-provided name, attached when the paper is saved to "My Generated
    # Papers" and sent back on download so the PDF title can use it. Optional.
    paperName: str = ""


# --------------------------------------------------------------------------- #
# Selection logic
# --------------------------------------------------------------------------- #
def _fetch_pool(subject: str, topics: list[str], paper_type: str) -> list[dict]:
    """Return questions matching subject, the calculator mode, and (if given) topics.

    Paper-type selection is a CALCULATOR mode, not a source-paper label:
      * "P2"  → a non-calculator paper: the pool is strictly every question
        classified hand-safe (calculatorStatus == "non_calc_safe"), regardless of
        which source paper it came from or its year. This is the whole point of
        calculatorStatus — a 2024 "P2" question may require a calculator, and a
        2024 "P4" question may be hand-safe, so we must NOT filter by paperType.
      * "P4" / "both" → a calculator paper: any question is eligible.

    We filter on `subject` in Firestore (auto single-field index) and apply the
    calculator + topic filters in Python — the collection is tiny, so this avoids
    needing a composite index or running into `in`-query limits.
    """
    db = _get_client()
    topic_set = set(topics or [])
    pool: list[dict] = []
    query = db.collection(_QUESTIONS_COLLECTION).where(
        filter=firestore.FieldFilter("subject", "==", subject)
    )
    for doc in query.stream():
        data = doc.to_dict() or {}
        if paper_type == "P2" and data.get("calculatorStatus") != "non_calc_safe":
            continue
        if topic_set and data.get("topic") not in topic_set:
            continue
        pool.append(data)
    return pool


def _ordered_pool(pool: list[dict], difficulty: str) -> list[dict]:
    """Shuffle the pool. For 'mixed', interleave difficulties so a greedy walk
    pulls a balanced spread; otherwise filter to the requested difficulty."""
    if difficulty == "mixed":
        groups: dict[str, list[dict]] = {}
        for q in pool:
            groups.setdefault(q.get("difficulty", "unknown"), []).append(q)
        for bucket in groups.values():
            random.shuffle(bucket)
        ordered: list[dict] = []
        for tier in zip_longest(*groups.values()):
            ordered.extend(q for q in tier if q is not None)
        return ordered

    filtered = [q for q in pool if q.get("difficulty") == difficulty]
    random.shuffle(filtered)
    return filtered


def _select(ordered: list[dict], total_marks: int) -> list[dict]:
    """Choose a subset of (already shuffled) questions whose marks sum to exactly
    `total_marks` where possible — never exceeding it.

    Implemented as a bounded subset-sum DP over (question_count, running_sum):
      * `reach[k]` holds every sum (<= target) attainable with exactly k
        questions; `came[k][s]` records the question added to reach (k, s), whose
        predecessor state is (k-1, s - marks).
      * We then pick the best terminal state: an exact hit on the target if one
        exists (preferring the fewest questions, i.e. higher-mark ones), else the
        largest attainable sum <= target.
    Count is constrained to [_MIN_QUESTIONS, _MAX_QUESTIONS]; capping at 12 while
    maximising the sum is what keeps high-mark questions favoured when many
    small ones would otherwise be needed.

    Graceful fallback (never errors): if fewer than _MIN_QUESTIONS questions
    exist, or no subset of >= _MIN_QUESTIONS fits under the target, it returns
    the closest it can with whatever questions are available.
    """
    items = ordered
    n = len(items)
    if n == 0:
        return []
    target = total_marks
    max_k = min(_MAX_QUESTIONS, n)

    reach: list[set[int]] = [set() for _ in range(max_k + 1)]
    reach[0].add(0)
    came: list[dict[int, int]] = [dict() for _ in range(max_k + 1)]
    for idx, q in enumerate(items):
        marks = int(q.get("marks", 0) or 0)
        if marks <= 0:
            continue
        # Walk k high -> low so each question is used at most once per subset.
        for k in range(max_k, 0, -1):
            for s in reach[k - 1]:
                ns = s + marks
                if ns <= target and ns not in reach[k]:
                    reach[k].add(ns)
                    came[k][ns] = idx

    def pick_best(k_min: int, k_max: int):
        exact = [k for k in range(k_min, k_max + 1) if target in reach[k]]
        if exact:
            return target, min(exact)
        best = None
        for k in range(k_min, k_max + 1):
            if reach[k]:
                s = max(reach[k])
                if best is None or s > best[0] or (s == best[0] and k < best[1]):
                    best = (s, k)
        return best

    choice = pick_best(_MIN_QUESTIONS, max_k) or pick_best(1, max_k)
    if choice is None:  # not even one question fits under the target
        return []  # never exceed the target — an empty paper is the only valid answer

    chosen_sum, k = choice
    chosen_idx: list[int] = []
    s = chosen_sum
    while k > 0:
        idx = came[k][s]
        chosen_idx.append(idx)
        s -= int(items[idx].get("marks", 0) or 0)
        k -= 1
    chosen_idx.reverse()
    return [items[i] for i in chosen_idx]


def _as_dict(model: BaseModel) -> dict:
    """Pydantic v2 (model_dump) with a v1 (.dict) fallback."""
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@router.post("/generate-paper", response_model=GeneratePaperResponse)
def generate_paper(
    req: GeneratePaperRequest,
    uid: str = Depends(get_current_uid),
):
    """Build a custom paper from the questions collection."""
    pool = _fetch_pool(req.subject, req.topics, req.paperType)
    ordered = _ordered_pool(pool, req.difficulty)
    selected = _select(ordered, req.totalMarks)

    questions: list[GeneratedQuestion] = []
    mark_scheme: list[MarkSchemeItem] = []
    for number, q in enumerate(selected, start=1):
        marks = int(q.get("marks", 0) or 0)
        questions.append(GeneratedQuestion(
            assignedNumber=number,
            originalPaperCode=q.get("paperCode", "") or "",
            paperType=q.get("paperType", "") or "",
            isSpecimen=bool(q.get("isSpecimen")),
            marks=marks,
            topic=q.get("topic", "") or "",
            difficulty=q.get("difficulty", "") or "",
            questionImageUrl=q.get("questionImageUrl", "") or "",
        ))
        mark_scheme.append(MarkSchemeItem(
            questionNumber=number,
            marks=marks,
            markSchemeText=q.get("markSchemeText", "") or "",
        ))

    return GeneratePaperResponse(
        paperId=str(uuid.uuid4()),
        subject=req.subject,
        totalMarks=sum(item.marks for item in questions),
        numQuestions=len(selected),
        questions=questions,
        markScheme=mark_scheme,
        schoolName=(req.schoolName or "").strip(),
    )


class PoolQuestion(BaseModel):
    """One question's selection metadata (no image / mark scheme) — enough for
    the app to compute the available-marks ceiling for any filter combination.

    `calculatorStatus` lets the app mirror the backend's non-calculator filter
    exactly: a Paper-2 (non-calculator) selection counts only "non_calc_safe"
    questions, so the reactive "Available: X marks" ceiling matches what Generate
    actually produces."""
    paperType: str
    topic: str
    difficulty: str
    marks: int
    calculatorStatus: str = ""


class PoolResponse(BaseModel):
    topics: list[str]
    questions: list[PoolQuestion]


@router.get("/generate-paper/pool", response_model=PoolResponse)
def generate_paper_pool(
    subject: str = "math",
    uid: str = Depends(get_current_uid),
):
    """Return the lightweight selection metadata for every question in a subject
    plus the sorted distinct topics. The Custom Paper form fetches this once and
    computes both the topic chips and the reactive "Available: X marks in
    [difficulty] [paperType] questions" ceiling entirely client-side, so the
    teacher always sees the pool limit before tapping Generate."""
    db = _get_client()
    questions: list[PoolQuestion] = []
    topics: set[str] = set()
    query = db.collection(_QUESTIONS_COLLECTION).where(
        filter=firestore.FieldFilter("subject", "==", subject)
    )
    for doc in query.stream():
        d = doc.to_dict() or {}
        questions.append(PoolQuestion(
            paperType=d.get("paperType", "") or "",
            topic=d.get("topic", "") or "",
            difficulty=d.get("difficulty", "") or "",
            marks=int(d.get("marks", 0) or 0),
            calculatorStatus=d.get("calculatorStatus", "") or "",
        ))
        if d.get("topic"):
            topics.add(d["topic"])
    return PoolResponse(topics=sorted(topics), questions=questions)


# --------------------------------------------------------------------------- #
# PDF rendering
# --------------------------------------------------------------------------- #
# Two engines produce the downloadable PDFs:
#   "latex"  — XeLaTeX typesetting (utils/latex): real maths notation, real
#              answer space, the school's own font. This is the default.
#   "images" — the original reportlab renderer, which pastes the cropped
#              question screenshot. Kept working as an instant rollback: set
#              GA_PDF_ENGINE=images, or pass ?engine=images on the request.
# The response shape is unchanged either way (raw PDF bytes with a
# Content-Disposition attachment header), so nothing downstream has to change.
_DEFAULT_ENGINE = (_os.getenv("GA_PDF_ENGINE") or "latex").strip().lower()


def _engine_for(requested: str | None) -> str:
    choice = (requested or _DEFAULT_ENGINE).strip().lower()
    return "images" if choice == "images" else "latex"


def _pdf_response(pdf: bytes, filename: str, headers: dict | None = None) -> Response:
    merged = {"Content-Disposition": f'attachment; filename="{filename}"'}
    merged.update(headers or {})
    return Response(content=pdf, media_type="application/pdf", headers=merged)


def _render_latex(build, paper: GeneratePaperResponse, filename: str) -> Response:
    """Run a LaTeX build, mapping any failure to a specific HTTP error.

    A malformed LaTeX fragment must fail *this paper* with a message naming the
    offending sub-part — never crash the worker and never return a half-rendered
    file (Part 3.1).
    """
    try:
        built = build(_as_dict(paper))
    except PaperBuildError as exc:
        detail = exc.message
        if exc.part:
            detail = f"{exc.message} (sub-part: {exc.part})"
        raise HTTPException(status_code=exc.status, detail=detail) from exc
    return _pdf_response(built.pdf, filename, {
        "X-GradeAI-Paper-Engine": "latex",
        "X-GradeAI-Paper-Font": f"{built.font_family} ({built.font_mode})",
        "X-GradeAI-Latex-Fallbacks": str(len(built.fallbacks)),
        "X-GradeAI-Compile-Seconds": f"{built.seconds:.1f}",
    })


@router.post("/generate-paper/download-question-paper")
def download_question_paper(
    paper: GeneratePaperResponse,
    engine: str | None = None,
    uid: str = Depends(get_current_uid),
):
    """Render the supplied paper to a question-paper PDF file download."""
    if _engine_for(engine) == "images":
        return _pdf_response(generate_question_paper_pdf(_as_dict(paper)),
                             "custom_math_paper.pdf",
                             {"X-GradeAI-Paper-Engine": "images"})
    return _render_latex(latex_service.question_paper, paper, "custom_math_paper.pdf")


@router.post("/generate-paper/download-mark-scheme")
def download_mark_scheme(
    paper: GeneratePaperResponse,
    engine: str | None = None,
    uid: str = Depends(get_current_uid),
):
    """Render the supplied paper to a mark-scheme PDF file download."""
    if _engine_for(engine) == "images":
        return _pdf_response(generate_mark_scheme_pdf(_as_dict(paper)),
                             "custom_math_mark_scheme.pdf",
                             {"X-GradeAI-Paper-Engine": "images"})
    return _render_latex(latex_service.mark_scheme, paper, "custom_math_mark_scheme.pdf")


@router.get("/generate-paper/typesetting-status")
def typesetting_status(uid: str = Depends(get_current_uid)):
    """Whether the LaTeX engine and the school's font are actually available.

    Lets the app (or an operator) tell "the engine is missing on this deploy"
    apart from "this particular paper failed to compile" without reading logs.
    """
    return {"defaultEngine": _DEFAULT_ENGINE, **latex_service.status()}


# --------------------------------------------------------------------------- #
# Part-level generator (Stage 5 filter + Stage 6 substitution) — schemaVersion 2
# --------------------------------------------------------------------------- #
def _fetch_partlevel_pool(subject: str) -> list[dict]:
    """Every schemaVersion-2 (part-level) question for a subject. Empty until the
    part-level bank is seeded (scripts/seed_partlevel_bank.py)."""
    db = _get_client()
    pool = []
    query = db.collection(_QUESTIONS_COLLECTION).where(
        filter=firestore.FieldFilter("subject", "==", subject))
    for doc in query.stream():
        d = doc.to_dict() or {}
        if d.get("schemaVersion") == 2 and d.get("subParts"):
            pool.append(d)
    return pool


class PartLevelSubPart(BaseModel):
    partId: str
    label: str
    marks: int
    syllabusCodes: list[str]
    imageUrl: str = ""
    substituted: bool = False


class PartLevelQuestionOut(BaseModel):
    assignedNumber: int
    originalPaperCode: str
    marks: int
    syllabusCodes: list[str]
    assembled: bool = False
    subParts: list[PartLevelSubPart]


class PartLevelPaperResponse(BaseModel):
    paperId: str
    subject: str
    targetMarks: int
    totalMarks: int
    numQuestions: int
    questions: list[PartLevelQuestionOut]
    warnings: list[str]
    log: dict


@router.post("/generate-paper/partlevel", response_model=PartLevelPaperResponse)
def generate_paper_partlevel(
    req: GeneratePaperRequest,
    uid: str = Depends(get_current_uid),
):
    """Topic-safe paper generation. Unlike /generate-paper (whole-question, single
    broad tag), this admits a question only if EVERY sub-part's syllabus code is
    within the teacher's selected topics; partially-matching questions have their
    out-of-topic sub-parts safely substituted or the whole question is excluded
    (see partlevel_selection.py). Requires the part-level bank to be seeded."""
    bank = _fetch_partlevel_pool(req.subject)
    if not bank:
        return PartLevelPaperResponse(
            paperId=str(uuid.uuid4()), subject=req.subject, targetMarks=req.totalMarks,
            totalMarks=0, numQuestions=0, questions=[], log={},
            warnings=["Part-level bank not seeded yet. Run scripts/seed_partlevel_bank.py."])

    allowed = _allowed_codes_from_topics(req.topics)
    result = select_paper(bank, allowed, req.totalMarks,
                          paper_type=req.paperType, difficulty=req.difficulty,
                          shuffle=random.shuffle)

    questions: list[PartLevelQuestionOut] = []
    for number, q in enumerate(result["questions"], start=1):
        subs = []
        for sp in q.get("subParts", []):
            subs.append(PartLevelSubPart(
                partId=sp.get("partId", ""), label=sp.get("label", ""),
                marks=int(sp.get("marks", 0) or 0),
                syllabusCodes=sp.get("syllabusCodes", []) or [],
                imageUrl=(sp.get("imageRefs") or [""])[0] and f"/question_parts/{sp['partId']}.png",
                substituted=bool(sp.get("_sourceQuestion") and sp.get("_sourceQuestion") != q.get("id")),
            ))
        questions.append(PartLevelQuestionOut(
            assignedNumber=number, originalPaperCode=q.get("paperCode", "") or "",
            marks=int(q.get("marks", 0) or 0),
            syllabusCodes=q.get("syllabusCodes", []) or [],
            assembled=bool(q.get("assembled")), subParts=subs))

    return PartLevelPaperResponse(
        paperId=str(uuid.uuid4()), subject=req.subject, targetMarks=req.totalMarks,
        totalMarks=result["totalMarks"], numQuestions=result["numQuestions"],
        questions=questions, warnings=result["warnings"], log=result["log"])


@router.post("/generate-paper/partlevel/download-question-paper")
def download_partlevel_question_paper(
    paper: PartLevelPaperResponse,
    uid: str = Depends(get_current_uid),
):
    """Typeset a topic-safe (part-level) paper to a question-paper PDF.

    Only the LaTeX engine can render this shape: a part-level paper may contain
    donor sub-parts spliced in from other questions, so there is no single
    whole-question screenshot that represents it.
    """
    try:
        built = latex_service.question_paper(_as_dict(paper), partlevel=True)
    except PaperBuildError as exc:
        detail = f"{exc.message} (sub-part: {exc.part})" if exc.part else exc.message
        raise HTTPException(status_code=exc.status, detail=detail) from exc
    return _pdf_response(built.pdf, "custom_math_paper.pdf", {
        "X-GradeAI-Paper-Engine": "latex",
        "X-GradeAI-Paper-Font": f"{built.font_family} ({built.font_mode})",
        "X-GradeAI-Latex-Fallbacks": str(len(built.fallbacks)),
    })


@router.post("/generate-paper/partlevel/download-mark-scheme")
def download_partlevel_mark_scheme(
    paper: PartLevelPaperResponse,
    uid: str = Depends(get_current_uid),
):
    """Typeset the mark scheme for a topic-safe (part-level) paper."""
    try:
        built = latex_service.mark_scheme(_as_dict(paper), partlevel=True)
    except PaperBuildError as exc:
        detail = f"{exc.message} (sub-part: {exc.part})" if exc.part else exc.message
        raise HTTPException(status_code=exc.status, detail=detail) from exc
    return _pdf_response(built.pdf, "custom_math_mark_scheme.pdf", {
        "X-GradeAI-Paper-Engine": "latex",
        "X-GradeAI-Latex-Fallbacks": str(len(built.fallbacks)),
    })
