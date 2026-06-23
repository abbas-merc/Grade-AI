"""
apply_transcriptions.py — Write the approved clean questionText back to
Firestore. Updates ONLY the `questionText` field; never touches markSchemeText,
hasImage, imageUrl, or anything else.

Safety: writes a one-time backup of the current questionText for every affected
doc to diagram_out/questiontext_backup.json before any update, so the change is
reversible.

Run from backend/:  python scripts/apply_transcriptions.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from firestore_service import _get_client  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "diagram_out")
COLLECTION = "questions"


def main() -> None:
    proposed = json.load(open(os.path.join(OUT, "transcribed_proposed.json"), encoding="utf-8"))
    db = _get_client()

    # Backup current questionText first (reversible).
    backup_path = os.path.join(OUT, "questiontext_backup.json")
    backup = {}
    for qid in proposed:
        snap = db.collection(COLLECTION).document(qid).get()
        if snap.exists:
            backup[qid] = (snap.to_dict() or {}).get("questionText", "")
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(backup, f, indent=2, ensure_ascii=False)
    print(f"Backed up {len(backup)} original questionText values -> {backup_path}")

    updated = 0
    for qid, clean in proposed.items():
        db.collection(COLLECTION).document(qid).update({"questionText": clean})
        updated += 1
        print(f"  updated questionText  {qid}")
    print(f"\nDONE: questionText updated for {updated} questions (markScheme untouched).")


if __name__ == "__main__":
    main()
