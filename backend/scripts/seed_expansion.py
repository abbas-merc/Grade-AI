"""
seed_expansion.py — Seed the 457 new classified questions and backfill the two
new calculator fields onto the existing 81, in the flat `questions` collection.

This does NOT clear the collection (unlike seed_question_bank.py). It:
  1. Writes the 457 new docs (new IDs) via a batched `set` — idempotent re-runs
     overwrite in place.
  2. Merge-updates the existing 81 docs with calculatorStatus + classificationReason
     only (content, image, marks, mark scheme untouched).

Run from backend/:  python scripts/seed_expansion.py [--dry-run]
"""
from __future__ import annotations

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from firestore_service import _get_client, batch_write_custom_questions  # noqa: E402
from finalize_bank import build_new_records, build_backfill_records  # noqa: E402

_COLLECTION = "questions"
_BATCH_LIMIT = 500


def backfill_calculator_fields(records: list[dict]) -> int:
    """Merge calculatorStatus + classificationReason onto existing docs by ID."""
    db = _get_client()
    coll = db.collection(_COLLECTION)
    n = 0
    for start in range(0, len(records), _BATCH_LIMIT):
        chunk = records[start : start + _BATCH_LIMIT]
        batch = db.batch()
        for r in chunk:
            batch.set(
                coll.document(r["id"]),
                {"calculatorStatus": r["calculatorStatus"],
                 "classificationReason": r["classificationReason"]},
                merge=True,  # preserve every existing field
            )
        batch.commit()
        n += len(chunk)
    return n


def main() -> None:
    dry = "--dry-run" in sys.argv
    new = build_new_records()
    backfill = build_backfill_records()

    print(f"NEW: {len(new)}  |  BACKFILL: {len(backfill)}")
    print("  new calculatorStatus:", dict(Counter(r["calculatorStatus"] for r in new)))
    print("  backfill calculatorStatus:", dict(Counter(r["calculatorStatus"] for r in backfill)))

    if dry:
        print("DRY RUN — nothing written.")
        return

    written = batch_write_custom_questions(new)
    print(f"Wrote {written} new question docs.")

    updated = backfill_calculator_fields(backfill)
    print(f"Backfilled calculator fields on {updated} existing docs.")

    # Verify total + non-calc pool in Firestore.
    db = _get_client()
    total = 0
    nc = 0
    missing = 0
    for doc in db.collection(_COLLECTION).stream():
        d = doc.to_dict() or {}
        total += 1
        cs = d.get("calculatorStatus")
        if cs == "non_calc_safe":
            nc += 1
        elif cs != "calc_required":
            missing += 1
    print(f"VERIFY Firestore: total={total}  non_calc_safe={nc}  missing_status={missing}")


if __name__ == "__main__":
    main()
