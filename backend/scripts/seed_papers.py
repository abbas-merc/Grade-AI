"""
seed_papers.py — Replace the Papers-tab `papers` collection with the 4 new
IGCSE 0580 maths papers that back the image-snippet question bank.

Removes the existing papers (the old Math/Physics/Chemistry set) and writes
exactly these four, each with its nested `questions` subcollection (one document
per question, carrying the question image URL) and a `mark_scheme` per question,
so the existing full-paper marking flow grades real student responses against
them.

Question content is taken from scripts/question_bank_manifest.json (the same
source as the flat generator bank), so the Papers tab and the Custom Paper
Generator stay in lockstep.

Run from backend/:  python scripts/seed_papers.py
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from firestore_service import _get_client, seed_paper_to_firestore  # noqa: E402

MANIFEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "question_bank_manifest.json")

# paperCode -> Papers-tab metadata. integer `id` is the API/frontend contract
# (used by getQuestions / marking); the human-readable Firestore doc id is built
# from subject_code/paper_number/session/year by make_paper_doc_id.
PAPER_META = {
    "0580/21/2024": {
        "id": 1, "paper_number": 2, "session": "May/June", "year": 2024,
        "paperType": "P2", "isSpecimen": False, "variant": 1,
        "name": "IGCSE Math 0580 Paper 2 Variant 1 2024",
    },
    "0580/41/2024": {
        "id": 2, "paper_number": 4, "session": "May/June", "year": 2024,
        "paperType": "P4", "isSpecimen": False, "variant": 1,
        "name": "IGCSE Math 0580 Paper 4 Variant 1 2024",
    },
    "0580/02/SP/2025": {
        "id": 3, "paper_number": 2, "session": "Specimen", "year": 2025,
        "paperType": "P2", "isSpecimen": True, "variant": 0,
        "name": "IGCSE Math 0580 Paper 2 Specimen 2025",
    },
    "0580/04/SP/2025": {
        "id": 4, "paper_number": 4, "session": "Specimen", "year": 2025,
        "paperType": "P4", "isSpecimen": True, "variant": 0,
        "name": "IGCSE Math 0580 Paper 4 Specimen 2025",
    },
}


def _clear_papers(db) -> int:
    """Recursively delete every existing paper document (and its questions /
    mark_scheme subcollections)."""
    deleted = 0
    for doc in db.collection("papers").stream():
        db.recursive_delete(doc.reference)
        deleted += 1
    return deleted


def main() -> None:
    with open(MANIFEST, encoding="utf-8") as f:
        items = json.load(f)

    by_code: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        by_code[it["paperCode"]].append(it)

    db = _get_client()
    cleared = _clear_papers(db)
    print(f"Cleared {cleared} existing paper(s).")

    for code, meta in PAPER_META.items():
        qs = sorted(by_code.get(code, []), key=lambda q: q["originalQuestionNumber"])
        if not qs:
            print(f"  WARNING: no questions for {code}; skipping.")
            continue
        total_marks = sum(q["marks"] for q in qs)

        paper_data = {
            "id": meta["id"],
            "subject_code": "0580",
            "subject_name": "Mathematics",
            "paper_number": meta["paper_number"],
            "session": meta["session"],
            "year": meta["year"],
            "tier": "Extended",
            "total_marks": total_marks,
            "variant": meta["variant"],
            "paperType": meta["paperType"],
            "isSpecimen": meta["isSpecimen"],
            "paper_name": meta["name"],
        }

        questions_data = []
        for q in qs:
            n = q["originalQuestionNumber"]
            questions_data.append({
                "id": n,
                "paper_id": meta["id"],
                "question_number": str(n),
                # The question itself is the image; this text is context for the
                # list/results (grading uses the mark scheme + the question image).
                "question_text": (
                    f"Question {n} — {q['topic']} ({q['marks']} mark"
                    f"{'s' if q['marks'] != 1 else ''})."
                ),
                "marks_available": q["marks"],
                "question_image_url": q["questionImageUrl"],
                "mark_scheme": [{
                    "id": 1,
                    "description": q["markSchemeText"],
                    "marks_for_point": q["marks"],
                    "acceptable_alternatives": "",
                }],
            })

        doc_id = seed_paper_to_firestore(paper_data, questions_data)
        print(f"  Seeded {meta['name']}  (id={meta['id']}, doc={doc_id}, "
              f"{len(questions_data)} Qs, {total_marks} marks)")

    print("Done.")


if __name__ == "__main__":
    main()
