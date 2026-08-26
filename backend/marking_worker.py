"""
marking_worker.py — Firestore-driven grading queue.

Replaces FastAPI BackgroundTasks, which Railway kills for long-running jobs. A
daemon thread holds a persistent Firestore *collection-group* listener over every
``teachers/*/markings`` document whose ``status == "queued"``. When one appears it
is claimed (``status -> "processing"``), graded with the existing
``run_full_paper_grading()`` pipeline, and the same document is updated in place
with the results (``status -> "complete"``) or an error (``status -> "failed"``).

Image transfer: the app writes each page as a document in the marking's
``pages`` subcollection (``{index, image_base64}``) — no Firebase Storage. The
worker reads that subcollection directly, so the pipeline's existing base64
contract is unchanged.

Nothing here touches the grading/marking logic itself — it only orchestrates the
queue, reports progress, and sends the completion push notification.
"""

from __future__ import annotations

import threading
import time
import traceback
from datetime import datetime, timezone, timedelta

import httpx
from firebase_admin import firestore as admin_firestore

from database import SessionLocal
from firestore_service import (
    _get_client,
    get_push_token,
    get_paper_by_id,
    build_paper_name,
)
from pipeline import run_full_paper_grading
from usage_limits import (
    MAX_PAGES_PER_MARKING,
    MAX_QUESTIONS_PER_MARKING,
    QuotaExceeded,
    enforce_daily_quota,
)

_EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
_MARKINGS_COLLECTION = "markings"

# A job still "processing" this long after it was created was almost certainly
# orphaned by a worker crash/restart (a real job finishes in well under a
# minute). The startup sweep fails those so the History row stops spinning.
# Comfortably larger than the worst-case grading time so a genuinely in-flight
# job is never swept.
_STALE_PROCESSING_AFTER = timedelta(minutes=15)

# Progress steps written to the document as the job advances (Issue 3). The
# pipeline emits the middle three via its progress_callback; the worker owns the
# first and last.
_STEP_UPLOADING = "Uploading images"
_STEP_SAVING = "Saving results"

# Guard against the same document being processed twice from overlapping
# snapshot callbacks.
_claimed_lock = threading.Lock()
_claimed: set[str] = set()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid_from_path(path: str) -> str:
    """teachers/{uid}/markings/{id} -> uid."""
    parts = path.split("/")
    return parts[1] if len(parts) >= 4 else ""


def _read_pages(doc_ref) -> list[str]:
    """
    Read the marking's page images from its ``pages`` subcollection, ordered by
    page index, and return raw base64 JPEG strings.

    The app writes one document per page (``{index, image_base64}``) instead of
    uploading to Firebase Storage, so the base64 the pipeline expects is read
    straight out of Firestore — no Storage, no HTTP download.
    """
    pages: list[tuple[int, str]] = []
    for snap in doc_ref.collection("pages").stream():
        data = snap.to_dict() or {}
        b64 = data.get("image_base64")
        if b64:
            pages.append((int(data.get("index", 0)), b64))
    pages.sort(key=lambda item: item[0])
    return [b64 for _, b64 in pages]


def _delete_pages(doc_ref) -> None:
    """Delete the marking's `pages` subcollection once grading has reached a
    terminal state. The page images (photographed student scripts — the most
    sensitive data the app handles, and potentially a minor's work) are only ever
    an INPUT to grading; the result is stored on the parent document and the app
    never re-reads the originals. Removing them enforces data minimisation and
    keeps retained student imagery to the grading window only. Best-effort."""
    try:
        db = _get_client()
        deleted = 0
        while True:
            snaps = list(doc_ref.collection("pages").limit(400).stream())
            if not snaps:
                break
            b = db.batch()
            for snap in snaps:
                b.delete(snap.reference)
            b.commit()
            deleted += len(snaps)
        if deleted:
            print(f"[worker] deleted {deleted} page image(s) for marking {doc_ref.id}")
    except Exception as exc:  # noqa: BLE001 — retention cleanup must never fail a job
        print(f"[worker] failed to delete pages for {doc_ref.id}: {exc}")


def _claim(doc_ref) -> bool:
    """
    Atomically claim a queued document by flipping it to "processing".
    Returns True if this caller won the claim, False if it was already taken.
    """
    db = _get_client()
    transaction = db.transaction()

    @admin_firestore.transactional
    def _txn(txn) -> bool:
        snap = doc_ref.get(transaction=txn)
        data = snap.to_dict() or {}
        if data.get("status") != "queued":
            return False
        txn.update(doc_ref, {"status": "processing", "progress_step": _STEP_UPLOADING})
        return True

    return _txn(transaction)


