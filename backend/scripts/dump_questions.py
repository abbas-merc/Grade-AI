"""
dump_questions.py — pull every question's questionText from Firestore for the
cleanup pass. Writes a readable dump (newlines shown as ⏎) plus a JSON the
cleaner reuses, and prints a sample of questions that contain obvious
diagram-label artifacts.

Run from backend/:  python scripts/dump_questions.py
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from firestore_service import _get_client  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "diagram_out")
COLLECTION = "questions"

# Heuristic markers that a question carries extraction noise (only for the
# "sample of 10" highlight — not the cleaning logic).
ARTIFACT_HINTS = [
    re.compile(r"NOT\s*TO\s*\n?\s*SCALE", re.I),
    re.compile(r"^\s*[A-Z]\s*$", re.M),                 # lone vertex letter line
    re.compile(r"^\s*\d+(\.\d+)?\s*(cm|m|km|mm|°)\s*$", re.M),  # lone measurement
]


def order_key(doc_id: str):
    m = re.search(r"_(\d{4})_(MJ|ON)_058042_Q(\d+)$", doc_id)
    if not m:
        return (9999, "", 99)
    return (int(m.group(1)), m.group(2), int(m.group(3)))


def main() -> None:
    db = _get_client()
    docs = sorted(db.collection(COLLECTION).stream(), key=lambda d: order_key(d.id))
    rows = []
    for d in docs:
        data = d.to_dict() or {}
        rows.append({
            "id": d.id,
            "paperCode": data.get("paperCode", ""),
            "qNo": data.get("originalQuestionNumber", ""),
            "topic": data.get("topic", ""),
            "hasImage": bool(data.get("hasImage")),
            "questionText": data.get("questionText", "") or "",
        })

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "questions_dump.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)

    # Readable text dump with visible line breaks.
    with open(os.path.join(OUT, "questions_dump.txt"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(f"\n{'='*90}\n{r['id']}  | {r['paperCode']} Q{r['qNo']} | "
                    f"{r['topic']} | hasImage={r['hasImage']}\n{'-'*90}\n")
            for ln in r["questionText"].split("\n"):
                f.write(f"  | {ln}\n")

    n_artifact = sum(1 for r in rows if any(p.search(r["questionText"]) for p in ARTIFACT_HINTS))
    print(f"Total questions: {len(rows)}")
    print(f"With obvious artifact hints: {n_artifact}")
    print(f"Dumps: {os.path.join(OUT,'questions_dump.txt')}  /  questions_dump.json")


if __name__ == "__main__":
    main()
