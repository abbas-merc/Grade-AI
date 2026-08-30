"""
usage_limits.py — Server-side spend/abuse guardrails for GradeAI.

Every marking and single-question grade triggers a real (paid) Anthropic API
call. The mobile app enqueues marking jobs by writing directly to Firestore
(teachers/{uid}/markings), so the only place these limits can be enforced is
server-side, in code that runs with the Admin SDK — the Firestore security rules
cannot express "at most N jobs per day". This module is that enforcement point.

Two independent controls, both fail-OPEN on infrastructure error (a transient
Firestore hiccup must not block a paying teacher; the Anthropic Console monthly
spend cap is the ultimate backstop) but fail-CLOSED on an exceeded quota:

  1. enforce_daily_quota(uid, action) — a per-user AND a global per-day counter,
     persisted in Firestore so they survive process restarts and span every
     Railway instance. This is the load-bearing cost control.

  2. allow_burst(uid, action) — a small in-process sliding-window limiter that
     blunts rapid bursts from a single account within one instance. Best-effort
     latency/DoS protection layered on top of (1); NOT a substitute for it.

All limits are configurable via environment variables so they can be tuned
without a code change. Defaults are deliberately generous for a real tuition
teacher yet bound worst-case spend hard.

Counter documents:
    teachers/{uid}/usage/{YYYYMMDD}   { markings: int, grades: int }
    usage_global/{YYYYMMDD}           { markings: int, grades: int }
Both are backend-only (the Firestore rules default-deny the client from reading
or writing them), so a user can neither see nor tamper with their own quota.
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from firebase_admin import firestore as admin_firestore

from firestore_service import _get_client, _TEACHERS_COLLECTION

_USAGE_SUBCOLLECTION = "usage"
_GLOBAL_USAGE_COLLECTION = "usage_global"


def _int_env(name: str, default: int) -> int:
    """Read a positive integer env var, falling back to `default` on anything odd."""
    try:
        value = int(str(os.getenv(name, "")).strip())
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


# Per-user daily caps. A tuition teacher marking a couple of classes a day sits
# comfortably under these; a single compromised account cannot run up more than
# (cap x per-call ceiling) of spend in a day.
MAX_MARKINGS_PER_DAY_PER_USER = _int_env("MAX_MARKINGS_PER_DAY_PER_USER", 60)
MAX_GRADES_PER_DAY_PER_USER = _int_env("MAX_GRADES_PER_DAY_PER_USER", 200)

# Global daily kill-switch across ALL users — a backstop against many-account
# abuse. If this is ever hit the app pauses new jobs until the next UTC day;
# raise it as the user base grows.
MAX_MARKINGS_PER_DAY_GLOBAL = _int_env("MAX_MARKINGS_PER_DAY_GLOBAL", 2000)
MAX_GRADES_PER_DAY_GLOBAL = _int_env("MAX_GRADES_PER_DAY_GLOBAL", 5000)

# Structural caps on a single job so one request can't be pathologically large
# (a 100-page booklet or a hand-crafted 500-question inline paper would make one
# very expensive Anthropic call).
MAX_PAGES_PER_MARKING = _int_env("MAX_PAGES_PER_MARKING", 20)
MAX_QUESTIONS_PER_MARKING = _int_env("MAX_QUESTIONS_PER_MARKING", 60)

# In-process burst limiter: at most this many of an action per uid per window.
_BURST_MAX = _int_env("BURST_MAX_PER_MINUTE", 20)
_BURST_WINDOW_SECONDS = 60.0

_PER_USER_LIMITS = {
    "markings": MAX_MARKINGS_PER_DAY_PER_USER,
    "grades": MAX_GRADES_PER_DAY_PER_USER,
}
_GLOBAL_LIMITS = {
    "markings": MAX_MARKINGS_PER_DAY_GLOBAL,
    "grades": MAX_GRADES_PER_DAY_GLOBAL,
}


class QuotaExceeded(Exception):
    """Raised when a per-user or global daily quota is exhausted. Carries a
    teacher-friendly message safe to surface directly in the UI."""

    def __init__(self, message: str, scope: str):
        super().__init__(message)
        self.message = message
        self.scope = scope  # "user" | "global"


def _utc_day_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _incr_if_below(doc_ref, field: str, limit: int) -> bool:
    """Atomically increment `field` on `doc_ref` iff it is currently < limit.

    Returns True if the increment happened (caller is within quota), False if the
    limit was already reached. Uses a Firestore transaction so concurrent workers
    can never both slip past the cap.
    """
    db = _get_client()
    transaction = db.transaction()

    @admin_firestore.transactional
    def _txn(txn) -> bool:
        snap = doc_ref.get(transaction=txn)
        data = snap.to_dict() or {}
        current = int(data.get(field, 0) or 0)
        if current >= limit:
            return False
        txn.set(doc_ref, {field: current + 1}, merge=True)
        return True

    return _txn(transaction)


def enforce_daily_quota(uid: str, action: str) -> None:
    """Enforce the per-user and global daily cap for `action` ("markings" |
    "grades"). Increments both counters for `uid` and the day.

    Raises QuotaExceeded (fail-CLOSED) when a cap is hit. On any *infrastructure*
    error reading/writing the counters, logs and returns without raising
    (fail-OPEN) so a Firestore blip never blocks a legitimate teacher — the
    Anthropic Console spend cap remains the hard financial backstop.
    """
    user_limit = _PER_USER_LIMITS.get(action)
    global_limit = _GLOBAL_LIMITS.get(action)
    if user_limit is None or global_limit is None:
        return  # Unknown action — nothing to enforce.

    day = _utc_day_key()
    try:
        db = _get_client()
        user_ref = (
            db.collection(_TEACHERS_COLLECTION)
            .document(uid)
            .collection(_USAGE_SUBCOLLECTION)
            .document(day)
        )
        if not _incr_if_below(user_ref, action, user_limit):
            raise QuotaExceeded(
                "You've reached today's grading limit for this account. "
                "It resets tomorrow — thanks for understanding.",
                scope="user",
            )

        global_ref = db.collection(_GLOBAL_USAGE_COLLECTION).document(day)
        if not _incr_if_below(global_ref, action, global_limit):
            raise QuotaExceeded(
                "Grading is briefly paused because today's overall usage limit "
                "was reached. Please try again a little later.",
                scope="global",
            )
    except QuotaExceeded:
        raise
    except Exception as exc:  # noqa: BLE001 — infra failure must not block grading
        print(f"[usage] quota check failed open for uid={uid} action={action}: {exc}")


# ---------------------------------------------------------------------------
# In-process burst limiter (best-effort, per instance)
# ---------------------------------------------------------------------------

_burst_lock = threading.Lock()
_burst_hits: dict[tuple[str, str], deque] = defaultdict(deque)


def allow_burst(uid: str, action: str) -> bool:
    """Return True if `uid` is under the per-minute burst cap for `action`, and
    record this hit. Sliding window, in-memory — resets on restart and is scoped
    to a single instance, so it only blunts rapid bursts; the daily Firestore
    quota is the durable control."""
    now = time.monotonic()
    key = (uid, action)
    with _burst_lock:
        hits = _burst_hits[key]
        cutoff = now - _BURST_WINDOW_SECONDS
        while hits and hits[0] < cutoff:
            hits.popleft()
        if len(hits) >= _BURST_MAX:
            return False
        hits.append(now)
        return True