def _send_completion_push(uid: str, paper_name: str, marking_id: str) -> None:
    """
    Best-effort Expo push with verbose debug logging (Issue 4). Never raises.
    """
    try:
        token = get_push_token(uid)
        if not token:
            print(f"[push] pushToken found: NO (uid={uid}) — skipping notification")
            return
        print(f"[push] pushToken found: YES (uid={uid}) token={token[:20]}…")
        payload = {
            "to": token,
            "title": "Marking Complete",
            "body": f"{paper_name} is ready to view",
            "data": {"markingId": marking_id},
        }
        resp = httpx.post(_EXPO_PUSH_URL, json=payload, timeout=15.0)
        print(f"[push] Expo HTTP status: {resp.status_code}")
        print(f"[push] Expo response body: {resp.text}")
    except Exception as exc:  # noqa: BLE001
        print(f"[push] failed to send notification: {exc}")


# ---------------------------------------------------------------------------
# Job processing
# ---------------------------------------------------------------------------

def _fail_job(doc_ref, message: str) -> None:
    """Flip a marking to "failed" with a teacher-friendly message and clear the
    progress spinner. Used for validation/quota rejections (no scary traceback)."""
    try:
        doc_ref.update({
            "status": "failed",
            "error_message": message,
            "progress_step": admin_firestore.DELETE_FIELD,
        })
    except Exception as exc:  # noqa: BLE001
        print(f"[worker] failed to reject marking {doc_ref.id}: {exc}")


def _process_doc(doc_ref) -> None:
    """Grade one claimed marking document. Runs on its own daemon thread."""
    db = None
    claimed = False
    try:
        if not _claim(doc_ref):
            return  # Another worker/snapshot already took it.
        claimed = True

        snap = doc_ref.get()
        data = snap.to_dict() or {}
        # Derive the owning uid from the DOCUMENT PATH, which the Firestore rules
        # guarantee only the owner can write under (teachers/{uid}/markings/...).
        # We must NOT trust a client-supplied `teacher_uid` body field: a user can
        # set it to anyone's uid in their own document, which would misattribute
        # the push notification and the quota charge. Path is authoritative.
        uid = _uid_from_path(doc_ref.path) or data.get("teacher_uid")
        paper_id = data.get("paper_id")
        paper_name = data.get("paper_name")
        # Custom Paper Generator jobs carry their paper + mark scheme inline
        # (they have no stored paper_id to look up). When present, the pipeline
        # grades against this instead of a papers-collection lookup.
        inline_paper = data.get("inline_paper")

        # Step 1 — read the page images from the `pages` subcollection.
        doc_ref.update({"progress_step": _STEP_UPLOADING})
        page_images = _read_pages(doc_ref)

        # --- Structural caps: bound the size of a single (paid) call before it
        # runs. Page docs are client-written, so a booklet could carry an
        # arbitrary number of pages, and an inline paper an arbitrary number of
        # questions — either would inflate one Anthropic call's cost. Reject
        # oversized jobs with a clear message instead of grading them. ---
        if not page_images:
            _fail_job(doc_ref, "No pages were found for this paper. Please retake and resubmit.")
            return
        if len(page_images) > MAX_PAGES_PER_MARKING:
            _fail_job(
                doc_ref,
                f"This paper has {len(page_images)} pages; the limit is "
                f"{MAX_PAGES_PER_MARKING}. Please split it into smaller submissions.",
            )
            return
        if isinstance(inline_paper, dict):
            q_count = len(inline_paper.get("questions", []) or [])
            if q_count > MAX_QUESTIONS_PER_MARKING:
                _fail_job(
                    doc_ref,
                    "This custom paper has too many questions to mark in one go. "
                    "Please generate a shorter paper.",
                )
                return

        # --- Cost guardrail: durable per-user + global daily quota. Enforced
        # here (Admin SDK) because the job arrives via a direct Firestore write
        # the security rules can't rate-limit. Exceeding it fails the job with a
        # friendly message rather than making the paid call. ---
        try:
            enforce_daily_quota(uid, "markings")
        except QuotaExceeded as exc:
            _fail_job(doc_ref, exc.message)
            return

        print(
            f"[worker] processing marking {doc_ref.id} "
            f"(uid={uid}, paper_id={paper_id}, pages={len(page_images)})"
        )

        # Steps 2-4 — the pipeline reports "Reading handwriting", "Applying mark
        # scheme", and "Calculating scores" as it advances.
        def _progress(step: str) -> None:
            try:
                doc_ref.update({"progress_step": step})
            except Exception as exc:  # noqa: BLE001
                print(f"[worker] progress update failed ({step}): {exc}")

        db = SessionLocal()
        result = run_full_paper_grading(
            paper_id=int(paper_id) if paper_id not in (None, "") else 0,
            page_images=page_images,
            db=db,
            uid=uid,
            progress_callback=_progress,
            inline_paper=inline_paper,
        )

        # Step 5 — persist results into the same document.
        doc_ref.update({"progress_step": _STEP_SAVING})

        if not paper_name:
            if inline_paper is not None:
                paper_name = "Custom Paper"
            else:
                paper = get_paper_by_id(int(paper_id))
                paper_name = build_paper_name(paper) if paper else f"Paper {paper_id}"

        payload = dict(result)
        # Cost telemetry is never persisted to Firestore.
        payload.pop("cost_usd", None)
        payload.pop("cost_cap_reached", None)
        payload["status"] = "complete"
        payload["paper_name"] = paper_name
        payload["progress_step"] = admin_firestore.DELETE_FIELD
        doc_ref.set(payload, merge=True)
        print(f"[worker] marking {doc_ref.id} complete")

        _send_completion_push(uid, paper_name, doc_ref.id)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        try:
            doc_ref.update({"status": "failed", "error_message": str(exc)})
        except Exception as exc2:  # noqa: BLE001
            print(f"[worker] failed to mark marking as failed: {exc2}")
    finally:
        if db is not None:
            db.close()
        # Data minimisation: the student page images are only an input to
        # grading. Once THIS worker's job has reached a terminal state (complete
        # or failed), delete them so captured scripts aren't retained
        # indefinitely. Guarded by `claimed` so we never delete pages out from
        # under another worker that won the claim.
        if claimed:
            _delete_pages(doc_ref)
        with _claimed_lock:
            _claimed.discard(doc_ref.path)


