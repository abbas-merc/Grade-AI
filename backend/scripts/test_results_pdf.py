"""
scripts/test_results_pdf.py — Exercise generate_results_pdf and the
/api/results/download-pdf endpoint, and write a reviewable sample to
/tmp/sample_results.pdf.

Run from the backend dir:
    venv/Scripts/python.exe scripts/test_results_pdf.py

What it covers:
  1. Renders a synthetic result that hits every edge case (full / partial /
     zero-with-no-answer questions, an empty mark_breakdown "single block",
     very long wrapping feedback, and marks_total_mismatch=True).
  2. If Firebase credentials are configured, pulls a real completed marking
     from Firestore and renders that too (this becomes the saved sample).
  3. Verifies each PDF with pdfplumber: header, summary total + percentage,
     every question number, feedback text, the mismatch note, and the footer.
  4. Drives the FastAPI endpoint with a TestClient (AUTH_REQUIRED=false) over
     the inline-result path and asserts a valid PDF download with a sanitized
     Content-Disposition filename.
"""

from __future__ import annotations

import os
import sys

# Run with AUTH disabled so get_current_uid returns a placeholder and the
# endpoint's inline-result path needs no Firebase token.
os.environ.setdefault("AUTH_REQUIRED", "false")

# Make `backend/` importable when run as `scripts/...`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pdfplumber  # noqa: E402

from utils.pdf_generator import generate_results_pdf, format_marked_date  # noqa: E402

OUT_DIR = "/tmp"
SAMPLE_PATH = os.path.join(OUT_DIR, "sample_results.pdf")
EDGE_PATH = os.path.join(OUT_DIR, "sample_results_edgecases.pdf")


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def synthetic_result() -> dict:
    """A result that deliberately includes every awkward shape."""
    long_feedback = (
        "You set this up really well and your method for finding the gradient "
        "was spot on. The only thing that let you down was the final "
        "rearrangement — double-check that you move every term to the correct "
        "side before dividing, and remember to keep the units consistent all "
        "the way through. With a bit more care on the last line this would be "
        "full marks. Keep going, you're very close!"
    )
    return {
        "paper_name": "Custom Math Paper",
        "graded_at": "2026-06-20T10:15:00+00:00",
        "total_marks_awarded": 18,
        "total_marks_available": 25,
        "marks_total_mismatch": True,
        "results": [
            {
                "question_number": "1",
                "marks_awarded": 5,
                "marks_available": 5,
                "extracted_answer": "x = 7, fully worked",
                "mark_breakdown": [
                    {"criterion": "M1 correct method", "awarded": True,
                     "reason": "Set up the equation correctly."},
                    {"criterion": "A1 correct value", "awarded": True,
                     "reason": "x = 7 stated clearly."},
                ],
                "feedback": "Excellent — clear method and a correct final answer.",
            },
            {
                "question_number": "2a",
                "marks_awarded": 4,
                "marks_available": 9,
                "extracted_answer": "gradient = 3, y = 3x + ...",
                "mark_breakdown": [
                    {"criterion": "B1 gradient", "awarded": True,
                     "reason": "Gradient of 3 found correctly."},
                    {"criterion": "M1 substitution", "awarded": True,
                     "reason": "Substituted a point to find c."},
                    {"criterion": "A1 final equation", "awarded": False,
                     "reason": "Rearrangement error in the last line."},
                    {"criterion": "A1 units", "awarded": False,
                     "reason": "Units omitted from the final answer."},
                ],
                "feedback": long_feedback,
            },
            {
                # Single-block question: no mark_breakdown at all.
                "question_number": "2b",
                "marks_awarded": 9,
                "marks_available": 9,
                "extracted_answer": "Full correct working shown.",
                "mark_breakdown": [],
                "feedback": "Perfect — every step is justified.",
            },
            {
                # No-answer / zero-mark question.
                "question_number": "3",
                "marks_awarded": 0,
                "marks_available": 2,
                "extracted_answer": "",
                "mark_breakdown": [],
                "feedback": "",
            },
        ],
    }


