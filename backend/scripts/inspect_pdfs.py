"""
inspect_pdfs.py — One-off diagnostic: understand the source PDFs before any
diagram extraction. Answers three questions:

  1. Which paper(s) does each PDF actually contain? (paper code per page)
  2. Are the figures EMBEDDED RASTER IMAGES (page.get_images -> extractable via
     pdfplumber page.images) or VECTOR LINE ART (page.get_drawings -> only
     reproducible by rasterising a page region)?
  3. Rough page->question mapping, so we can gauge whether spatial matching is
     even viable.

Run:  python scripts/inspect_pdfs.py
"""
from __future__ import annotations

import os
import re
import sys

import fitz  # PyMuPDF

HERE = os.path.dirname(os.path.abspath(__file__))
# The real Cambridge source question papers live in the user's Downloads folder.
PAPERS = os.path.expanduser(r"~/Downloads")

# The 5 question papers (qp), one per seeded paperCode.
CANDIDATES = [
    "0580_s21_qp_42.pdf",  # 0580/42/M/J/21
    "0580_s22_qp_42.pdf",  # 0580/42/M/J/22
    "0580_s23_qp_42.pdf",  # 0580/42/M/J/23
    "0580_w22_qp_42.pdf",  # 0580/42/O/N/22
    "0580_w23_qp_42.pdf",  # 0580/42/O/N/23
]

PAPER_CODE_RE = re.compile(r"0580/\d{2}/[A-Z]/[A-Z]/\d{2}")
# A leading question number at the very start of a line, e.g. "6  The diagram..."
QNUM_RE = re.compile(r"^\s*(\d{1,2})\s")


def classify_page(page: fitz.Page) -> dict:
    imgs = page.get_images(full=True)
    drawings = page.get_drawings()
    # Count "substantial" vector drawings (those with several segments) to tell
    # real figures apart from underline rules / answer-line dashes.
    big_drawings = 0
    for d in drawings:
        items = d.get("items", [])
        if len(items) >= 4:
            big_drawings += 1
    text = page.get_text("text")
    codes = sorted(set(PAPER_CODE_RE.findall(text)))
    return {
        "n_images": len(imgs),
        "n_drawings": len(drawings),
        "n_big_drawings": big_drawings,
        "codes": codes,
        "text_head": " ".join(text.split())[:90],
    }


def main() -> None:
    for name in CANDIDATES:
        path = os.path.join(PAPERS, name)
        if not os.path.exists(path):
            print(f"\n### {name}: NOT FOUND at {path}")
            continue
        doc = fitz.open(path)
        print(f"\n{'='*78}\n### {name}  —  {len(doc)} pages, {os.path.getsize(path)//1024} KB\n{'='*78}")
        total_imgs = 0
        total_big_draw = 0
        codes_seen: set[str] = set()
        for i, page in enumerate(doc):
            info = classify_page(page)
            total_imgs += info["n_images"]
            total_big_draw += info["n_big_drawings"]
            codes_seen.update(info["codes"])
            # Print per-page only for the first PDF (the question paper) to keep
            # output readable; summarise images/drawings everywhere.
            flag = ""
            if info["n_images"]:
                flag += f" [IMAGES x{info['n_images']}]"
            if info["n_big_drawings"]:
                flag += f" [VECTOR x{info['n_big_drawings']}]"
            print(
                f"p{i:>3} imgs={info['n_images']:>2} draw={info['n_drawings']:>3} "
                f"bigdraw={info['n_big_drawings']:>2} codes={','.join(info['codes']) or '-':<28}"
                f"{flag}  | {info['text_head']}"
            )
        print(
            f"\nSUMMARY {name}: pages={len(doc)} total_embedded_images={total_imgs} "
            f"total_big_vector_drawings={total_big_draw}"
        )
        print(f"PAPER CODES FOUND: {sorted(codes_seen)}")
        doc.close()


if __name__ == "__main__":
    main()
