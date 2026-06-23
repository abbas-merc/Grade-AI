"""
extract_two.py — Extract figures for the 2 questions still on a [Diagram: …]
text fallback (2021 Q5, 2022 Q4), reusing the same vector-cluster + spatial
matching used for the other 31. Saves crops locally for visual confirmation;
does NOT upload or touch Firestore.

Run from backend/:  python scripts/extract_two.py
"""
from __future__ import annotations

import json
import os
import sys

import fitz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.extract_diagrams import (  # noqa: E402
    PAPERS, _question_anchors, _figure_regions, _owning_question,
    _expand_with_labels, _render, _stack,
)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "diagram_out")
DOWNLOADS = os.path.expanduser(r"~/Downloads")

TARGETS = [
    ("0580/42/M/J/21", 5, "math_2021_MJ_058042_Q5"),
    ("0580/42/M/J/22", 4, "math_2022_MJ_058042_Q4"),
]


def main() -> None:
    extra_manifest = []
    for code, qnum, qid in TARGETS:
        pdf_name = PAPERS[code][0]
        doc = fitz.open(os.path.join(DOWNLOADS, pdf_name))
        anchors = _question_anchors(doc)
        regions = []
        for pi in range(len(doc)):
            page = doc[pi]
            if pi == 0 or "Permission to reproduce" in page.get_text("text"):
                continue
            for box in _figure_regions(page):
                if _owning_question(anchors, pi, box.y0) == qnum:
                    regions.append((pi, box))
        if not regions:
            print(f"{qid}: NO FIGURE FOUND")
            continue
        images, pages, boxes = [], [], []
        for (pi, box) in regions:
            grown = _expand_with_labels(doc[pi], box)
            images.append(_render(doc[pi], grown))
            pages.append(pi + 1)
            boxes.append([round(grown.x0), round(grown.y0), round(grown.x1), round(grown.y1)])
        out_png = os.path.join(OUT, f"{qid}.png")
        _stack(images).save(out_png)
        extra_manifest.append({"questionId": qid, "paperCode": code, "qNo": qnum,
                               "status": "OK", "nRegions": len(regions),
                               "pages": pages, "boxes": boxes,
                               "png": os.path.relpath(out_png, HERE)})
        print(f"{qid}: {len(regions)} region(s) on page(s) {pages} -> {out_png}")
        doc.close()

    with open(os.path.join(OUT, "_manifest_two.json"), "w", encoding="utf-8") as f:
        json.dump(extra_manifest, f, indent=2)


if __name__ == "__main__":
    main()
