"""
routers/questions.py — Individual question endpoints.

Endpoints:
  GET /questions/{question_id} — question detail with full mark scheme array

Question content is served from Firestore (see firestore_service.py). Document
IDs are the stringified integer IDs, so we cast back to int to honour the
integer contract that QuestionResponse / MarkPointResponse declare.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_uid
from firestore_service import get_distinct_topics, get_question_by_id
from shared_schema import QuestionResponse

router = APIRouter(prefix="/questions", tags=["questions"])


class TopicsResponse(BaseModel):
    """Deduplicated list of topics available for a subject."""
    topics: list[str] = []


class MarkPointResponse(BaseModel):
    """One mark point from a question's mark scheme."""
    id: int
    description: str
    marks_for_point: int
    acceptable_alternatives: str = ""


class QuestionDetailResponse(QuestionResponse):
    """QuestionResponse extended with the full mark scheme array."""
    mark_scheme: list[MarkPointResponse] = []


def _serialize_question_detail(question: dict) -> dict:
    points = [
        {
            "id": int(ms["id"]),
            "description": ms.get("description"),
            "marks_for_point": ms.get("marks_for_point"),
            "acceptable_alternatives": ms.get("acceptable_alternatives") or "",
        }
        for ms in question.get("mark_scheme", [])
    ]
    return {
        "id": int(question["id"]),
        "question_number": question.get("question_number"),
        "question_text": question.get("question_text"),
        "marks_available": question.get("marks_available"),
        "mark_scheme": points,
    }


@router.get("/topics", response_model=TopicsResponse)
def get_topics(
    subject: str,
    uid: str = Depends(get_current_uid),
):
    """Return the deduplicated list of topics for a subject, used by the Custom
    Paper Generator to populate its topic picker.

    Declared BEFORE `/{question_id}` so the literal path "topics" is matched
    here rather than being coerced into the integer `question_id` param.
    """
    try:
        return {"topics": get_distinct_topics(subject)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load topics: {exc}")


@router.get("/{question_id}", response_model=QuestionDetailResponse)
def get_question(
    question_id: int,
    uid: str = Depends(get_current_uid),
):
    """Return a question with its full mark scheme as an array of mark points."""
    try:
        question = get_question_by_id(question_id)
        if not question:
            raise HTTPException(status_code=404, detail="Question not found")
        return _serialize_question_detail(question)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load question: {exc}")
