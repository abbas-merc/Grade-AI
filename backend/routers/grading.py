"""
routers/grading.py — Grading endpoints.

Endpoints:
  POST /grade       — submit a single student photo for AI grading
  POST /grade/paper — submit page photos of a full exam paper for AI grading
"""

from fastapi import APIRouter, HTTPException

from database import SessionLocal
from pipeline import run_grading_pipeline, run_full_paper_grading
from shared_schema import (
    GradeRequest,
    GradingResponse,
    PaperGradeRequest,
    PaperGradingResponse,
)

router = APIRouter(tags=["grading"])


@router.post("/grade", response_model=GradingResponse)
def grade_answer(body: GradeRequest):
    """
    Accept a student's base64-encoded photo and question ID, run the
    AI grading pipeline, and return the full graded result.
    """
    db = SessionLocal()
    try:
        result = run_grading_pipeline(
            question_id=body.question_id,
            image_base64=body.image_base64,
            db=db,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        db.close()


@router.post("/grade/paper", response_model=PaperGradingResponse)
def grade_paper(body: PaperGradeRequest):
    """
    Accept one or more page photos of a student's answer booklet and grade
    every question in the paper. Page images are base64-encoded JPEGs.

    This endpoint may take 1–3 minutes for a full 47-question paper.
    The client must use a 120-second (or longer) request timeout.
    """
    db = SessionLocal()
    try:
        result = run_full_paper_grading(
            paper_id=body.paper_id,
            page_images=body.page_images,
            db=db,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        db.close()
