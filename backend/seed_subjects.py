"""
seed_subjects.py — Seed Physics (0625) and Chemistry (0620) papers into Firestore.

Unlike seed.py (which seeds the Maths paper into SQLite), this script writes
directly to Firestore using firestore_service.seed_paper_to_firestore. It drives
each paper entirely from its official Cambridge mark-scheme PDF — there is no
solved paper, so question wording is a placeholder and the mark points come
from the mark scheme.

Usage (run from inside the backend/ directory, with Firebase credentials
configured exactly as the running backend has them):

    python seed_subjects.py

PDFs are expected under backend/papers/. Any paper whose PDF is not present yet
is skipped with a clear message, so this script is safe to run before all the
mark-scheme PDFs have been added.

Integer IDs:
    The API response schemas (PaperResponse, QuestionResponse, MarkPointResponse)
    declare integer IDs, and the routers/pipeline cast every Firestore document
    ID back to int(). So we assign deterministic integer IDs here rather than
    letting Firestore auto-generate string IDs:
        paper_id     = int(subject_code) * 10 + paper_number   (e.g. 6254)
        question_id  = paper_id * 1000 + sequence              (globally unique)
        mark_point_id= 1-based index within the question
    These never collide with the Maths paper (id=1) migrated from SQLite.
"""

from __future__ import annotations

import os

from firestore_service import seed_paper_to_firestore
from pdf_parser import (
    extract_text_from_pdf,
    parse_markscheme,
    print_parsing_preview,
)


def _build_questions_data(
    paper_id: int,
    subject_code: str,
    subject_name: str,
    paper_number: int,
    markscheme: list[dict],
) -> list[dict]:
    """
    Convert parsed mark-scheme entries into the questions_data shape that
    seed_paper_to_firestore expects, assigning deterministic integer IDs.

    Marks-per-question priority (mirrors seed.py):
        1. the parser's total_marks for the entry
        2. the count of parsed mark points (each Cambridge point is 1 mark)
        3. fallback of 1
    """
    questions_data: list[dict] = []

    for index, entry in enumerate(markscheme):
        qnum = entry["question_number"]
        mark_points: list[str] = entry.get("mark_points", []) or []
        alternatives: str = entry.get("acceptable_alternatives", "") or ""
        total_marks: int = entry.get("total_marks", 0) or 0

        mp_count = len(mark_points)
        if total_marks:
            marks = total_marks
        elif mp_count > 0:
            marks = mp_count
        else:
            marks = 1

        question_id = paper_id * 1000 + (index + 1)

        if mark_points:
            mark_scheme = [
                {
                    "id": point_index + 1,
                    "description": point_text,
                    "marks_for_point": 1,
                    "acceptable_alternatives": alternatives,
                }
                for point_index, point_text in enumerate(mark_points)
            ]
        else:
            # Entry exists but has no parsed points — insert one catch-all row so
            # grading always has a criterion to work with.
            mark_scheme = [
                {
                    "id": 1,
                    "description": alternatives
                    or f"Award {marks} mark(s) for correct answer",
                    "marks_for_point": marks,
                    "acceptable_alternatives": alternatives,
                }
            ]

        questions_data.append({
            "id": question_id,
            "paper_id": paper_id,
            "question_number": qnum,
            "question_text": (
                f"{subject_name} {subject_code} Paper {paper_number} "
                f"Question {qnum} (mark scheme only)"
            ),
            "marks_available": marks,
            "mark_scheme": mark_scheme,
        })

    return questions_data


