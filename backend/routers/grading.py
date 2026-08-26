"""
routers/grading.py — Grading endpoints.

Endpoints:
  POST /grade     — single-question grading (synchronous, fast)
  GET  /history   — this user's grading history from Firestore

Full-paper grading is NO LONGER an HTTP endpoint. It runs through a Firestore
queue: the app writes a teachers/{uid}/markings/{id} document with
status "queued", and a persistent backend listener (see marking_worker.py,
started in main.py) grades it and updates the same document. FastAPI
BackgroundTasks are no longer used anywhere in the grading flow — they were
unreliable for long-running jobs on Railway.
"""

from fastapi import APIRouter, Depends, HTTPException

from auth import get_current_uid
from database import SessionLocal
from firestore_service import save_grading_result, get_grading_history
from pipeline import run_grading_pipeline
from shared_schema import GradeRequest, GradingResponse
from usage_limits import QuotaExceeded, allow_burst, enforce_daily_quota

router = APIRouter(tags=["grading"])


@router.post("/grade", response_model=GradingResponse)
def grade_answer(
    body: GradeRequest,
    uid: str = Depends(get_current_uid),
):
    """
    Accept a student's base64-encoded photo and question ID, run the
    AI grading pipeline, and return the full graded result.

    Cost guardrails run BEFORE any paid Anthropic call: a per-instance burst
    limiter, then a durable per-user + global daily quota. Either being exceeded
    returns 429 and no API call is made.
    """
    if not allow_burst(uid, "grades"):
        raise HTTPException(
            status_code=429,
            detail="You're grading a bit too quickly. Please wait a moment and try again.",
        )
    try:
        enforce_daily_quota(uid, "grades")
    except QuotaExceeded as exc:
        raise HTTPException(status_code=429, detail=exc.message)

    db = SessionLocal()
    try:
        result = run_grading_pipeline(
            question_id=body.question_id,
            image_base64=body.image_base64,
            db=db,
        )
        # Persist the grading result to Firestore under this user. Saving must
        # not break the grading response, so failures here are logged, not raised.
        try:
            save_grading_result(uid, result)
        except Exception as exc:  # noqa: BLE001
            print(f"[firestore] failed to save grading result: {exc}")
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        db.close()


@router.get("/history")
def get_history(uid: str = Depends(get_current_uid)):
    """
    Return this user's grading history from Firestore, newest first.
    Each item includes its Firestore document ID as 'marking_id'.
    """
    return get_grading_history(uid)
