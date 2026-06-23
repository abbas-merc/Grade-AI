"""
routers/papers.py — Exam paper endpoints.

Endpoints:
  GET /papers                     — list all papers
  GET /papers/{paper_id}/questions — list questions for a paper

Paper content is served from Firestore (see firestore_service.py). Document IDs
are the stringified integer IDs, so we cast back to int to honour the integer
contract that PaperResponse / QuestionResponse declare.
"""

from fastapi import APIRouter, Depends, HTTPException

from auth import get_current_uid
from firestore_service import get_all_papers, get_questions_for_paper
from shared_schema import PaperResponse, QuestionResponse

router = APIRouter(prefix="/papers", tags=["papers"])


def _serialize_paper(paper: dict) -> dict:
    return {
        "id": int(paper["id"]),
        "subject_code": paper.get("subject_code"),
        "year": paper.get("year"),
        "session": paper.get("session"),
        "paper_number": paper.get("paper_number"),
        "tier": paper.get("tier"),
        "total_marks": paper.get("total_marks"),
    }


def _serialize_question(q: dict) -> dict:
    return {
        "id": int(q["id"]),
        "question_number": q.get("question_number"),
        "question_text": q.get("question_text"),
        "marks_available": q.get("marks_available"),
        "question_image_url": q.get("question_image_url") or "",
    }


@router.get("/", response_model=list[PaperResponse])
def list_papers(
    uid: str = Depends(get_current_uid),
):
    """Return all exam papers from Firestore."""
    try:
        papers = get_all_papers()
        return [_serialize_paper(p) for p in papers]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load papers: {exc}")


@router.get("/{paper_id}/questions", response_model=list[QuestionResponse])
def list_questions_for_paper(
    paper_id: int,
    uid: str = Depends(get_current_uid),
):
    """Return all questions belonging to the given paper."""
    try:
        # Verify the paper exists so a missing paper still yields a 404 (the
        # paper set is tiny, so listing all papers here is cheap).
        papers = get_all_papers()
        if not any(str(p["id"]) == str(paper_id) for p in papers):
            raise HTTPException(status_code=404, detail="Paper not found")
        questions = get_questions_for_paper(str(paper_id))
        return [_serialize_question(q) for q in questions]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load questions: {exc}")
