"""
firestore_service.py — Firestore persistence layer for GradeAI.

This module stores two kinds of data in Cloud Firestore:

  1. Grading results, keyed by the authenticated user's uid
     (teachers/{uid}/markings/{auto_id}).
  2. Static paper content — papers, their questions, and each question's
     mark scheme — migrated out of SQLite into a papers collection.

The Firestore client reuses the Firebase Admin app that auth.py already
initialized. We never call firebase_admin.initialize_app() here; instead we
reuse auth._init_firebase_app(), which is idempotent (it no-ops if the default
app already exists), so there is no risk of a second initialization.

Document layout:
    teachers/{uid}/markings/{auto_id}
        ...all fields from the grading result dict...
        created_at: server timestamp

    papers/{paper_id}
        id, subject_code, year, session, paper_number, tier, total_marks
        questions/{question_id}
            id, paper_id, question_number, question_text, marks_available
            mark_scheme/{mark_point_id}
                id, description, marks_for_point, acceptable_alternatives

Document IDs for papers/questions/mark points are the stringified SQLite
integer IDs, and each document also carries its integer `id` as a field. This
preserves the integer-ID contract the API schemas depend on (PaperResponse.id,
QuestionResponse.id, etc. are all ints) and lets us order by the numeric `id`
field rather than the lexical document ID (so Q10 sorts after Q2).
"""

from typing import Any, Optional

from firebase_admin import firestore

from auth import _init_firebase_app

# Collection / subcollection names for the grading-result documents.
_TEACHERS_COLLECTION = "teachers"
_MARKINGS_SUBCOLLECTION = "markings"

# Collection / subcollection names for the static paper content.
_PAPERS_COLLECTION = "papers"
_QUESTIONS_SUBCOLLECTION = "questions"
_MARK_SCHEME_SUBCOLLECTION = "mark_scheme"

# Collection for structured marking-request logs.
_LOGS_COLLECTION = "logs"


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


def log_marking_request(uid: str, log_data: dict) -> None:
    """
    Write a structured marking-request log document to the top-level `logs`
    collection. All fields from log_data are stored plus a server-side
    created_at timestamp.

    This function must never raise — logging is best-effort and must not break
    grading. Any error is caught and printed silently.
    """
    try:
        db = _get_client()
        payload: dict[str, Any] = dict(log_data)
        payload["created_at"] = firestore.SERVER_TIMESTAMP
        db.collection(_LOGS_COLLECTION).add(payload)
    except Exception as exc:  # noqa: BLE001
        print(f"[firestore] failed to log marking request: {exc}")


# ---------------------------------------------------------------------------
# Static paper content (papers / questions / mark schemes)
# ---------------------------------------------------------------------------

def _embed_mark_scheme(question_ref) -> list[dict[str, Any]]:
    """
    Read a question's mark_scheme subcollection, ordered by the numeric `id`
    field so the mark points keep their original SQLite order, and return them
    as a list of dicts (each with its document ID exposed as `id`).
    """
    points: list[dict[str, Any]] = []
    for mp in question_ref.collection(_MARK_SCHEME_SUBCOLLECTION).order_by("id").stream():
        mp_data: dict[str, Any] = mp.to_dict() or {}
        mp_data["id"] = mp.id
        points.append(mp_data)
    return points


