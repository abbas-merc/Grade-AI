"""
_smoke_new_pdfs.py — Exercise the new PDF features end to end and verify with
pdfplumber:

  * Question paper: exam-cover formalities (school name, candidate name/number,
    date, invigilator signature, Instructions to Candidates + calculator note).
  * Mark scheme: improved formatting renders without error.
  * Results: the new "Performance Analysis" first page (per-topic bars + weakest
    summary) plus the existing breakdown.

Run:  venv/Scripts/python.exe scripts/_smoke_new_pdfs.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pdfplumber  # noqa: E402

from utils.pdf_generator import (  # noqa: E402
    generate_question_paper_pdf,
    generate_mark_scheme_pdf,
    generate_results_pdf,
)

OUT = "/tmp"
os.makedirs(OUT, exist_ok=True)


def _text(path: str) -> str:
    with pdfplumber.open(path) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def paper_data() -> dict:
    # Two P2 + one P4 question so the calculator note resolves to "may use".
    return {
        "subject": "math",
        "totalMarks": 15,
        "numQuestions": 3,
        "schoolName": "Springfield High School",
        "questions": [
            {"assignedNumber": 1, "marks": 5, "topic": "algebra",
             "difficulty": "medium", "paperType": "P2",
             "questionImageUrl": "/question_snippets/0580_2_SP_2025_Q1.png"},
            {"assignedNumber": 2, "marks": 4, "topic": "geometry",
             "difficulty": "easy", "paperType": "P2",
             "questionImageUrl": "/question_snippets/0580_2_SP_2025_Q10.png"},
            {"assignedNumber": 3, "marks": 6, "topic": "number",
             "difficulty": "hard", "paperType": "P4",
             "questionImageUrl": "/question_snippets/0580_2_SP_2025_Q11.png"},
        ],
        "markScheme": [
            {"questionNumber": 1, "marks": 5,
             "markSchemeText": "1(a)\n3x + 2\nM1 oe\n(b)(i)\nx = 4\nA1\n(b)(ii)\ny = 7\nA1 ft"},
            {"questionNumber": 2, "marks": 4,
             "markSchemeText": "2(a)\n72\ncao\n(b)\n5.6 cm\nB1"},
            {"questionNumber": 3, "marks": 6,
             "markSchemeText": "3\n1250\nM2 for full method\nA1"},
        ],
    }


def results_data() -> dict:
    return {
        "paper_name": "Mock Paper 2026",
        "graded_at": "2026-07-02T10:00:00+00:00",
        "total_marks_awarded": 9,
        "total_marks_available": 15,
        "results": [
            {"question_number": "1", "topic": "algebra", "marks_awarded": 5,
             "marks_available": 5, "extracted_answer": "x=4", "mark_breakdown": [],
             "feedback": "Fully correct, cleanly set out.", "low_confidence": False},
            {"question_number": "2", "topic": "geometry", "marks_awarded": 1,
             "marks_available": 4, "extracted_answer": "72",
             "mark_breakdown": [
                 {"criterion": "cao", "awarded": True, "reason": "72 correct."},
                 {"criterion": "B1 length", "awarded": False,
                  "reason": "Used the wrong side in Pythagoras."}],
             "feedback": "Right angle fact but wrong side used in Pythagoras in part (b).",
             "low_confidence": True},
            {"question_number": "3", "topic": "number", "marks_awarded": 3,
             "marks_available": 6, "extracted_answer": "1250",
             "mark_breakdown": [], "feedback": "Correct method, arithmetic slip in the final line.",
             "low_confidence": False},
        ],
    }


def main() -> None:
    pd = paper_data()

    # 1) Question paper
    qp = os.path.join(OUT, "smoke_qp.pdf")
    with open(qp, "wb") as fh:
        fh.write(generate_question_paper_pdf(pd))
    t = _text(qp)
    for token in ["Springfield High School", "Candidate Name",
                  "Candidate Number / Roll No", "Date", "Invigilator",
                  "Instructions to Candidates", "Answer all questions",
                  "You may use a calculator"]:
        assert token in t, f"QP missing: {token!r}"
    print("  [OK] question paper — formalities present")

    # All-P2 variant -> non-calculator note
    pd_p2 = dict(pd)
    pd_p2["questions"] = [q for q in pd["questions"] if q["paperType"] == "P2"]
    with open(os.path.join(OUT, "smoke_qp_p2.pdf"), "wb") as fh:
        fh.write(generate_question_paper_pdf(pd_p2))
    t2 = _text(os.path.join(OUT, "smoke_qp_p2.pdf"))
    assert "You must NOT use a calculator" in t2, "P2 paper should be non-calculator"
    print("  [OK] all-P2 paper — non-calculator note")

    # 2) Mark scheme
    ms = os.path.join(OUT, "smoke_ms.pdf")
    with open(ms, "wb") as fh:
        fh.write(generate_mark_scheme_pdf(pd))
    tm = _text(ms)
    for token in ["Mark Scheme", "Springfield High School"]:
        assert token in tm, f"MS missing: {token!r}"
    print("  [OK] mark scheme — rendered")

    # 3) Results with Performance Analysis
    rd = results_data()
    rp = os.path.join(OUT, "smoke_results.pdf")
    with open(rp, "wb") as fh:
        fh.write(generate_results_pdf(rd))
    with pdfplumber.open(rp) as pdf:
        pages = pdf.pages
        first = pages[0].extract_text() or ""
        full = "\n".join(p.extract_text() or "" for p in pages)
    assert "Performance Analysis" in first, "analysis must be the FIRST page"
    assert "Marks by Topic" in first
    for token in ["Algebra", "Geometry", "Number", "Weakest area"]:
        assert token in full, f"Results missing: {token!r}"
    # Weakest is geometry (1/4 = 25%)
    assert "Geometry" in full and "25%" in full, "weakest topic summary wrong"
    assert "Marked Results" in full, "existing breakdown page must remain"
    print(f"  [OK] results — Performance Analysis first page ({len(pages)} pages)")

    # Results with NO topics -> analysis omitted, opens on Marked Results
    rd_no = results_data()
    for q in rd_no["results"]:
        q.pop("topic", None)
    with open(os.path.join(OUT, "smoke_results_notopic.pdf"), "wb") as fh:
        fh.write(generate_results_pdf(rd_no))
    with pdfplumber.open(os.path.join(OUT, "smoke_results_notopic.pdf")) as pdf:
        first_no = pdf.pages[0].extract_text() or ""
    assert "Performance Analysis" not in first_no, "no-topic paper must omit analysis"
    assert "Marked Results" in first_no
    print("  [OK] results — analysis gracefully omitted when no topics")

    print("\nALL SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()
