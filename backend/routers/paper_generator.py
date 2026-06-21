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

Diagram questions (hasImage == true) are now included: each carries an
`imageUrl` ("/diagrams/<id>.png") pointing at the figure extracted from the
source paper. The PDF generator embeds it inline and the app renders it in the
preview card.
"""
from __future__ import annotations

import random
import uuid
from itertools import zip_longest
from typing import Literal

from fastapi import APIRouter, Depends, Response
from firebase_admin import firestore
from pydantic import BaseModel, Field

from auth import get_current_uid
from firestore_service import _get_client
from utils.pdf_generator import (
    generate_mark_scheme_pdf,
    generate_question_paper_pdf,
)

router = APIRouter(tags=["paper-generator"])

_QUESTIONS_COLLECTION = "questions"
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
    topics: list[str] = Field(min_length=1)
    totalMarks: int = Field(ge=20, le=200)
    difficulty: Literal["mixed", "easy", "medium", "hard"] = "mixed"


class GeneratedQuestion(BaseModel):
    assignedNumber: int
    originalPaperCode: str
    marks: int
    questionText: str
    topic: str
    difficulty: str
    # Diagram support: hasImage flags a figure question; imageUrl is the
    # host-agnostic path ("/diagrams/<id>.png") the app prepends BASE_URL to and
    # the PDF generator resolves to a local file. Empty for text-only questions.
    hasImage: bool = False
    imageUrl: str = ""


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


# --------------------------------------------------------------------------- #
# Selection logic
# --------------------------------------------------------------------------- #
def _fetch_pool(subject: str, topics: list[str]) -> list[dict]:
    """Return questions matching subject and (if given) topics.

    We filter on `subject` in Firestore (auto single-field index) and apply the
    topic filter in Python — the collection is tiny, so this avoids needing a
    composite index or running into `in`-query limits. Diagram questions
    (hasImage == true) are included now that each carries an `imageUrl`.
    """
    db = _get_client()
    topic_set = set(topics or [])
    pool: list[dict] = []
    query = db.collection(_QUESTIONS_COLLECTION).where(
        filter=firestore.FieldFilter("subject", "==", subject)
    )
    for doc in query.stream():
        data = doc.to_dict() or {}
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
    pool = _fetch_pool(req.subject, req.topics)
    ordered = _ordered_pool(pool, req.difficulty)
    selected = _select(ordered, req.totalMarks)

    questions: list[GeneratedQuestion] = []
    mark_scheme: list[MarkSchemeItem] = []
    for number, q in enumerate(selected, start=1):
        marks = int(q.get("marks", 0) or 0)
        questions.append(GeneratedQuestion(
            assignedNumber=number,
            originalPaperCode=q.get("paperCode", "") or "",
            marks=marks,
            questionText=q.get("questionText", "") or "",
            topic=q.get("topic", "") or "",
            difficulty=q.get("difficulty", "") or "",
            hasImage=bool(q.get("hasImage")),
            imageUrl=q.get("imageUrl", "") or "",
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
    )


@router.post("/generate-paper/download-question-paper")
def download_question_paper(
    paper: GeneratePaperResponse,
    uid: str = Depends(get_current_uid),
):
    """Render the supplied paper to a question-paper PDF file download."""
    pdf = generate_question_paper_pdf(_as_dict(paper))
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="custom_math_paper.pdf"'},
    )


@router.post("/generate-paper/download-mark-scheme")
def download_mark_scheme(
    paper: GeneratePaperResponse,
    uid: str = Depends(get_current_uid),
):
    """Render the supplied paper to a mark-scheme PDF file download."""
    pdf = generate_mark_scheme_pdf(_as_dict(paper))
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="custom_math_mark_scheme.pdf"'},
    )
