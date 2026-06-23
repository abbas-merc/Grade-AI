"""
extract_diagrams.py — Extract diagram figures for the 33 hasImage questions.

The Cambridge 0580 figures are VECTOR line art (page.get_images() is empty on
every page), so we cannot pull an embedded raster. Instead we:

  1. Find figure regions on a page by clustering vector paths
     (page.get_drawings()) into spatially-connected components, dropping the
     page border and tiny inline-maths marks.
  2. Expand each region to swallow adjacent label text (vertex letters,
     "NOT TO SCALE", axis numbers) which are TEXT, not part of the path bbox.
  3. Match each region to the owning top-level question by scanning left-margin
     question-number anchors across the whole paper, in reading order.
  4. Rasterise the cropped region to a PNG (white background, high DPI). If a
     question owns several regions, stack them vertically into one image.

Output:
  scripts/diagram_out/<questionId>.png        one image per matched question
  scripts/diagram_out/_manifest.json          machine-readable match report
  scripts/diagram_out/_pages/<paper>_pXX.png  full-page renders (debug context)

Run from backend/:  python scripts/extract_diagrams.py
"""
from __future__ import annotations

import json
import os
import re
import sys

import fitz  # PyMuPDF
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
DOWNLOADS = os.path.expanduser(r"~/Downloads")
OUT_DIR = os.path.join(HERE, "diagram_out")
PAGES_DIR = os.path.join(OUT_DIR, "_pages")

# paperCode -> source question-paper PDF, and the doc-id session token.
PAPERS = {
    "0580/42/M/J/21": ("0580_s21_qp_42.pdf", "math_2021_MJ_058042"),
    "0580/42/M/J/22": ("0580_s22_qp_42.pdf", "math_2022_MJ_058042"),
    "0580/42/M/J/23": ("0580_s23_qp_42.pdf", "math_2023_MJ_058042"),
    "0580/42/O/N/22": ("0580_w22_qp_42.pdf", "math_2022_ON_058042"),
    "0580/42/O/N/23": ("0580_w23_qp_42.pdf", "math_2023_ON_058042"),
}

# Which top-level question numbers need a diagram, per paper (from Firestore).
IMAGE_QUESTIONS = {
    "0580/42/M/J/21": [2, 4, 6, 7, 8, 9],
    "0580/42/M/J/22": [2, 5, 7, 9, 11],
    "0580/42/M/J/23": [1, 3, 4, 7, 8, 10],
    "0580/42/O/N/22": [2, 3, 4, 6, 7, 8, 9, 10],
    "0580/42/O/N/23": [1, 2, 4, 6, 7, 8, 9, 10],
}

# --- tuning knobs ----------------------------------------------------------
ZOOM = 3.0               # raster scale (≈216 dpi)
CLUSTER_GAP = 16.0       # pt: merge vector rects whose gap is below this
MIN_FIG_W = 45.0         # pt: a real figure/grid is at least this wide…
MIN_FIG_H = 32.0         # …and this tall (drops surds, vector brackets, bars)
MIN_RECTS = 1            # size, not segment count, is the gate (polyline figs = 1 obj)
LABEL_MARGIN = 14.0      # pt: pull in label text this close to the figure
PAD = 9.0                # pt: padding around the final crop
ANCHOR_X = 60.0          # pt: question numbers sit at x≈49.6; sub-parts at x≈72.3
# ---------------------------------------------------------------------------

# A question-number anchor: a bold, left-margin span that STARTS with the
# number, whether it stands alone ('9') or is glued to the first sub-part
# ('10 (a) '). Body text and sub-parts live at x≈72, so the x filter excludes
# them; the bold filter excludes stray digits in running text.
LEAD_INT_RE = re.compile(r"^\s*(\d{1,2})(?:\D|$)")
_BOLD_FLAG = 16


def _rects_overlap_or_near(a, b, gap):
    """True if rects a, b overlap or are within `gap` in both axes."""
    return not (
        a.x0 - gap > b.x1 or b.x0 - gap > a.x1 or
        a.y0 - gap > b.y1 or b.y0 - gap > a.y1
    )


def _cluster_rects(rects, gap):
    """Greedy connected-components clustering of rects by proximity."""
    clusters: list[dict] = []  # each: {"box": Rect, "members": [Rect,...]}
    for r in rects:
        hit = None
        for c in clusters:
            if _rects_overlap_or_near(c["box"], r, gap):
                hit = c
                break
        if hit is None:
            clusters.append({"box": fitz.Rect(r), "members": [r]})
        else:
            hit["box"] |= r
            hit["members"].append(r)
    # Merge passes: clusters may have grown to touch each other.
    merged = True
    while merged:
        merged = False
        out: list[dict] = []
        for c in clusters:
            placed = False
            for o in out:
                if _rects_overlap_or_near(o["box"], c["box"], gap):
                    o["box"] |= c["box"]
                    o["members"].extend(c["members"])
                    placed = True
                    merged = True
                    break
            if not placed:
                out.append(c)
        clusters = out
    return clusters


def _question_anchors(doc):
    """Return ordered [(page_idx, y0, qnum)] for left-margin question numbers."""
    anchors = []
    for pi in range(len(doc)):
        page = doc[pi]
        d = page.get_text("dict")
        for block in d.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    x0, y0 = span["bbox"][0], span["bbox"][1]
                    if x0 >= ANCHOR_X or y0 <= 55:
                        continue
                    if not (span["flags"] & _BOLD_FLAG):
                        continue
                    m = LEAD_INT_RE.match(span["text"])
                    if not m:
                        continue
                    qn = int(m.group(1))
                    if 1 <= qn <= 12:
                        anchors.append((pi, y0, qn))
    anchors.sort(key=lambda a: (a[0], a[1]))
    return anchors


