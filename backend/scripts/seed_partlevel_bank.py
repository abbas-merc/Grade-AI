"""
seed_partlevel_bank.py — Upgrade the Firestore `questions` collection to the
part-level schema (schemaVersion 2) from scripts/part_extraction/part_level_questions.json.

This UPDATES each existing question document in place, adding the part-level
fields (subParts, sharedAssets, syllabusCodes, dependencyGraph, schemaVersion)
while leaving the flat fields the app already uses (questionImageUrl, marks,
topic, calculatorStatus, ...) untouched. After this runs, the new endpoint
POST /api/generate-paper/partlevel returns topic-safe papers.

Idempotent (doc id == question id). GATED: NOT run automatically — seeding is a
production write, consistent with the project's build-review-then-seed pattern.
Run manually only after review:

    python scripts/seed_partlevel_bank.py            # dry run: prints a summary
    python scripts/seed_partlevel_bank.py --commit   # actually write to Firestore
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "part_extraction", "part_level_questions.json")

# Only these part-level fields are added to each existing doc.
_PARTLEVEL_FIELDS = (
    "schemaVersion", "syllabusCodes", "subParts", "sharedAssets",
    "dependencyGraph", "extractionStatus", "marksReconciled", "tagMismatch",
)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    commit = "--commit" in sys.argv
    docs = json.load(open(SRC, encoding="utf-8"))

    tagged = sum(1 for d in docs if d["syllabusCodes"])
    subparts = sum(len(d["subParts"]) for d in docs)
    print(f"source: {len(docs)} part-level questions, {subparts} sub-parts")
    print(f"  with >=1 syllabus code: {tagged}")
    print(f"  extractionStatus: {dict(Counter(d.get('extractionStatus') for d in docs))}")
    print(f"  tagMismatch (old broad tag wrong): {sum(1 for d in docs if d.get('tagMismatch'))}")

    if not commit:
        print("\nDRY RUN — no writes. Re-run with --commit to update Firestore.")
        return

    from firestore_service import _get_client  # noqa: E402
    db = _get_client()
    col = db.collection("questions")
    batch = db.batch()
    n = 0
    for d in docs:
        update = {k: d[k] for k in _PARTLEVEL_FIELDS if k in d}
        batch.set(col.document(d["id"]), update, merge=True)
        n += 1
        if n % 400 == 0:
            batch.commit()
            batch = db.batch()
    batch.commit()
    print(f"\nUpdated {n} documents with part-level fields (merge=True).")


if __name__ == "__main__":
    main()