def _on_snapshot(col_snapshot, changes, read_time) -> None:
    """Snapshot callback: dispatch each newly-queued document to a worker thread."""
    for change in changes:
        # ADDED = a document entered the (status==queued) result set.
        if change.type.name not in ("ADDED", "MODIFIED"):
            continue
        doc = change.document
        data = doc.to_dict() or {}
        if data.get("status") != "queued":
            continue

        path = doc.reference.path
        with _claimed_lock:
            if path in _claimed:
                continue
            _claimed.add(path)

        # Grade off the snapshot thread so a long job doesn't block detection of
        # other queued documents.
        threading.Thread(
            target=_process_doc, args=(doc.reference,), daemon=True
        ).start()


# ---------------------------------------------------------------------------
# Listener lifecycle
# ---------------------------------------------------------------------------

def _sweep_stale_processing() -> None:
    """Fail any job stuck in "processing" from a previous (crashed/restarted)
    worker, so it doesn't hang forever. Queued jobs are deliberately NOT touched
    — the listener's initial snapshot re-delivers them for normal processing.
    Runs once at listener startup; best-effort (never raises)."""
    try:
        db = _get_client()
        now = datetime.now(timezone.utc)
        swept = 0
        for snap in db.collection_group(_MARKINGS_COLLECTION).stream():
            data = snap.to_dict() or {}
            if data.get("status") != "processing":
                continue
            created = data.get("created_at")
            # created_at is a tz-aware datetime from Firestore. If it's recent the
            # job may still be legitimately in flight, so leave it alone.
            if isinstance(created, datetime) and (now - created) < _STALE_PROCESSING_AFTER:
                continue
            snap.reference.update({
                "status": "failed",
                "error_message": "Grading was interrupted. Please resubmit this paper.",
                "progress_step": admin_firestore.DELETE_FIELD,
            })
            swept += 1
        if swept:
            print(f"[worker] startup sweep: failed {swept} stale 'processing' job(s)")
    except Exception as exc:  # noqa: BLE001
        print(f"[worker] startup sweep failed (non-fatal): {exc}")


def _run_listener() -> None:
    """Register the collection-group listener and keep it alive forever."""
    # One-time cleanup of jobs orphaned by a prior crash before we start listening.
    _sweep_stale_processing()
    while True:
        try:
            db = _get_client()
            # NOTE: no server-side `where(status == "queued")` filter. A collection
            # *group* query with a field filter requires a COLLECTION_GROUP-scoped
            # index, which Firestore does NOT auto-create — without it on_snapshot
            # raises FailedPrecondition and the queue silently never runs. We listen
            # to the whole group and filter by status inside _on_snapshot instead,
            # which needs no custom index.
            query = db.collection_group(_MARKINGS_COLLECTION)
            watch = query.on_snapshot(_on_snapshot)  # noqa: F841 — hold the watch open
            print(
                "[worker] marking-queue listener started "
                "(collection group 'markings', status filtered in callback)"
            )
            # Hold a reference to the watch and keep this thread alive.
            while True:
                time.sleep(60)
        except Exception as exc:  # noqa: BLE001
            print(f"[worker] listener crashed; restarting in 10s: {exc}")
            traceback.print_exc()
            time.sleep(10)


def start_marking_listener() -> threading.Thread:
    """
    Start the Firestore queue listener on a daemon thread so it runs for the
    lifetime of the process without blocking the FastAPI server.
    """
    thread = threading.Thread(
        target=_run_listener, name="marking-listener", daemon=True
    )
    thread.start()
    return thread
