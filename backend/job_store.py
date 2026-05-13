"""
job_store.py — In-memory async job store for long-running grading requests.

Why this exists:
  Cloudflare / Railway's edge proxy times out HTTP requests around 100 seconds.
  Full-paper grading routinely takes 30-90 seconds and edges into the timeout
  zone, producing 502 Bad Gateway errors mid-request.

  This module backs an async pattern: the start endpoint returns a job_id
  immediately and the grading runs in a FastAPI BackgroundTask. The frontend
  polls a status endpoint until the job is done. No single HTTP request is
  ever held open long enough to hit the proxy timeout.

Storage is in-process and thread-safe. Jobs older than 1 hour are pruned on
each read. For multi-instance production, swap this for Redis or a DB row.
"""

from __future__ import annotations

import time
import uuid
from threading import Lock
from typing import Any, Literal

JobStatus = Literal["pending", "running", "done", "error"]

_LOCK = Lock()
_JOBS: dict[str, dict[str, Any]] = {}
_TTL_SECONDS = 3600


def create_job() -> str:
    """Allocate a new job and return its id."""
    job_id = uuid.uuid4().hex
    with _LOCK:
        _JOBS[job_id] = {
            "status": "pending",
            "created_at": time.time(),
            "result": None,
            "error": None,
        }
    return job_id


def update_status(job_id: str, status: JobStatus) -> None:
    with _LOCK:
        if job_id in _JOBS:
            _JOBS[job_id]["status"] = status


def set_result(job_id: str, result: dict) -> None:
    with _LOCK:
        if job_id in _JOBS:
            _JOBS[job_id]["status"] = "done"
            _JOBS[job_id]["result"] = result


def set_error(job_id: str, message: str) -> None:
    with _LOCK:
        if job_id in _JOBS:
            _JOBS[job_id]["status"] = "error"
            _JOBS[job_id]["error"] = message


def get_job(job_id: str) -> dict[str, Any] | None:
    _evict_expired()
    with _LOCK:
        return _JOBS.get(job_id)


def _evict_expired() -> None:
    now = time.time()
    with _LOCK:
        expired = [
            jid for jid, v in _JOBS.items() if now - v["created_at"] > _TTL_SECONDS
        ]
        for jid in expired:
            del _JOBS[jid]
