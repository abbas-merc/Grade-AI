"""
routers/papers.py — Exam paper endpoints.

Endpoints:
  GET /papers                     — list all papers
  GET /papers/{paper_id}/questions — list questions for a paper
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Paper, Question
from shared_schema import PaperResponse, QuestionResponse

router = APIRouter(prefix="/papers", tags=["papers"])


def _serialize_paper(paper: Paper) -> dict:
    return {
        "id": paper.id,
        "subject_code": paper.subject_code,
        "year": paper.year,
        "session": paper.session,
        "paper_number": paper.paper_number,
        "tier": paper.tier,
        "total_marks": paper.total_marks,
    }


def _serialize_question(q: Question) -> dict:
    return {
        "id": q.id,
        "question_number": q.question_number,
        "question_text": q.question_text,
        "marks_available": q.marks_available,
    }


@router.get("/", response_model=list[PaperResponse])
def list_papers(db: Session = Depends(get_db)):
    """Return all exam papers in the database."""
    papers = db.query(Paper).order_by(Paper.id).all()
    return [_serialize_paper(p) for p in papers]


@router.get("/{paper_id}/questions", response_model=list[QuestionResponse])
def list_questions_for_paper(paper_id: int, db: Session = Depends(get_db)):
    """Return all questions belonging to the given paper."""
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    questions = (
        db.query(Question)
        .filter(Question.paper_id == paper_id)
        .order_by(Question.id)
        .all()
    )
    return [_serialize_question(q) for q in questions]