def _figure_regions(page):
    """Cluster vector paths on a page into candidate figure bboxes."""
    pr = page.rect
    rects = []
    for d in page.get_drawings():
        r = fitz.Rect(d["rect"])
        r.normalize()
        # A horizontal/vertical line has a zero-thickness bbox; KEEP it (grids,
        # histograms and axes are built from such lines) — only drop a true
        # degenerate point.
        if r.width <= 0 and r.height <= 0:
            continue
        # Drop the full-page border / margin frame.
        if r.width > pr.width * 0.92 and r.height > pr.height * 0.92:
            continue
        # Give lines a 1pt thickness so proximity clustering can connect them.
        if r.width < 1:
            r.x1 = r.x0 + 1
        if r.height < 1:
            r.y1 = r.y0 + 1
        rects.append(r)
    clusters = _cluster_rects(rects, CLUSTER_GAP)
    figs = []
    for c in clusters:
        box = c["box"]
        if box.width >= MIN_FIG_W and box.height >= MIN_FIG_H and len(c["members"]) >= MIN_RECTS:
            figs.append(box)
    figs.sort(key=lambda b: b.y0)
    return figs


def _expand_with_labels(page, box):
    """Grow a figure box to include label text (vertex letters, NOT TO SCALE,
    axis numbers) that sits within LABEL_MARGIN of the box."""
    grown = fitz.Rect(box)
    near = fitz.Rect(box) + (-LABEL_MARGIN, -LABEL_MARGIN, LABEL_MARGIN, LABEL_MARGIN)
    d = page.get_text("dict")
    for block in d.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                sb = fitz.Rect(span["bbox"])
                if sb.is_empty:
                    continue
                if near.intersects(sb):
                    # Only union spans that are small labels, not whole
                    # paragraph lines wider than the figure itself.
                    if sb.width <= box.width + 2 * LABEL_MARGIN:
                        grown |= sb
    return grown


def _owning_question(anchors, page_idx, y_top):
    """The qnum of the nearest anchor at or before (page_idx, y_top)."""
    best = None
    for (pi, ay, qn) in anchors:
        if (pi, ay) <= (page_idx, y_top):
            best = qn
        else:
            break
    return best


def _render(page, box):
    box = fitz.Rect(box) + (-PAD, -PAD, PAD, PAD)
    box &= page.rect
    pix = page.get_pixmap(clip=box, matrix=fitz.Matrix(ZOOM, ZOOM), alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _stack(images: list[Image.Image]) -> Image.Image:
    if len(images) == 1:
        return images[0]
    gap = 16
    w = max(im.width for im in images)
    h = sum(im.height for im in images) + gap * (len(images) - 1)
    canvas = Image.new("RGB", (w, h), "white")
    y = 0
    for im in images:
        canvas.paste(im, ((w - im.width) // 2, y))
        y += im.height + gap
    return canvas


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(PAGES_DIR, exist_ok=True)
    manifest = []

    for code, (pdf_name, doc_prefix) in PAPERS.items():
        path = os.path.join(DOWNLOADS, pdf_name)
        doc = fitz.open(path)
        anchors = _question_anchors(doc)
        wanted = set(IMAGE_QUESTIONS[code])

        # Collect every figure region in the paper, tagged with its owner.
        figs_by_q: dict[int, list[tuple[int, fitz.Rect]]] = {}
        for pi in range(len(doc)):
            page = doc[pi]
            txt = page.get_text("text")
            # Skip the cover (pi 0, has the UCLES logo art) and the copyright
            # back-matter page (no question figures, just acknowledgements).
            if pi == 0 or "Permission to reproduce" in txt:
                continue
            for box in _figure_regions(page):
                qn = _owning_question(anchors, pi, box.y0)
                if qn is None:
                    continue
                figs_by_q.setdefault(qn, []).append((pi, box))

        for qn in IMAGE_QUESTIONS[code]:
            qid = f"{doc_prefix}_Q{qn}"
            regions = figs_by_q.get(qn, [])
            if not regions:
                manifest.append({
                    "questionId": qid, "paperCode": code, "qNo": qn,
                    "status": "NO_FIGURE_FOUND", "nRegions": 0, "pages": [], "png": None,
                })
                continue
            images = []
            pages = []
            boxes = []
            for (pi, box) in regions:
                grown = _expand_with_labels(doc[pi], box)
                images.append(_render(doc[pi], grown))
                pages.append(pi + 1)  # 1-based page label
                boxes.append([round(grown.x0), round(grown.y0), round(grown.x1), round(grown.y1)])
            out_png = os.path.join(OUT_DIR, f"{qid}.png")
            _stack(images).save(out_png)
            manifest.append({
                "questionId": qid, "paperCode": code, "qNo": qn,
                "status": "OK", "nRegions": len(regions), "pages": pages,
                "boxes": boxes, "png": os.path.relpath(out_png, HERE),
            })
        doc.close()

    with open(os.path.join(OUT_DIR, "_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    ok = [m for m in manifest if m["status"] == "OK"]
    multi = [m for m in ok if m["nRegions"] > 1]
    fail = [m for m in manifest if m["status"] != "OK"]
    print(f"Matched figures for {len(ok)}/{len(manifest)} image questions.")
    print(f"  single-region: {len(ok) - len(multi)}   multi-region: {len(multi)}")
    if multi:
        print("  multi-region questions (several figures stacked):")
        for m in multi:
            print(f"    {m['questionId']}  regions={m['nRegions']} pages={m['pages']}")
    if fail:
        print(f"  NO FIGURE FOUND ({len(fail)}):")
        for m in fail:
            print(f"    {m['questionId']} ({m['paperCode']} Q{m['qNo']})")
    print(f"\nOutput dir: {OUT_DIR}")


if __name__ == "__main__":
    main()
