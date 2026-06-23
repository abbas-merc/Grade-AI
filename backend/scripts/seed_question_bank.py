"""
seed_question_bank.py — Clear the flat `questions` collection and re-seed it
from the image-snippet manifest produced by build_question_bank.py.

This replaces the old text-based bank (seed_custom_questions.py, now backed up
to scripts/questiontext_backup_v1.py) with image-snippet questions: every
document stores a `questionImageUrl` (served from backend static) instead of
`questionText`, plus `paperType` / `isSpecimen`, and keeps `markSchemeText` as
text for AI marking.

Safe to re-run (idempotent: doc IDs come from each question's `id`). It clears
first so questions removed from the manifest don't linger.

Run from backend/:  python scripts/seed_question_bank.py
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from firestore_service import (  # noqa: E402
    batch_write_custom_questions,
    clear_custom_questions,
)

MANIFEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "question_bank_manifest.json")

# The Firestore document schema (everything else in the manifest is review-only).
_DOC_FIELDS = (
    "id", "subject", "paperType", "paperCode", "year", "isSpecimen",
    "originalQuestionNumber", "marks", "topic", "difficulty",
    "questionImageUrl", "markSchemeText",
)


def build_docs() -> list[dict]:
    with open(MANIFEST, encoding="utf-8") as f:
        items = json.load(f)
    docs = []
    for it in items:
        doc = {k: it[k] for k in _DOC_FIELDS if k in it}
        # Integrity guards — fail loudly rather than seed bad data.
        assert doc["questionImageUrl"], f"{doc['id']} missing questionImageUrl"
        assert doc["markSchemeText"].strip(), f"{doc['id']} missing markSchemeText"
        assert doc["marks"] > 0, f"{doc['id']} has 0 marks"
        docs.append(doc)
    return docs


def main() -> None:
    docs = build_docs()
    print(f"Manifest: {len(docs)} questions")
    print(f"  paperType: {dict(Counter(d['paperType'] for d in docs))}")
    print(f"  difficulty: {dict(Counter(d['difficulty'] for d in docs))}")
    print(f"  topics: {dict(Counter(d['topic'] for d in docs))}")

    deleted = clear_custom_questions()
    print(f"Cleared {deleted} existing documents from `questions`.")

    written = batch_write_custom_questions(docs)
    print(f"Uploaded {written} image-snippet questions to `questions`.")


if __name__ == "__main__":
    main()
