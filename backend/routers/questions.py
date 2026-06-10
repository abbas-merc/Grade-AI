"""
routers/questions.py — Individual question endpoints.

Endpoints:
  GET /questions/{question_id} — question detail with full mark scheme array
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from auth import get_current_uid
from database import get_db
from models import Question
from shared_schema import QuestionResponse

router = APIRouter(prefix="/questions", tags=["questions"])


class MarkPointResponse(BaseModel):
    """One mark point from a question's mark scheme."""
    id: int
    description: str
    marks_for_point: int
    acceptable_alternatives: str = ""


class QuestionDetailResponse(QuestionResponse):
    """QuestionResponse extended with the full mark scheme array."""
    mark_scheme: list[MarkPointResponse] = []


def _serialize_question_detail(question: Question) -> dict:
    points = [
        {
            "id": ms.id,
            "description": ms.description,
            "marks_for_point": ms.marks_for_point,
            "acceptable_alternatives": ms.acceptable_alternatives or "",
        }
        for ms in question.mark_scheme
    ]
    return {
        "id": question.id,
        "question_number": question.question_number,
        "question_text": question.question_text,
        "marks_available": question.marks_available,
        "mark_scheme": points,
    }


@router.get("/{question_id}", response_model=QuestionDetailResponse)
def get_question(
    question_id: int,
    db: Session = Depends(get_db),
    uid: str = Depends(get_current_uid),
):
    """Return a question with its full mark scheme as an array of mark points."""
    try:
        question = db.query(Question).filter(Question.id == question_id).first()
        if not question:
            raise HTTPException(status_code=404, detail="Question not found")
        return _serialize_question_detail(question)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load question: {exc}")
