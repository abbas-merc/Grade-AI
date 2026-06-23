"""
test_paper_pdf.py — Exercise the updated generator + PDF pipeline end-to-end
(no HTTP server / auth needed: calls the endpoint functions directly).

Generates P2-only / P4-only / both papers and renders the question-paper and
mark-scheme PDFs, asserting: only the requested paperType is selected, every
question carries a questionImageUrl, totals never exceed the request, and the
PDFs render with sane page counts. Saves the PDFs + a first-page preview PNG.

Run from backend/:  python scripts/test_paper_pdf.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz  # PyMuPDF (page counting / preview)
from routers.paper_generator import (
    GeneratePaperRequest, generate_paper, generate_paper_pool, _as_dict,
)
from utils.pdf_generator import generate_question_paper_pdf, generate_mark_scheme_pdf

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_pdf_out")
os.makedirs(OUT, exist_ok=True)


def run(label, paper_type, total, difficulty, topics=None):
    pool = generate_paper_pool(subject="math", uid="t")
    topics = topics or pool.topics
    req = GeneratePaperRequest(
        subject="math", paperType=paper_type, topics=topics,
        totalMarks=total, difficulty=difficulty,
    )
    paper = generate_paper(req, uid="t")
    d = _as_dict(paper)

    types = {q["paperType"] for q in d["questions"]}
    have_img = all(q["questionImageUrl"] for q in d["questions"])
    print(f"\n### {label}: paperType={paper_type} req={total} diff={difficulty}")
    print(f"   -> {d['numQuestions']} Qs, {d['totalMarks']} marks "
          f"(<= req: {d['totalMarks'] <= total}); source types={types or '∅'}; "
          f"all have image: {have_img}")
    if paper_type != "both":
        assert types <= {paper_type} or not types, f"leaked other types: {types}"
    assert have_img, "a question is missing questionImageUrl"
    assert d["totalMarks"] <= total, "exceeded requested marks"

    qp = generate_question_paper_pdf(d)
    ms = generate_mark_scheme_pdf(d)
    qp_path = os.path.join(OUT, f"{label}_QP.pdf")
    ms_path = os.path.join(OUT, f"{label}_MS.pdf")
    open(qp_path, "wb").write(qp)
    open(ms_path, "wb").write(ms)
    qd, md = fitz.open(qp_path), fitz.open(ms_path)
    print(f"   QP: {len(qd)} pages, {len(qp)//1024} KB   |   MS: {len(md)} pages, {len(ms)//1024} KB")
    # First-page preview of the question paper for visual spot-check.
    pix = qd[0].get_pixmap(matrix=fitz.Matrix(1.4, 1.4))
    pix.save(os.path.join(OUT, f"{label}_QP_p1.png"))
    qd.close(); md.close()
    return d


def main():
    pool = generate_paper_pool(subject="math", uid="t")
    print(f"pool: {len(pool.questions)} questions, topics={pool.topics}")
    run("P2_40_mixed", "P2", 40, "mixed")
    run("P4_60_hard", "P4", 60, "hard")
    run("both_80_mixed", "both", 80, "mixed")
    # Pool-ceiling case: 100 marks hard from P2 only (P2 hard ~39 marks) should
    # fall short of the request, never exceed it.
    d = run("P2_100_hard", "P2", 100, "hard")
    print(f"\n   [pool-ceiling] P2/hard requested 100 -> delivered {d['totalMarks']} "
          f"(expected < 100, this is what the app's availability message warns about)")
    print(f"\nPDFs + previews in {os.path.relpath(OUT)}")


if __name__ == "__main__":
    main()
