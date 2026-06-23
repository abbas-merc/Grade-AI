"""
test_generate_with_images.py — End-to-end check (step 8): run the real
generate_paper selection for geometry + trigonometry, confirm diagram questions
are included with imageUrls, render the question-paper PDF, and rasterise its
pages so the embedded figures can be eyeballed.

Run from backend/:  python scripts/test_generate_with_images.py
"""
from __future__ import annotations

import os
import sys

import fitz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from routers.paper_generator import GeneratePaperRequest, generate_paper  # noqa: E402
from utils.pdf_generator import (  # noqa: E402
    generate_mark_scheme_pdf,
    generate_question_paper_pdf,
)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "diagram_out")


def main() -> None:
    req = GeneratePaperRequest(
        subject="math",
        topics=["geometry", "trigonometry"],
        totalMarks=90,
        difficulty="mixed",
    )
    resp = generate_paper(req, uid="test-script")
    paper = resp.model_dump() if hasattr(resp, "model_dump") else resp.dict()

    qs = paper["questions"]
    img_qs = [q for q in qs if q.get("hasImage") and q.get("imageUrl")]
    print(f"Generated paper: {len(qs)} questions, {paper['totalMarks']} marks")
    print(f"Image questions included: {len(img_qs)}")
    for q in qs:
        flag = "IMG" if q.get("hasImage") else "txt"
        print(f"  Q{q['assignedNumber']:<2} [{flag}] {q['marks']:>2}m  {q['topic']:<13} {q.get('imageUrl','')}")

    qp = generate_question_paper_pdf(paper)
    ms = generate_mark_scheme_pdf(paper)
    qp_path = os.path.join(OUT, "_test_qp.pdf")
    ms_path = os.path.join(OUT, "_test_ms.pdf")
    open(qp_path, "wb").write(qp)
    open(ms_path, "wb").write(ms)
    print(f"\nQuestion paper PDF: {qp_path}  ({len(qp)//1024} KB)")
    print(f"Mark scheme PDF:    {ms_path}  ({len(ms)//1024} KB)")

    # Rasterise the QP pages so the embedded figures can be reviewed, and count
    # embedded raster images per page as a hard check that figures got placed.
    doc = fitz.open(qp_path)
    total_imgs = 0
    for i, page in enumerate(doc):
        n = len(page.get_images(full=True))
        total_imgs += n
        page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6)).save(
            os.path.join(OUT, f"_test_qp_p{i+1}.png")
        )
    print(f"\nQP pages: {len(doc)}, embedded raster figures total: {total_imgs}")
    doc.close()


if __name__ == "__main__":
    main()
