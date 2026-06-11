"""
migrate_to_firestore.py — One-time migration of static paper content from
SQLite into Cloud Firestore.

Reads every Paper, Question, and MarkScheme row from the existing SQLite
database (gradeai.db) and writes them to Firestore via
firestore_service.seed_paper_to_firestore, preserving the integer IDs as the
Firestore document IDs.

This does NOT touch the SQLite database — it is read-only against SQLite and
write-only against Firestore. SQLite remains intact as a fallback until the
migration is verified.

Usage (run from inside the backend/ directory, with Firebase credentials
configured exactly as the running backend has them):

    python migrate_to_firestore.py
"""

from __future__ import annotations

import os

from database import SessionLocal
from models import MarkScheme, Paper, Question
from firestore_service import seed_paper_to_firestore


def _paper_to_dict(paper: Paper) -> dict:
    return {
        "id": paper.id,
        "subject_code": paper.subject_code,
        "year": paper.year,
        "session": paper.session,
        "paper_number": paper.paper_number,
        "tier": paper.tier,
        "total_marks": paper.total_marks,
    }


def _question_to_dict(question: Question, mark_points: list[MarkScheme]) -> dict:
    return {
        "id": question.id,
        "paper_id": question.paper_id,
        "question_number": question.question_number,
        "question_text": question.question_text,
        "marks_available": question.marks_available,
        "mark_scheme": [
            {
                "id": ms.id,
                "description": ms.description,
                "marks_for_point": ms.marks_for_point,
                "acceptable_alternatives": ms.acceptable_alternatives or "",
            }
            for ms in mark_points
        ],
    }


def migrate() -> None:
    db = SessionLocal()
    try:
        papers = db.query(Paper).order_by(Paper.id).all()
        if not papers:
            print("No papers found in SQLite. Nothing to migrate.")
            return

        print(f"Found {len(papers)} paper(s) in SQLite. Starting migration...\n")

        total_questions = 0
        total_mark_points = 0

        for paper in papers:
            paper_data = _paper_to_dict(paper)

            questions = (
                db.query(Question)
                .filter(Question.paper_id == paper.id)
                .order_by(Question.id)
                .all()
            )

            questions_data: list[dict] = []
            paper_mark_points = 0
            for question in questions:
                mark_points = (
                    db.query(MarkScheme)
                    .filter(MarkScheme.question_id == question.id)
                    .order_by(MarkScheme.id)
                    .all()
                )
                questions_data.append(_question_to_dict(question, mark_points))
                paper_mark_points += len(mark_points)

            print(
                f"  Migrating paper {paper.id}: "
                f"{paper.subject_code} Paper {paper.paper_number} "
                f"({paper.session} {paper.year}) — "
                f"{len(questions_data)} question(s), {paper_mark_points} mark point(s)..."
            )

            doc_id = seed_paper_to_firestore(paper_data, questions_data)

            print(f"    -> wrote papers/{doc_id}")

            total_questions += len(questions_data)
            total_mark_points += paper_mark_points

        print()
        print("Migration complete.")
        print(f"   Papers migrated      : {len(papers)}")
        print(f"   Questions migrated   : {total_questions}")
        print(f"   Mark points migrated : {total_mark_points}")

    finally:
        db.close()


if __name__ == "__main__":
    # Ensure we run from the backend/ directory so the relative SQLite path and
    # Firebase credential paths resolve the same way they do for the server.
    here = os.path.dirname(os.path.abspath(__file__))
    if os.path.abspath(os.getcwd()) != here:
        os.chdir(here)
        print(f"(Changed working directory to {here})")

    migrate()
