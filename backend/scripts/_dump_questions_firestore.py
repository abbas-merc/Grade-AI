"""
_dump_questions_firestore.py — Safety backup of the live `questions` collection
to JSON before it is cleared and rebuilt with image-snippet questions.

Run from backend/:  python scripts/_dump_questions_firestore.py
Writes:  scripts/questiontext_backup_v1_firestore.json
"""
from __future__ import annotations

import json
import os
import sys

# Allow importing the backend modules when run from scripts/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from firestore_service import _get_client  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "questiontext_backup_v1_firestore.json")


def main() -> None:
    db = _get_client()
    docs = []
    for d in db.collection("questions").stream():
        data = d.to_dict() or {}
        # createdAt is a Firestore timestamp — stringify so json can serialize it.
        if "createdAt" in data:
            data["createdAt"] = str(data["createdAt"])
        data["_doc_id"] = d.id
        docs.append(data)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(docs, f, indent=2, ensure_ascii=False)
    print(f"Backed up {len(docs)} question docs -> {os.path.relpath(OUT)}")


if __name__ == "__main__":
    main()
