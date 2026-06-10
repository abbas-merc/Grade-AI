"""
firestore_service.py — Firestore persistence layer for grading results.

This module stores grading results in Cloud Firestore, keyed by the
authenticated user's uid. SQLite remains the source of truth for papers,
questions, and mark schemes — only grading results live in Firestore.

The Firestore client reuses the Firebase Admin app that auth.py already
initialized. We never call firebase_admin.initialize_app() here; instead we
reuse auth._init_firebase_app(), which is idempotent (it no-ops if the default
app already exists), so there is no risk of a second initialization.

Document layout:
    teachers/{uid}/markings/{auto_id}
        ...all fields from the grading result dict...
        created_at: server timestamp
"""

from typing import Any

from firebase_admin import firestore

from auth import _init_firebase_app

# Collection / subcollection names for the grading-result documents.
_TEACHERS_COLLECTION = "teachers"
_MARKINGS_SUBCOLLECTION = "markings"


def _get_client() -> firestore.Client:
    """
    Return a Firestore client bound to the existing Firebase Admin app.

    _init_firebase_app() is idempotent — if auth.py already initialized the
    default app (it does at import time when AUTH_REQUIRED is true) this is a
    no-op. firestore.client() then attaches to that same default app.
    """
    _init_firebase_app()
    return firestore.client()


def save_grading_result(uid: str, result: dict) -> str:
    """
    Save a grading result under teachers/{uid}/markings/ with an auto ID.

    A server-side created_at timestamp is added to the stored document so
    history can be ordered reliably. Returns the new document's ID.
    """
    db = _get_client()
    markings_ref = (
        db.collection(_TEACHERS_COLLECTION)
        .document(uid)
        .collection(_MARKINGS_SUBCOLLECTION)
    )

    # Copy so we never mutate the caller's dict, then stamp the create time.
    payload: dict[str, Any] = dict(result)
    payload["created_at"] = firestore.SERVER_TIMESTAMP

    _, doc_ref = markings_ref.add(payload)
    return doc_ref.id


def get_grading_history(uid: str) -> list:
    """
    Fetch all grading results for a user, newest first.

    Each returned dict includes the Firestore document ID as 'marking_id'.
    """
    db = _get_client()
    markings_ref = (
        db.collection(_TEACHERS_COLLECTION)
        .document(uid)
        .collection(_MARKINGS_SUBCOLLECTION)
    )

    query = markings_ref.order_by(
        "created_at", direction=firestore.Query.DESCENDING
    )

    history: list[dict[str, Any]] = []
    for doc in query.stream():
        data: dict[str, Any] = doc.to_dict() or {}
        data["marking_id"] = doc.id
        history.append(data)
    return history
