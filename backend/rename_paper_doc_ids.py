"""
rename_paper_doc_ids.py — One-time migration that renames existing `papers`
documents from their old integer IDs (e.g. "1", "6254") to the human-readable
convention {subjectCode}_paper{paperNumber}_{session} (e.g. "0625_paper4_mj2025").

Firestore has no "rename document" operation, so for each paper we copy the
document — together with its questions/ subcollection and each question's
mark_scheme/ subcollection — to the new document ID, then delete the old one.

This is SAFE to re-run: papers already at the new ID are skipped, and a paper is
only deleted after its copy has been written.

The integer `id` field inside each document is left untouched — it remains the
API/frontend contract. Only the document ID changes.

Usage (run from inside the backend/ directory, with Firebase credentials
configured exactly as the running backend has them):

    python rename_paper_doc_ids.py            # perform the migration
    python rename_paper_doc_ids.py --dry-run  # print what would change only
"""

from __future__ import annotations

import os
import sys

from firestore_service import (
    _get_client,
    make_paper_doc_id,
    _PAPERS_COLLECTION,
    _QUESTIONS_SUBCOLLECTION,
    _MARK_SCHEME_SUBCOLLECTION,
)


def _copy_paper(old_paper_ref, new_paper_ref) -> tuple[int, int]:
    """
    Copy a paper document and all of its nested content to new_paper_ref.
    Returns (questions_copied, mark_points_copied).
    """
    new_paper_ref.set(old_paper_ref.get().to_dict() or {})

    q_count = 0
    mp_count = 0
    for q in old_paper_ref.collection(_QUESTIONS_SUBCOLLECTION).stream():
        new_q_ref = new_paper_ref.collection(_QUESTIONS_SUBCOLLECTION).document(q.id)
        new_q_ref.set(q.to_dict() or {})
        q_count += 1
        for mp in q.reference.collection(_MARK_SCHEME_SUBCOLLECTION).stream():
            new_q_ref.collection(_MARK_SCHEME_SUBCOLLECTION).document(mp.id).set(
                mp.to_dict() or {}
            )
            mp_count += 1
    return q_count, mp_count


def _delete_paper(paper_ref) -> None:
    """Recursively delete a paper document and its subcollections."""
    for q in paper_ref.collection(_QUESTIONS_SUBCOLLECTION).stream():
        for mp in q.reference.collection(_MARK_SCHEME_SUBCOLLECTION).stream():
            mp.reference.delete()
        q.reference.delete()
    paper_ref.delete()


def migrate(dry_run: bool = False) -> None:
    db = _get_client()
    papers = list(db.collection(_PAPERS_COLLECTION).stream())
    if not papers:
        print("No papers found. Nothing to migrate.")
        return

    print(f"Found {len(papers)} paper document(s).{' (dry run)' if dry_run else ''}\n")

    renamed = skipped = 0
    for doc in papers:
        data = doc.to_dict() or {}
        new_id = make_paper_doc_id(data)

        if new_id is None:
            print(f"  SKIP {doc.id!r}: missing fields needed to build a new ID.")
            skipped += 1
            continue
        if doc.id == new_id:
            print(f"  SKIP {doc.id!r}: already in the new format.")
            skipped += 1
            continue

        new_ref = db.collection(_PAPERS_COLLECTION).document(new_id)
        if new_ref.get().exists:
            print(
                f"  SKIP {doc.id!r} -> {new_id!r}: target already exists "
                f"(would clobber). Resolve manually."
            )
            skipped += 1
            continue

        if dry_run:
            print(f"  WOULD RENAME {doc.id!r} -> {new_id!r}")
            renamed += 1
            continue

        q_count, mp_count = _copy_paper(doc.reference, new_ref)
        _delete_paper(doc.reference)
        print(
            f"  RENAMED {doc.id!r} -> {new_id!r} "
            f"({q_count} question(s), {mp_count} mark point(s))"
        )
        renamed += 1

    print()
    print("Dry run complete." if dry_run else "Migration complete.")
    print(f"   Renamed : {renamed}")
    print(f"   Skipped : {skipped}")


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    if os.path.abspath(os.getcwd()) != here:
        os.chdir(here)
        print(f"(Changed working directory to {here})")

    migrate(dry_run="--dry-run" in sys.argv)
