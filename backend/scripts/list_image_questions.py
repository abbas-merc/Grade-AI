"""
list_image_questions.py — Step 1: read the live `questions` collection and list
every document with hasImage == true (id, paperCode, originalQuestionNumber).

Run from the backend/ directory (so .env / Firebase creds resolve exactly as the
running backend has them):

    python scripts/list_image_questions.py
"""
from __future__ import annotations

import os
import sys

# Ensure backend/ is importable when run as `python scripts/list_image_questions.py`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from firestore_service import _get_client  # noqa: E402

COLLECTION = "questions"


def main() -> None:
    db = _get_client()
    docs = list(db.collection(COLLECTION).stream())
    rows = []
    has_image = 0
    for doc in docs:
        d = doc.to_dict() or {}
        if d.get("hasImage"):
            has_image += 1
            rows.append(
                (
                    doc.id,
                    d.get("paperCode", ""),
                    d.get("originalQuestionNumber", ""),
                    d.get("topic", ""),
                    bool(d.get("imageUrl")),
                )
            )

    # Sort by paperCode then question number for a readable list.
    rows.sort(key=lambda r: (r[1], int(r[2]) if str(r[2]).isdigit() else 0))

    print(f"Total documents in `{COLLECTION}`: {len(docs)}")
    print(f"hasImage == true:                 {has_image}\n")
    print(f"{'doc id':<28} {'paperCode':<18} {'qNo':>3} {'topic':<14} imageUrl?")
    print("-" * 80)
    for doc_id, code, qno, topic, has_url in rows:
        print(f"{doc_id:<28} {code:<18} {str(qno):>3} {topic:<14} {'YES' if has_url else '-'}")

    # Group counts per paper for the report.
    by_paper: dict[str, int] = {}
    for _, code, *_ in rows:
        by_paper[code] = by_paper.get(code, 0) + 1
    print("\nhasImage per paper:")
    for code in sorted(by_paper):
        print(f"  {code}: {by_paper[code]}")


if __name__ == "__main__":
    main()
