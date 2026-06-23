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

    papers/{subjectCode}_paper{paperNumber}_{session}   e.g. 0625_paper4_mj2025
        id, subject_code, year, session, paper_number, tier, total_marks
        questions/{question_id}
            id, paper_id, question_number, question_text, marks_available
            mark_scheme/{mark_point_id}
                id, description, marks_for_point, acceptable_alternatives

Paper document IDs follow the human-readable convention
``{subjectCode}_paper{paperNumber}_{session}`` (e.g. ``0625_paper4_mj2025``),
built by make_paper_doc_id() from the paper's own fields. Each paper document
still carries its integer `id` as a field, and questions / mark points keep
their stringified integer IDs as document IDs. This preserves the integer-ID
contract the API schemas depend on (PaperResponse.id, QuestionResponse.id, etc.
are all ints): callers look papers up by the numeric `id` field, never by the
document ID, and order by that numeric field (so Q10 sorts after Q2).
"""

import re
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

# Flat top-level collection for the Custom Paper Generator. Distinct from the
# nested papers/{id}/questions content above: these documents are denormalized
# (topic, subtopic, paperCode, ...) so the generator can query across papers by
# subject + topic. See app/types/question.ts for the document schema.
_CUSTOM_QUESTIONS_COLLECTION = "questions"

# Firestore caps a single batched write at 500 operations.
_BATCH_LIMIT = 500


def _get_client() -> firestore.Client:
    """
    Return a Firestore client bound to the existing Firebase Admin app.

    _init_firebase_app() is idempotent — if auth.py already initialized the
    default app (it does at import time when AUTH_REQUIRED is true) this is a
    no-op. firestore.client() then attaches to that same default app.
    """
    _init_firebase_app()
    return firestore.client()


# ---------------------------------------------------------------------------
# Paper document-ID convention
# ---------------------------------------------------------------------------

def _session_token(session: str, year: int | str) -> str:
    """
    Compress a (session, year) pair into the short token used inside a paper
    document ID, e.g. ("May/June", 2025) -> "mj2025", ("Oct/Nov", 2024) ->
    "on2024", ("Feb/March", 2026) -> "fm2026".
    """
    s = (session or "").strip().lower()
    if s.startswith("m") or "june" in s or "jun" in s:
        abbr = "mj"
    elif s.startswith("o") or "nov" in s:
        abbr = "on"
    elif s.startswith("f") or "march" in s or "mar" in s:
        abbr = "fm"
    else:
        # Fallback: first two alphanumerics of whatever was provided.
        abbr = re.sub(r"[^a-z0-9]", "", s)[:2] or "xx"
    return f"{abbr}{year}"


def make_paper_doc_id(paper_data: dict) -> Optional[str]:
    """
    Build the human-readable paper document ID from a paper's own fields:
        {subject_code}_paper{paper_number}_{session_token}
    e.g. {"subject_code": "0625", "paper_number": 4, "session": "May/June",
          "year": 2025} -> "0625_paper4_mj2025".

    Returns None if any required field is missing, so callers can fall back to
    the integer-ID document naming.

    NOTE: `variant` is intentionally not part of the ID. If two variants of the
    same subject/paper/session/year are ever seeded, they would collide on the
    same document ID — add the variant to this convention if that day comes.
    """
    subject_code = paper_data.get("subject_code")
    paper_number = paper_data.get("paper_number")
    session = paper_data.get("session")
    year = paper_data.get("year")
    if subject_code is None or paper_number is None or session is None or year is None:
        return None
    return f"{subject_code}_paper{paper_number}_{_session_token(str(session), year)}"


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
    # Cost telemetry must never be persisted to Firestore — it is internal
    # accounting, not marking data. Strip it from the stored document (the API
    # response still carries cost_usd/cost_cap_reached for terminal logging).
    payload.pop("cost_usd", None)
    payload.pop("cost_cap_reached", None)
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


def get_marking_for_user(uid: str, marking_id: str) -> Optional[dict]:
    """
    Fetch a single marking document at teachers/{uid}/markings/{marking_id}.

    Because the read is scoped to the caller's own uid path, this also enforces
    ownership: a teacher can only ever resolve a marking that lives under their
    own subcollection. A marking_id belonging to another teacher simply does not
    exist here and returns None (the caller turns that into a 404).

    The Firestore document ID is exposed as 'marking_id'. Returns None if the
    document does not exist.
    """
    db = _get_client()
    snap = (
        db.collection(_TEACHERS_COLLECTION)
        .document(uid)
        .collection(_MARKINGS_SUBCOLLECTION)
        .document(marking_id)
        .get()
    )
    if not snap.exists:
        return None
    data: dict[str, Any] = snap.to_dict() or {}
    data["marking_id"] = snap.id
    return data


def create_pending_marking(
    uid: str, paper_id: int, paper_name: str, total_marks_available: int
) -> str:
    """
    Create a placeholder marking document with status "processing" so the
    History tab can show the job as in-progress before grading finishes.

    Returns the new document's ID, which is later passed to finalize_marking().
    """
    db = _get_client()
    markings_ref = (
        db.collection(_TEACHERS_COLLECTION)
        .document(uid)
        .collection(_MARKINGS_SUBCOLLECTION)
    )
    payload: dict[str, Any] = {
        "status": "processing",
        "paper_id": paper_id,
        "paper_name": paper_name,
        "total_marks_awarded": 0,
        "total_marks_available": total_marks_available,
        "results": [],
        "created_at": firestore.SERVER_TIMESTAMP,
    }
    _, doc_ref = markings_ref.add(payload)
    return doc_ref.id


def finalize_marking(
    uid: str, marking_id: str, result: dict, paper_name: Optional[str] = None
) -> None:
    """
    Write the completed grading result onto the existing pending marking
    document and flip its status to "complete". Merges so the created_at and
    any display fields written at creation are preserved.

    Cost telemetry is never persisted (see save_grading_result).
    """
    db = _get_client()
    doc_ref = (
        db.collection(_TEACHERS_COLLECTION)
        .document(uid)
        .collection(_MARKINGS_SUBCOLLECTION)
        .document(marking_id)
    )
    payload: dict[str, Any] = dict(result)
    payload.pop("cost_usd", None)
    payload.pop("cost_cap_reached", None)
    payload.pop("marking_id", None)  # doc.id is authoritative; never store it as a field
    payload["status"] = "complete"
    if paper_name:
        payload["paper_name"] = paper_name
    doc_ref.set(payload, merge=True)


def mark_marking_error(uid: str, marking_id: str) -> None:
    """Flip a marking document's status to "error" so the row stops spinning."""
    db = _get_client()
    doc_ref = (
        db.collection(_TEACHERS_COLLECTION)
        .document(uid)
        .collection(_MARKINGS_SUBCOLLECTION)
        .document(marking_id)
    )
    try:
        doc_ref.set({"status": "error"}, merge=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[firestore] failed to mark marking {marking_id} as error: {exc}")


def get_push_token(uid: str) -> Optional[str]:
    """
    Read the Expo push token stored at teachers/{uid}.pushToken, or None if the
    teacher document or field is absent.
    """
    db = _get_client()
    snap = db.collection(_TEACHERS_COLLECTION).document(uid).get()
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    token = data.get("pushToken")
    return token if isinstance(token, str) and token else None


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

    # Document ID follows the human-readable convention (e.g. 0625_paper4_mj2025).
    # The integer `id` is kept as a *field* on the document so the API/frontend
    # integer-ID contract is unchanged. Fall back to the integer ID, then an
    # auto ID, only if the fields needed to build the readable ID are missing.
    doc_id = make_paper_doc_id(paper_data)
    if doc_id is not None:
        paper_ref = db.collection(_PAPERS_COLLECTION).document(doc_id)
    elif paper_data.get("id") is not None:
        paper_ref = db.collection(_PAPERS_COLLECTION).document(str(paper_data["id"]))
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


def _find_paper_ref(db, paper_id: int | str):
    """
    Resolve a paper's document reference from its integer `id` field.

    Paper document IDs are human-readable strings (e.g. 0625_paper4_mj2025), so
    we can no longer address a paper by `.document(str(paper_id))`. Instead we
    match on the integer `id` field. The paper set is tiny, so a linear scan is
    cheaper than maintaining a composite index and mirrors get_question_by_id().

    Returns the DocumentReference, or None if no paper has that `id`.
    """
    target = str(paper_id)
    for doc in db.collection(_PAPERS_COLLECTION).stream():
        data = doc.to_dict() or {}
        if str(data.get("id")) == target:
            return doc.reference
    return None


def get_paper_by_id(paper_id: int | str) -> Optional[dict]:
    """
    Fetch a single paper's fields by its integer `id` field, or None if no paper
    matches. The human-readable document ID is exposed as `doc_id`.
    """
    db = _get_client()
    ref = _find_paper_ref(db, paper_id)
    if ref is None:
        return None
    data = ref.get().to_dict() or {}
    data["doc_id"] = ref.id
    return data


_SESSION_DISPLAY = {
    "May/June": "M/J",
    "October/November": "O/N",
    "Oct/Nov": "O/N",
    "Feb/March": "F/M",
}


def build_paper_name(paper: dict) -> str:
    """
    Build a human-readable paper name for display / push notifications, e.g.
    "IGCSE 0625 Paper 4 M/J 2025".
    """
    subject = paper.get("subject_code", "")
    number = paper.get("paper_number", "")
    year = paper.get("year", "")
    session = str(paper.get("session", "")).strip()
    session_display = _SESSION_DISPLAY.get(session, session)
    return f"IGCSE {subject} Paper {number} {session_display} {year}".strip()


def get_all_papers() -> list[dict]:
    """
    Fetch every paper from the papers collection, ordered by the numeric `id`
    field. The integer `id` field is preserved as-is (it is the API/frontend
    contract); the human-readable Firestore document ID is exposed as `doc_id`.
    """
    db = _get_client()
    papers: list[dict[str, Any]] = []
    for doc in db.collection(_PAPERS_COLLECTION).order_by("id").stream():
        data: dict[str, Any] = doc.to_dict() or {}
        data["doc_id"] = doc.id
        papers.append(data)
    return papers


def get_questions_for_paper(paper_id: str) -> list[dict]:
    """
    Fetch all questions under papers/{paper_id}/questions with each question's
    mark scheme points embedded under a `mark_scheme` key.

    Questions are ordered by their numeric `id` field, which mirrors the
    original SQLite ``ORDER BY questions.id`` (i.e. question sequence). Each
    returned dict includes the document ID as `id`.

    `paper_id` is the integer paper ID (the API contract). The paper is resolved
    by that field, not by document ID, since paper document IDs are now
    human-readable strings.
    """
    db = _get_client()
    paper_ref = _find_paper_ref(db, paper_id)
    if paper_ref is None:
        return []
    questions_ref = paper_ref.collection(_QUESTIONS_SUBCOLLECTION)

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


# ---------------------------------------------------------------------------
# Custom Paper Generator — flat `questions` collection
# ---------------------------------------------------------------------------

def clear_custom_questions() -> int:
    """
    Delete every document in the flat `questions` collection, in batches of 500
    (Firestore's batch cap). Returns the number of documents deleted.

    Used when rebuilding the question bank from scratch (e.g. switching from the
    old text-based questions to image-snippet questions). Back up first.
    """
    db = _get_client()
    collection = db.collection(_CUSTOM_QUESTIONS_COLLECTION)
    deleted = 0
    while True:
        docs = list(collection.limit(_BATCH_LIMIT).stream())
        if not docs:
            break
        batch = db.batch()
        for doc in docs:
            batch.delete(doc.reference)
        batch.commit()
        deleted += len(docs)
    return deleted


def batch_write_custom_questions(questions: list[dict]) -> int:
    """
    Write a list of Custom Paper Generator questions to the flat top-level
    `questions` collection using batched writes (Firestore caps each batch at
    500 operations, so the list is committed in chunks of 500).

    When a question dict carries an `id`, that value (stringified) becomes the
    document ID — making re-seeds idempotent (a `set` overwrites in place).
    Otherwise Firestore assigns an auto ID. A `createdAt` server timestamp is
    stamped on every document that does not already supply one.

    Args:
        questions: List of question dicts matching app/types/question.ts.

    Returns:
        The number of question documents written.
    """
    db = _get_client()
    collection = db.collection(_CUSTOM_QUESTIONS_COLLECTION)

    written = 0
    for start in range(0, len(questions), _BATCH_LIMIT):
        chunk = questions[start : start + _BATCH_LIMIT]
        batch = db.batch()
        for question in chunk:
            payload = dict(question)
            payload.setdefault("createdAt", firestore.SERVER_TIMESTAMP)
            doc_id = payload.get("id")
            if doc_id is not None:
                doc_ref = collection.document(str(doc_id))
            else:
                doc_ref = collection.document()
            batch.set(doc_ref, payload)
        batch.commit()
        written += len(chunk)

    return written


def get_distinct_topics(subject: str) -> list[str]:
    """
    Return the sorted, deduplicated list of `topic` values across all documents
    in the flat `questions` collection for the given subject.

    Uses a `where(subject == ...)` filter on a single field, which Firestore
    serves from its automatic single-field index (no composite index needed).

    Args:
        subject: One of "math" | "physics" | "chemistry".

    Returns:
        Sorted list of unique topic strings (empty if none match).
    """
    db = _get_client()
    query = db.collection(_CUSTOM_QUESTIONS_COLLECTION).where(
        filter=firestore.FieldFilter("subject", "==", subject)
    )

    topics: set[str] = set()
    for doc in query.stream():
        topic = (doc.to_dict() or {}).get("topic")
        if topic:
            topics.add(topic)

    return sorted(topics)