def fetch_real_marking() -> dict | None:
    """Return one real completed marking from Firestore, or None if Firebase is
    not reachable / nothing is complete yet."""
    try:
        from firestore_service import _get_client
        db = _get_client()
        for snap in db.collection_group("markings").stream():
            data = snap.to_dict() or {}
            if data.get("status") == "complete" and data.get("results"):
                data["marking_id"] = snap.id
                print(f"  - using real marking: {snap.reference.path} "
                      f"({data.get('paper_name')}, "
                      f"{data.get('total_marks_awarded')}/{data.get('total_marks_available')})")
                return data
    except Exception as exc:  # noqa: BLE001
        print(f"  - Firestore unavailable, skipping real-data render: {exc}")
    return None


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #
def verify_pdf(path: str, data: dict, *, expect_mismatch: bool) -> None:
    with pdfplumber.open(path) as pdf:
        pages = pdf.pages
        text = "\n".join(p.extract_text() or "" for p in pages)

    def need(token: str, label: str) -> None:
        assert token in text, f"[{os.path.basename(path)}] missing {label}: {token!r}"

    need("Grade AI", "brand wordmark")
    need("Marked Results", "title")
    need(str(data.get("paper_name")), "paper name")
    need("TOTAL SCORE", "summary label")

    awarded = int(data.get("total_marks_awarded") or 0)
    available = int(data.get("total_marks_available") or 0)
    pct = round((awarded / available) * 100) if available > 0 else 0
    need(f"{awarded} / {available}", "total score")
    need(f"{pct}%", "percentage")
    need("Question Breakdown", "section header")
    need("Generated by Grade AI", "footer")
    need(format_marked_date(data), "marked date")

    for q in data.get("results", []):
        qn = str(q.get("question_number"))
        need(f"Question {qn}", f"question {qn} header")
        fb = str(q.get("feedback") or "").strip()
        if fb:
            # Check a distinctive opening slice survives wrapping.
            need(fb[:24], f"feedback for Q{qn}")

    # No-answer question renders an explicit note, never a blank.
    if any(int(q.get("marks_awarded") or 0) == 0
           and not str(q.get("extracted_answer") or "").strip()
           and not (q.get("mark_breakdown") or [])
           for q in data.get("results", [])):
        need("No answer was found", "no-answer note")

    if expect_mismatch:
        need("total marks may not reflect final allocation", "mismatch note")

    print(f"  [OK] verified {os.path.basename(path)} "
          f"({len(pages)} page{'s' if len(pages) != 1 else ''}, {len(text)} chars)")


def test_endpoint_inline(data: dict) -> None:
    """Drive POST /api/results/download-pdf over the inline-result path."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers import results as results_router

    app = FastAPI()
    app.include_router(results_router.router, prefix="/api")
    client = TestClient(app)

    # Happy path: inline result.
    resp = client.post("/api/results/download-pdf", json={
        "result": data,
        "paper_name": data.get("paper_name"),
        "graded_at": data.get("graded_at"),
    })
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text[:300]}"
    assert resp.headers["content-type"] == "application/pdf", resp.headers.get("content-type")
    cd = resp.headers.get("content-disposition", "")
    assert "attachment" in cd and cd.endswith('.pdf"'), cd
    assert " " not in cd.split("filename=")[1], f"filename not sanitized: {cd}"
    assert resp.content[:4] == b"%PDF", "endpoint did not return PDF bytes"
    print(f"  [OK] endpoint 200, Content-Disposition: {cd}")

    # Validation: neither result_id nor result -> 422.
    resp2 = client.post("/api/results/download-pdf", json={})
    assert resp2.status_code == 422, f"expected 422 for empty body, got {resp2.status_code}"
    print(f"  [OK] endpoint rejects empty body ({resp2.status_code})")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)

    print("1) Synthetic edge-case render")
    syn = synthetic_result()
    with open(EDGE_PATH, "wb") as fh:
        fh.write(generate_results_pdf(syn))
    verify_pdf(EDGE_PATH, syn, expect_mismatch=True)
    print(f"     saved {os.path.abspath(EDGE_PATH)}")

    print("2) Real Firestore marking (if available)")
    real = fetch_real_marking()
    sample_data = real or syn
    with open(SAMPLE_PATH, "wb") as fh:
        fh.write(generate_results_pdf(sample_data))
    verify_pdf(SAMPLE_PATH, sample_data,
               expect_mismatch=bool(sample_data.get("marks_total_mismatch")))
    print(f"     saved {os.path.abspath(SAMPLE_PATH)}")

    print("3) Endpoint (inline-result path, AUTH_REQUIRED=false)")
    test_endpoint_inline(syn)

    print("\nALL CHECKS PASSED")
    print(f"Sample PDF for review: {os.path.abspath(SAMPLE_PATH)}")


if __name__ == "__main__":
    main()