def seed_paper(
    subject_code: str,
    year: int,
    session: str,
    paper_number: int,
    variant: int,
    tier: str,
    total_marks: int,
    markscheme_path: str,
    subject_name: str,
) -> None:
    """
    Seed one Physics/Chemistry paper into Firestore from its mark-scheme PDF.

    Skips gracefully (with a printed message) if the PDF is not present or the
    mark scheme cannot be parsed.
    """
    label = f"{subject_name} {subject_code} Paper {paper_number} ({session} {year})"
    print(f"\n--- {label} ---")

    if not os.path.isfile(markscheme_path):
        print(f"  SKIP: mark scheme PDF not found at {os.path.abspath(markscheme_path)}")
        print("        (paper not yet available — add the PDF and rerun)")
        return

    print(f"  Extracting text from {markscheme_path}...")
    try:
        text = extract_text_from_pdf(markscheme_path)
    except Exception as exc:
        print(f"  SKIP: could not read PDF — {exc}")
        print("        (the file may be empty or corrupt — replace it and rerun)")
        return

    print(f"  Parsing mark scheme (subject_code={subject_code})...")
    markscheme = parse_markscheme(text, subject_code)

    # Diagnostic summary (no solved paper, so question list is empty here).
    print_parsing_preview([], markscheme)

    if not markscheme:
        print(
            "  SKIP: 0 mark scheme entries parsed. "
            "Check that the PDF is text-based (not image-only)."
        )
        return

    paper_id = int(subject_code) * 10 + paper_number
    paper_data = {
        "id": paper_id,
        "subject_code": subject_code,
        "year": year,
        "session": session,
        "paper_number": paper_number,
        "variant": variant,
        "tier": tier,
        "total_marks": total_marks,
        "subject_name": subject_name,
    }

    questions_data = _build_questions_data(
        paper_id, subject_code, subject_name, paper_number, markscheme
    )

    doc_id = seed_paper_to_firestore(paper_data, questions_data)

    print(
        f"  Seeded {label} -> papers/{doc_id} "
        f"with {len(questions_data)} question(s)."
    )

    # --- Validation summary: verify the parsed marks add up to the paper total ---
    total_questions = len(questions_data)
    total_mark_points = sum(len(q["mark_scheme"]) for q in questions_data)
    marks_sum = sum(q["marks_available"] for q in questions_data)
    print("  Validation summary:")
    print(f"    Questions seeded   : {total_questions}")
    print(f"    Mark points seeded : {total_mark_points}")
    print(f"    Sum of all marks   : {marks_sum} (expected paper total: {total_marks})")
    if marks_sum != total_marks:
        print(
            f"    NOTE: sum of marks ({marks_sum}) does not match the expected "
            f"paper total ({total_marks}) — review the parsed mark scheme."
        )


if __name__ == "__main__":
    # Ensure we run from the backend/ directory so relative PDF paths and
    # Firebase credential paths resolve the same way they do for the server.
    here = os.path.dirname(os.path.abspath(__file__))
    if os.path.abspath(os.getcwd()) != here:
        os.chdir(here)
        print(f"(Changed working directory to {here})")

    # Physics 0625 Paper 4 (theory)
    seed_paper(
        subject_code="0625",
        year=2025,
        session="May/June",
        paper_number=4,
        variant=2,
        tier="Extended",
        total_marks=80,
        markscheme_path="papers/Physics_P4_MS.pdf",
        subject_name="Physics",
    )

    # Physics 0625 Paper 6 (Alternative to Practical)
    seed_paper(
        subject_code="0625",
        year=2024,
        session="Oct/Nov",
        paper_number=6,
        variant=3,
        tier="Extended",
        total_marks=40,
        markscheme_path="papers/Physics_P6_MS.pdf",
        subject_name="Physics",
    )

    # Chemistry 0620 Paper 4 (theory)
    seed_paper(
        subject_code="0620",
        year=2025,
        session="Oct/Nov",
        paper_number=4,
        variant=2,
        tier="Extended",
        total_marks=80,
        markscheme_path="papers/Chemistry_P4_MS.pdf",
        subject_name="Chemistry",
    )

    # Chemistry 0620 Paper 6 (Alternative to Practical)
    seed_paper(
        subject_code="0620",
        year=2024,
        session="May/June",
        paper_number=6,
        variant=3,
        tier="Extended",
        total_marks=40,
        markscheme_path="papers/Chemistry_P6_MS.pdf",
        subject_name="Chemistry",
    )

    print("\nDone.")
