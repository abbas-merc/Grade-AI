"""
update_questions.py — Fill placeholder question_text for any Question row that
has no real text yet.

A row is treated as needing a placeholder when its question_text is empty,
None, or contains the word "placeholder" (case-insensitive).

The replacement text is:
    Question <question_number> — <marks_available> marks

Usage (run from inside the backend/ directory):
    python update_questions.py
"""

from __future__ import annotations

import os
import sys


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    if os.path.abspath(os.getcwd()) != here:
        os.chdir(here)

    from database import SessionLocal
    from models import Question

    db = SessionLocal()
    try:
        questions = db.query(Question).all()
        updated = 0
        for q in questions:
            text = (q.question_text or "").strip()
            if not text or "placeholder" in text.lower() or "text not available" in text.lower():
                m = "mark" if q.marks_available == 1 else "marks"
                q.question_text = (
                    f"Question {q.question_number} — {q.marks_available} {m}"
                )
                updated += 1
        db.commit()
    finally:
        db.close()

    print(f"{updated} question(s) updated.")


if __name__ == "__main__":
    sys.exit(main())
