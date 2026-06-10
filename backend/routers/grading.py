"""
routers/grading.py — Grading endpoints.

Endpoints:
  POST /grade                            — single-question grading (sync, fast)
  POST /grade/paper                      — start full-paper grading (async, returns job_id)
  GET  /grade/paper/status/{job_id}      — poll for full-paper grading result

Why /grade/paper is async:
  Full-paper grading takes 30-90 seconds. Cloudflare / Railway's edge proxy
  times out HTTP requests around 100 seconds, producing 502 Bad Gateway
  errors. The async pattern returns a job_id immediately and the frontend
  polls for completion — no single request is ever held open long enough
  to hit the proxy timeout.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from auth import get_current_uid
from database import SessionLocal
from firestore_service import save_grading_result, get_grading_history
from pipeline import run_grading_pipeline, run_full_paper_grading
from shared_schema import (
    GradeRequest,
    GradingResponse,
    PaperGradeRequest,
    StartGradingResponse,
    GradingStatusResponse,
)
from job_store import (
    create_job,
    update_status,
    set_result,
    set_error,
    get_job,
)

router = APIRouter(tags=["grading"])


@router.post("/grade", response_model=GradingResponse)
def grade_answer(
    body: GradeRequest,
    uid: str = Depends(get_current_uid),
):
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


def _run_paper_grading_job(
    job_id: str, paper_id: int, page_images: list[str], uid: str
) -> None:
    """Background-task wrapper around run_full_paper_grading. Never raises."""
    import traceback as _tb
    db = SessionLocal()
    try:
        update_status(job_id, "running")
        result = run_full_paper_grading(
            paper_id=paper_id,
            page_images=page_images,
            db=db,
        )
        # Persist the full-paper result to Firestore under this user. Don't let
        # a Firestore failure fail the job — log it and keep the result.
        try:
            save_grading_result(uid, result)
        except Exception as exc:  # noqa: BLE001
            print(f"[firestore] failed to save paper grading result: {exc}")
        set_result(job_id, result)
    except Exception as exc:
        _tb.print_exc()  # always log the full traceback so Railway logs capture it
        set_error(job_id, str(exc))
    finally:
        db.close()


@router.post("/grade/paper", response_model=StartGradingResponse)
def start_paper_grading(
    body: PaperGradeRequest,
    background_tasks: BackgroundTasks,
    uid: str = Depends(get_current_uid),
):
    """
    Kick off a full-paper grading job. Returns immediately with a job_id;
    the actual grading runs in a background task. Poll
    GET /grade/paper/status/{job_id} to retrieve the result.
    """
    job_id = create_job()
    background_tasks.add_task(
        _run_paper_grading_job, job_id, body.paper_id, body.page_images, uid
    )
    return {"job_id": job_id}


@router.get("/grade/paper/status/{job_id}", response_model=GradingStatusResponse)
def get_paper_grading_status(
    job_id: str,
    uid: str = Depends(get_current_uid),
):
    """Return the current state of a paper-grading job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=404, detail="Job not found or expired"
        )
    return {
        "status": job["status"],
        "result": job["result"],
        "error": job["error"],
    }


@router.get("/history")
def get_history(uid: str = Depends(get_current_uid)):
    """
    Return this user's grading history from Firestore, newest first.
    Each item includes its Firestore document ID as 'marking_id'.
    """
    return get_grading_history(uid)