def seed_paper_to_firestore(paper_data: dict, questions_data: list[dict]) -> str:
    """
    Write one paper, its questions, and each question's mark scheme to Firestore.

    Structure created:
        papers/{paper_id}                      <- paper_data (minus nested lists)
            questions/{question_id}            <- each item of questions_data
                mark_scheme/{mark_point_id}    <- each item of question["mark_scheme"]

    When a dict carries an `id`, that value (stringified) becomes the document
    ID so the original SQLite integer IDs are preserved end to end; otherwise
    Firestore assigns an auto ID. The integer `id` is also written as a field so
    documents can be ordered numerically.

    Args:
        paper_data:     Paper metadata. May include `id`. Any nested
                        `questions` key is ignored (questions come from the
                        second argument).
        questions_data: List of question dicts. Each may include `id` and a
                        `mark_scheme` list of mark-point dicts.

    Returns:
        The Firestore paper document ID.
    """
    db = _get_client()

    paper_id = paper_data.get("id")
    if paper_id is not None:
        paper_ref = db.collection(_PAPERS_COLLECTION).document(str(paper_id))
    else:
        paper_ref = db.collection(_PAPERS_COLLECTION).document()

    paper_payload = {
        k: v for k, v in paper_data.items() if k not in ("questions", "mark_scheme")
    }
    paper_ref.set(paper_payload)

    for question in questions_data:
        q_id = question.get("id")
        if q_id is not None:
            q_ref = paper_ref.collection(_QUESTIONS_SUBCOLLECTION).document(str(q_id))
        else:
            q_ref = paper_ref.collection(_QUESTIONS_SUBCOLLECTION).document()

        q_payload = {
            k: v for k, v in question.items() if k != "mark_scheme"
        }
        q_ref.set(q_payload)

        for mark_point in question.get("mark_scheme", []) or []:
            mp_id = mark_point.get("id")
            if mp_id is not None:
                mp_ref = q_ref.collection(_MARK_SCHEME_SUBCOLLECTION).document(str(mp_id))
            else:
                mp_ref = q_ref.collection(_MARK_SCHEME_SUBCOLLECTION).document()
            mp_ref.set(dict(mark_point))

    return paper_ref.id


def get_all_papers() -> list[dict]:
    """
    Fetch every paper from the papers collection, ordered by the numeric `id`
    field. Each returned dict includes the document ID as `id`.
    """
    db = _get_client()
    papers: list[dict[str, Any]] = []
    for doc in db.collection(_PAPERS_COLLECTION).order_by("id").stream():
        data: dict[str, Any] = doc.to_dict() or {}
        data["id"] = doc.id
        papers.append(data)
    return papers


def get_questions_for_paper(paper_id: str) -> list[dict]:
    """
    Fetch all questions under papers/{paper_id}/questions with each question's
    mark scheme points embedded under a `mark_scheme` key.

    Questions are ordered by their numeric `id` field, which mirrors the
    original SQLite ``ORDER BY questions.id`` (i.e. question sequence). Each
    returned dict includes the document ID as `id`.
    """
    db = _get_client()
    questions_ref = (
        db.collection(_PAPERS_COLLECTION)
        .document(str(paper_id))
        .collection(_QUESTIONS_SUBCOLLECTION)
    )

    questions: list[dict[str, Any]] = []
    for doc in questions_ref.order_by("id").stream():
        data: dict[str, Any] = doc.to_dict() or {}
        data["id"] = doc.id
        data["mark_scheme"] = _embed_mark_scheme(doc.reference)
        questions.append(data)
    return questions


def get_question_by_id(question_id: int | str) -> Optional[dict]:
    """
    Find a single question across all papers by its (document) ID and return it
    with its mark scheme points embedded under a `mark_scheme` key.

    The questions live in per-paper subcollections, so we look the question up
    by its known document ID inside each paper rather than running a
    collection-group query (which would require a manually created index). The
    paper set is tiny, so this is one or two reads.

    Returns the question dict (with `id` set to the document ID) or None if no
    paper contains a question with that ID.
    """
    db = _get_client()
    for paper in db.collection(_PAPERS_COLLECTION).stream():
        q_ref = (
            paper.reference.collection(_QUESTIONS_SUBCOLLECTION).document(str(question_id))
        )
        snap = q_ref.get()
        if snap.exists:
            data: dict[str, Any] = snap.to_dict() or {}
            data["id"] = snap.id
            data["mark_scheme"] = _embed_mark_scheme(q_ref)
            return data
    return None
