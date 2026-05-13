"""
seed.py — Populate the GradeAI database from real Cambridge IGCSE PDF files.

Reads two PDFs from backend/papers/:
  Solved_Paper.pdf   — fully worked solutions for 0580 Paper 2 May/June 2025 V2
  Mark_scheme.pdf    — official Cambridge mark scheme for the same paper

Inserts:
  1 Paper record
  N Question records (one per question or sub-part)
  M MarkScheme records (one per individual marking point)

Usage (run from inside the backend/ directory):
  python seed.py
"""

from __future__ import annotations

import os
import sys

from database import Base, SessionLocal, engine
from models import MarkScheme, Paper, Question
from pdf_parser import (
    extract_text_from_pdf,
    parse_markscheme,
    parse_questions_from_solved_paper,
    print_parsing_preview,
)

SOLVED_PATH = "papers/Solved_Paper.pdf"
MARKSCHEME_PATH = "papers/Mark_scheme.pdf"


def seed() -> None:
    """Create tables, parse PDFs, and populate the database."""

    # --- Create all tables (idempotent) ---
    import models  # noqa: F401 — registers models on Base before create_all
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # --- Idempotency check ---
        if db.query(Paper).first():
            print("Database already seeded. Delete gradeai.db and rerun to reseed.")
            return

        # --- Verify PDF files exist ---
        for path in (SOLVED_PATH, MARKSCHEME_PATH):
            if not os.path.isfile(path):
                print(f"ERROR: PDF not found at expected path: {os.path.abspath(path)}")
                print("Make sure you are running this script from inside backend/")
                sys.exit(1)

        # --- Extract text ---
        print("Extracting text from Solved_Paper.pdf...")
        solved_text = extract_text_from_pdf(SOLVED_PATH)

        print("Extracting text from Mark_scheme.pdf...")
        ms_text = extract_text_from_pdf(MARKSCHEME_PATH)

        # --- Parse ---
        print("Parsing questions from solved paper...")
        questions = parse_questions_from_solved_paper(solved_text)

        print("Parsing mark scheme...")
        markscheme = parse_markscheme(ms_text)

        # Show diagnostic summary before inserting anything.
        print_parsing_preview(questions, markscheme)

        if not markscheme:
            print(
                "ERROR: 0 mark scheme entries parsed. "
                "Check that Mark_scheme.pdf is a text-based PDF (not image-only)."
            )
            sys.exit(1)

        # --- Build mark scheme lookup ---
        ms_lookup: dict[str, dict] = {
            item["question_number"]: item for item in markscheme
        }

        # --- Determine question list ---
        # When the solved paper has extractable text, use its questions (they
        # carry full question wording and marks). Otherwise fall back to the
        # mark scheme entries (questions will have placeholder text).
        if questions:
            question_list = questions
        else:
            print(
                "NOTE: Solved_Paper.pdf has no extractable text (image-only PDF).\n"
                "      Falling back to mark scheme entries for the question list.\n"
                "      Question text will be placeholder until a text-based PDF is provided."
            )
            question_list = [
                {
                    "question_number": e["question_number"],
                    "question_text": (
                        f"Question {e['question_number']} "
                        "(text not available — solved paper is image-only)"
                    ),
                    "marks_available": e["total_marks"] or 1,
                    "solved_working": "",
                }
                for e in markscheme
            ]

        # --- Insert Paper ---
        paper = Paper(
            subject_code="0580",
            year=2025,
            session="May/June",
            paper_number=2,
            tier="Extended",
            total_marks=100,
        )
        db.add(paper)
        db.flush()  # get paper.id without committing

        # --- Insert Questions + MarkScheme rows ---
        questions_inserted = 0
        mark_points_inserted = 0
        questions_without_ms = 0

        for qrec in question_list:
            qnum = qrec["question_number"]
            ms_entry = ms_lookup.get(qnum)

            # Determine marks. Priority order:
            #   1. ms_entry.total_marks from parser (capped at 20 by pdf_parser)
            #   2. count of parsed mark points (each Cambridge point is 1 mark)
            #   3. qrec.marks_available from solved-paper bracket notation
            #   4. fallback of 1
            mp_count = len(ms_entry.get("mark_points", [])) if ms_entry else 0
            if ms_entry and ms_entry.get("total_marks"):
                marks = ms_entry["total_marks"]
            elif mp_count > 0:
                marks = mp_count
            elif qrec.get("marks_available"):
                marks = qrec["marks_available"]
            else:
                marks = 1

            question = Question(
                paper_id=paper.id,
                question_number=qnum,
                question_text=qrec["question_text"],
                marks_available=marks,
            )
            db.add(question)
            db.flush()  # get question.id
            questions_inserted += 1

            if ms_entry:
                mark_points: list[str] = ms_entry.get("mark_points", [])
                alternatives: str = ms_entry.get("acceptable_alternatives", "") or ""

                if mark_points:
                    for point_text in mark_points:
                        db.add(MarkScheme(
                            question_id=question.id,
                            description=point_text,
                            marks_for_point=1,
                            acceptable_alternatives=alternatives,
                        ))
                        mark_points_inserted += 1
                else:
                    # Mark scheme entry exists but has no parsed points —
                    # insert one catch-all row so grading has something to work with.
                    db.add(MarkScheme(
                        question_id=question.id,
                        description=alternatives or f"Award {marks} mark(s) for correct answer",
                        marks_for_point=marks,
                        acceptable_alternatives=alternatives,
                    ))
                    mark_points_inserted += 1
            else:
                print(f"WARNING: No mark scheme found for question {qnum}")
                questions_without_ms += 1

        db.commit()

        # --- Final summary ---
        print()
        print("Seeding complete.")
        print(f"   Paper: IGCSE Mathematics 0580 Extended Paper 2 May/June 2025")
        print(f"   Questions inserted         : {questions_inserted}")
        print(f"   Mark scheme points inserted: {mark_points_inserted}")
        print(f"   Questions with no MS match : {questions_without_ms}")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    # Ensure we run from the backend/ directory so relative PDF paths resolve.
    here = os.path.dirname(os.path.abspath(__file__))
    if os.path.abspath(os.getcwd()) != here:
        os.chdir(here)
        print(f"(Changed working directory to {here})")

    seed()
