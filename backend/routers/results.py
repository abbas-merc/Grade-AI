"""
routers/results.py — Shareable marked-results PDF.

Endpoint (mounted under /api by main.py):
  POST /api/results/download-pdf
      Render a completed marking to a clean, branded PDF (file download) that a
      teacher can hand to a student or parent.

Two ways to supply the result, mirroring the existing download endpoints in
paper_generator.py while adding the ownership check a result requires:

  * `result_id` (preferred): the Firestore marking document ID. The document is
    read from teachers/{uid}/markings/{result_id} for the AUTHENTICATED uid, so
    a teacher can only ever download their own students' results — another
    teacher's id simply doesn't resolve under their path (404).
  * `result` (inline fallback): the full result object the client already holds
    in memory, used for legacy entries that predate the stored marking id. This
    leaks nothing — the caller is only ever rendering data it already possesses.
"""

from __future__ import annotations

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from auth import get_current_uid
from firestore_service import get_marking_for_user
from utils.pdf_generator import format_marked_date, generate_results_pdf

router = APIRouter(prefix="/results", tags=["results"])


class DownloadResultsRequest(BaseModel):
    # Preferred: the marking document id, resolved under the caller's own uid.
    result_id: Optional[str] = None
    # Fallback: the full marking/result object (when no stored id is available).
    result: Optional[dict] = None
    # Optional display fields used when only an inline result is sent (and the
    # backend has no document to read them from).
    paper_name: Optional[str] = None
    graded_at: Optional[str] = None


def _sanitize_filename_part(text: str) -> str:
    """Make a filename-safe slug: non-alphanumerics collapse to single
    underscores, with leading/trailing underscores trimmed."""
    slug = re.sub(r"[^A-Za-z0-9]+", "_", text or "").strip("_")
    return slug or "results"


@router.post("/download-pdf")
def download_results_pdf(
    req: DownloadResultsRequest,
    uid: str = Depends(get_current_uid),
):
    """Render a completed marking to a PDF and return it as a file download."""
    if req.result_id:
        # Ownership is enforced by the read path: scoped to the caller's uid.
        data = get_marking_for_user(uid, req.result_id)
        if data is None:
            raise HTTPException(
                status_code=404,
                detail="Result not found, or you don't have access to it.",
            )
    elif req.result is not None:
        data = dict(req.result)
    else:
        raise HTTPException(
            status_code=422,
            detail="Provide either 'result_id' or 'result'.",
        )

    # Backfill display fields the client supplied separately (only used when the
    # data itself doesn't already carry them).
    if req.paper_name and not data.get("paper_name"):
        data["paper_name"] = req.paper_name
    if req.graded_at and not data.get("graded_at"):
        data["graded_at"] = req.graded_at

    pdf = generate_results_pdf(data)

    paper_name = str(data.get("paper_name") or "results")
    date_label = format_marked_date(data)
    filename = (
        f"results_{_sanitize_filename_part(paper_name)}"
        f"_{_sanitize_filename_part(date_label)}.pdf"
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
