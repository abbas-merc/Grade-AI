"""
build_question_bank.py — Extract image-snippet questions + mark-scheme text for
the new 4-paper IGCSE 0580 question bank.

For each of the 4 question papers it:
  1. Detects top-level question anchors (bold, left-margin, size-11.5 number
     spans) with PyMuPDF — validated identical across all 4 papers at x0~49.6.
  2. Computes each question's crop region(s); a question that spans pages (every
     Paper 4 question does) is stitched from consecutive page-regions into one
     tall PNG. The crop bottom is auto-detected just above the page footer.
  3. Renders at 200 DPI to scripts/question_snippets/{code}_Q{n}.png.

For each mark scheme it parses per-question mark-scheme TEXT with PyMuPDF's
get_text (pdfplumber mis-orders the 2025 specimen schemes — its text layer is
reversed; fitz reads them correctly). Questions are segmented by their label
using reading order + a sequence check (a label is the next integer, or a
sub-part of the current one), with an x-column guard on the clean June papers.

It then infers marks (sum of the QP "[k]" annotations), topic (keyword match)
and difficulty (paper-type-aware mark thresholds), writes a machine-readable
manifest, and renders one contact-sheet montage per paper for visual review.

NOTHING is written to Firestore or Firebase here — this only produces local
files for review. Upload happens in a separate step after sign-off.

Run from backend/:  python scripts/build_question_bank.py
"""
from __future__ import annotations

import json
import os
import re

import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
DL = os.path.expanduser("~/Downloads")
SNIP_DIR = os.path.join(HERE, "question_snippets")
MONTAGE_DIR = os.path.join(HERE, "question_bank_review")
MANIFEST = os.path.join(HERE, "question_bank_manifest.json")

# --------------------------------------------------------------------------- #
# Paper definitions
# --------------------------------------------------------------------------- #
# code        : underscore-safe token used for image filenames + Firestore ids
# paperCode   : human-readable code stored on the doc
# paperType   : "P2" | "P4"
PAPERS = [
    {
        "code": "058021_2024", "paperType": "P2", "paperCode": "0580/21/2024",
        "year": 2024, "isSpecimen": False,
        "name": "IGCSE Math 0580 Paper 2 Variant 1 2024",
        "qp": "569924-june-2024-question-paper-21.pdf",
        "ms": "569920-june-2024-mark-scheme-paper-21.pdf",
    },
    {
        "code": "058041_2024", "paperType": "P4", "paperCode": "0580/41/2024",
        "year": 2024, "isSpecimen": False,
        "name": "IGCSE Math 0580 Paper 4 Variant 1 2024",
        "qp": "671439-june-2024-question-paper-41.pdf",
        "ms": "671437-june-2024-mark-scheme-paper-41.pdf",
    },
    {
        "code": "0580_2_SP_2025", "paperType": "P2", "paperCode": "0580/02/SP/2025",
        "year": 2025, "isSpecimen": True,
        "name": "IGCSE Math 0580 Paper 2 Specimen 2025",
        "qp": "663664-2025-specimen-paper-2.pdf",
        "ms": "663672-2025-specimen-paper-2-mark-scheme.pdf",
    },
    {
        "code": "0580_4_SP_2025", "paperType": "P4", "paperCode": "0580/04/SP/2025",
        "year": 2025, "isSpecimen": True,
        "name": "IGCSE Math 0580 Paper 4 Specimen 2025",
        "qp": "663668-2025-specimen-paper-4.pdf",
        "ms": "663676-2025-specimen-paper-4-mark-scheme.pdf",
    },
]

# --------------------------------------------------------------------------- #
# Rendering / geometry knobs
# --------------------------------------------------------------------------- #
ZOOM = 2.78               # ~200 DPI
CONTENT_X0, CONTENT_X1 = 38.0, 560.0
CONTENT_TOP = 50.0
CONTENT_BOTTOM_MAX = 808.0   # hard floor if no footer line is found
ANCHOR_TOP_PAD = 7.0         # px above the question number
NEXT_GAP = 4.0               # stop this far above the next question number
BOLD = 16

# Footer markers — the crop bottom is set just above the first line matching one
# of these in the bottom band, so the "© UCLES … [Turn over]" strip is excluded.
_FOOTER_RE = re.compile(r"(UCLES|©|Turn over|Cambridge|0580/|Page \d+ of)", re.I)
_BLANK_RE = re.compile(r"BLANK PAGE", re.I)
_COPYRIGHT_RE = re.compile(r"(Permission to reproduce|Copyright Acknowledgements|"
                           r"every reasonable effort)", re.I)

_LEAD_INT = re.compile(r"^\s*(\d{1,2})(?:\s|\(|$)")


# --------------------------------------------------------------------------- #
# QP: anchors + regions + rendering
# --------------------------------------------------------------------------- #
def question_anchors(doc) -> list[tuple[int, float, int]]:
    """Ordered [(page_idx, y0, qnum)] for left-margin question numbers.

    The discriminating signature is position (x0 ~= 49.6, left margin) + size
    (~11.5) + a leading integer, validated by the caller's 1..N sequence check.
    Boldness is deliberately NOT required: the 2024 papers and the 2025 specimen
    render their question numbers bold (flags & 16), but the 2025 real exam
    papers render them serifed-but-not-bold (flags == 4). Requiring bold silently
    matched zero questions on every 2025 paper. Dropping it is verified to leave
    the 2024/existing/specimen anchor sets byte-identical while unlocking 2025.
    """
    anchors: list[tuple[int, float, int]] = []
    for pi in range(len(doc)):
        for block in doc[pi].get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    x0, y0 = span["bbox"][0], span["bbox"][1]
                    if not (45 <= x0 <= 55) or y0 <= 55:
                        continue
                    if not (11.0 <= span["size"] <= 12.0):
                        continue
                    m = _LEAD_INT.match(span["text"])
                    if not m:
                        continue
                    qn = int(m.group(1))
                    if 1 <= qn <= 40:
                        anchors.append((pi, y0, qn))
    anchors.sort(key=lambda a: (a[0], a[1]))
    return anchors


def page_is_skippable(page) -> bool:
    txt = page.get_text("text") or ""
    if _BLANK_RE.search(txt) or _COPYRIGHT_RE.search(txt):
        return True
    return len(txt.strip()) < 25


def footer_bottom(page) -> float:
    """Crop bottom for a page: just above the first footer-ish line in the
    bottom band, else the hard floor."""
    best = CONTENT_BOTTOM_MAX
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            y0 = line["bbox"][1]
            if y0 < 770:
                continue
            txt = "".join(s["text"] for s in line.get("spans", [])).strip()
            if txt and _FOOTER_RE.search(txt):
                best = min(best, y0 - 3)
    return best


def _content_top(page, desired_top: float) -> float:
    """Push `desired_top` below any top-of-page barcode furniture.

    The 2025 papers carry a 1-D barcode at y~54 (rendered in a barcode font, so
    its span text is full of non-printable control characters) sitting just above
    the first question and just below CONTENT_TOP. A crop starting at its normal
    top slices that black strip in. We detect the barcode by its control chars
    (no real question text has them) and, only when it actually intrudes at/above
    the desired top, start the crop just beneath it. No-op on papers without such
    furniture (all 2024 papers), so their crops are byte-identical."""
    barcode_bottom = None
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span["bbox"][1] > desired_top + 30:   # only near/above the top
                    continue
                if any(ord(c) < 32 and c not in "\t\n\r" for c in span["text"]):
                    y1 = span["bbox"][3]
                    barcode_bottom = y1 if barcode_bottom is None else max(barcode_bottom, y1)
    if barcode_bottom is not None and barcode_bottom > desired_top:
        return barcode_bottom + 2.0
    return desired_top


def question_regions(doc, anchors, i) -> list[tuple[int, float, float]]:
    """[(page_idx, y_top, y_bottom)] for question i, spanning pages as needed.

    Every region's top is pushed below any top-of-page barcode strip (see
    _content_top) so the 2025 papers' barcode is never sliced into the crop."""
    p, y, _ = anchors[i]
    nxt = anchors[i + 1] if i + 1 < len(anchors) else None
    top = _content_top(doc[p], y - ANCHOR_TOP_PAD)

    if nxt and nxt[0] == p:                       # same page → single region
        return [(p, top, nxt[1] - NEXT_GAP)]

    regions: list[tuple[int, float, float]] = [(p, top, footer_bottom(doc[p]))]
    if nxt:
        for mid in range(p + 1, nxt[0]):
            if not page_is_skippable(doc[mid]):
                regions.append((mid, _content_top(doc[mid], CONTENT_TOP), footer_bottom(doc[mid])))
        regions.append((nxt[0], _content_top(doc[nxt[0]], CONTENT_TOP), nxt[1] - NEXT_GAP))
    else:                                         # last question
        mid = p + 1
        while mid < len(doc) and not page_is_skippable(doc[mid]):
            regions.append((mid, _content_top(doc[mid], CONTENT_TOP), footer_bottom(doc[mid])))
            mid += 1
    return regions


def render_region(page, y0, y1) -> Image.Image:
    clip = fitz.Rect(CONTENT_X0, max(y0, 0), CONTENT_X1, min(y1, page.rect.height))
    pix = page.get_pixmap(clip=clip, matrix=fitz.Matrix(ZOOM, ZOOM), alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def stitch(images: list[Image.Image]) -> Image.Image:
    if len(images) == 1:
        return images[0]
    w = max(im.width for im in images)
    h = sum(im.height for im in images)
    canvas = Image.new("RGB", (w, h), "white")
    y = 0
    for im in images:
        canvas.paste(im, (0, y))
        y += im.height
    return canvas


def region_text(doc, regions) -> str:
    out = []
    for (pi, y0, y1) in regions:
        clip = fitz.Rect(CONTENT_X0, y0, CONTENT_X1, y1)
        out.append(doc[pi].get_text("text", clip=clip))
    return "\n".join(out)


def looks_cut_off(img: Image.Image) -> bool:
    """Heuristic: dark pixels hugging the very top or bottom edge suggest the
    crop sliced through a line of text/figure."""
    g = img.convert("L")
    w, h = g.size
    for band_y in (0, h - 2):
        row = g.crop((0, band_y, w, band_y + 2)).getdata()
        dark = sum(1 for px in row if px < 110)
        if dark > w * 0.12:
            return True
    return False


# --------------------------------------------------------------------------- #
# Marks / topic / difficulty inference
# --------------------------------------------------------------------------- #
_MARK_RE = re.compile(r"\[(\d{1,2})\]")


def detect_marks(qp_text: str) -> int:
    return sum(int(m) for m in _MARK_RE.findall(qp_text))


# Ordered most-specific first; first topic to clear the score wins ties by order.
_TOPIC_KEYWORDS = {
    "calculus": ["gradient of the curve", "dy/dx", "derivative", "differentiate",
                 "turning point", "stationary point", "rate of change", "tangent to the curve",
                 "integrate", "area under"],
    "vectors": ["vector", "column vector", "position vector", "magnitude of",
                "midpoint of o", r"\\binom", "in terms of p and q", "⃗"],
    "trigonometry": ["sine rule", "cosine rule", "angle of elevation", "angle of depression",
                     "bearing", "sin", "cos", "tan", "trigonometr"],
    "probability": ["probability", "tree diagram", "at random", "p(a", "dice", "spinner",
                    "without replacement", "relative frequency"],
    "statistics": ["histogram", "frequency density", "cumulative frequency", "box-and-whisker",
                   "interquartile", "median", "mean", "standard deviation", "pie chart",
                   "scatter", "stem-and-leaf", "quartile"],
    "geometry": ["polygon", "circle", "triangle", "quadrilateral", "parallelogram",
                 "trapezium", "perimeter", "circumference", "radius", "diameter", "sector",
                 "area", "volume", "surface area", "congruent", "similar", "transformation",
                 "reflection", "rotation", "enlargement", "translation", "parallel",
                 "angle", "bearing", "loci", "locus", "pythagoras", "cuboid", "cylinder",
                 "sphere", "cone", "prism"],
    "algebra": ["simplify", "expand", "factorise", "factorize", "solve", "equation",
                "expression", "inequalit", "nth term", "sequence", "rearrange",
                "make x the subject", "subject of the formula", "function", "f(x)", "g(x)",
                "quadratic", "simultaneous", "indices", "exponential", "graph of y"],
    "number": ["percentage", "ratio", "fraction", "standard form", "prime", "hcf", "lcm",
               "highest common factor", "lowest common multiple", "compound interest",
               "simple interest", "exchange rate", "currency", "upper bound", "lower bound",
               "significant figure", "decimal place", "estimate", "speed", "density"],
}


def detect_topic(text: str) -> str:
    t = text.lower()
    scores: dict[str, int] = {}
    for topic, kws in _TOPIC_KEYWORDS.items():
        s = 0
        for kw in kws:
            if kw.startswith("\\b") or "\\" in kw:
                try:
                    s += len(re.findall(kw, t))
                    continue
                except re.error:
                    pass
            s += t.count(kw)
        if s:
            scores[topic] = s
    if not scores:
        return "number"
    # Highest score wins; ties broken by the dict's specificity order.
    order = list(_TOPIC_KEYWORDS.keys())
    return max(scores, key=lambda k: (scores[k], -order.index(k)))


# Difficulty from marks. The old bank used <=10 easy / 11-13 medium / 14+ hard,
# tuned for whole Paper-4 questions; applied to the now-mixed bank (short Paper-2
# and new shorter specimen questions) it labels almost everything "easy". This
# unified scheme (<=3 easy / 4-7 medium / >=8 hard) gives the best spread across
# both paper types — P4 ~ 12/10/11, P2 ~ 30/14/4. (paper_type kept in the
# signature for callers; the scheme is currently type-agnostic.)
def detect_difficulty(paper_type: str, marks: int) -> str:
    if marks <= 3:
        return "easy"
    if marks <= 7:
        return "medium"
    return "hard"


# --------------------------------------------------------------------------- #
# Mark scheme parsing (fitz)
# --------------------------------------------------------------------------- #
# Tolerate optional whitespace between the number and its sub-parts: some schemes
# print "18 (a)" (with a space) instead of "18(a)". Without this, a single spaced
# label breaks the sequential parser for every question after it (observed on
# 0580/23/O/N/25, which lost Q18-29). The char class stays restricted to a-z0-9
# so real answer text like "3 (2x + 1)" (space/plus inside) still won't match.
_MS_LABEL = re.compile(r"^(\d{1,2})\s*((?:\([a-z0-9ivx]+\)\s*)*)$")
_MS_SKIP = re.compile(
    r"(Cambridge IGCSE|Mark Scheme|PUBLISHED|© Cambridge|UCLES|Page \d+ of|"
    r"May/June|October|SPECIMEN|For examination|Generic Marking|"
    r"Mathematics-Specific|Abbreviations|^0580/|^Question$|^Answer$|^Marks$|"
    r"^Partial Marks$)", re.I)
_ABBREVS = {"cao", "dep", "ft", "isw", "oe", "sc", "nfww", "soi"}


def _columns_reliable(doc, answer_pages) -> bool:
    """June schemes lay Question/Answer/Marks at well-separated x0; the corrupt
    specimen schemes stack them at the same x0. Detect which we have."""
    for pi in answer_pages:
        xs = {}
        for block in doc[pi].get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                txt = "".join(s["text"] for s in line.get("spans", [])).strip()
                if txt in ("Question", "Answer", "Marks"):
                    xs[txt] = line["bbox"][0]
        if len(xs) == 3:
            return (max(xs.values()) - min(xs.values())) > 80
    return False


def parse_mark_scheme(path: str, qnums: list[int]) -> tuple[dict[int, str], dict]:
    """Return ({qnum: markSchemeText}, debug_info). Segments by label using
    reading order + sequence; uses the x-column band as a guard when reliable."""
    doc = fitz.open(path)
    # Answer pages: from the first page carrying the table header to the end.
    answer_pages = []
    started = False
    for pi in range(len(doc)):
        t = doc[pi].get_text("text")
        if not started and "Answer" in t and "Marks" in t and "Question" in t:
            started = True
        if started:
            answer_pages.append(pi)

    reliable = _columns_reliable(doc, answer_pages)
    per_q: dict[int, list[str]] = {}
    cur = 0
    seen_content = False
    labels_found: list[str] = []

    for pi in answer_pages:
        for block in doc[pi].get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                x0 = line["bbox"][0]
                txt = "".join(s["text"] for s in line.get("spans", [])).strip()
                if not txt or _MS_SKIP.search(txt) or txt.lower() in _ABBREVS:
                    continue
                m = _MS_LABEL.match(txt)
                is_label = False
                if m:
                    L = int(m.group(1))
                    has_part = bool(m.group(2))
                    in_band = (55 <= x0 <= 112) if reliable else True
                    if in_band:
                        if cur == 0 and L == 1:
                            is_label = True
                        elif L == cur + 1 and seen_content:
                            is_label = True
                        elif L == cur and has_part:
                            is_label = True  # sub-part of current question
                if is_label:
                    L = int(m.group(1))
                    if L == cur + 1:
                        cur = L
                        per_q.setdefault(cur, [])
                        seen_content = False
                    labels_found.append(txt)
                    per_q.setdefault(cur, []).append(txt)
                elif cur >= 1:
                    per_q[cur].append(txt)
                    seen_content = True
    doc.close()

    text_by_q = {q: re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
                 for q, lines in per_q.items()}
    debug = {
        "reliable_columns": reliable,
        "answer_pages": [p + 1 for p in answer_pages],
        "top_levels_found": sorted(per_q.keys()),
        "labels_sample": labels_found[:12],
    }
    return text_by_q, debug


# --------------------------------------------------------------------------- #
# Montage (contact sheet) for visual review
# --------------------------------------------------------------------------- #
def _font(size: int):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


def build_montage(paper_code: str, items: list[dict], out_path: str) -> None:
    cols = 4
    cell_w, thumb_h_cap, label_h, pad = 360, 460, 46, 10
    thumbs = []
    for it in items:
        im = Image.open(it["_png"])
        scale = cell_w / im.width
        tw, th = cell_w, int(im.height * scale)
        if th > thumb_h_cap:
            th = thumb_h_cap
            tw = int(im.width * (thumb_h_cap / im.height))
        thumbs.append((it, im.resize((max(tw, 1), max(th, 1)))))

    rows = (len(thumbs) + cols - 1) // cols
    row_h = [0] * rows
    for idx, (_, t) in enumerate(thumbs):
        r = idx // cols
        row_h[r] = max(row_h[r], t.height + label_h)
    W = cols * cell_w + (cols + 1) * pad
    H = sum(row_h) + (rows + 1) * pad + 40
    sheet = Image.new("RGB", (W, H), "#f0f0f0")
    d = ImageDraw.Draw(sheet)
    d.text((pad, 10), f"{paper_code} — {len(items)} questions", fill="black", font=_font(20))

    y = 40 + pad
    for r in range(rows):
        x = pad
        for c in range(cols):
            idx = r * cols + c
            if idx >= len(thumbs):
                break
            it, t = thumbs[idx]
            flags = "".join([
                " ✂CUT" if it["flag_cutoff"] else "",
                " 📄x%d" % it["n_regions"] if it["n_regions"] > 1 else "",
                " ⚠noMS" if not it["has_ms"] else "",
            ])
            label = f"Q{it['originalQuestionNumber']} · {it['marks']}m · {it['topic']}/{it['difficulty']}{flags}"
            d.rectangle([x, y, x + cell_w, y + label_h - 4], fill="white", outline="#cccccc")
            d.text((x + 4, y + 4), label, fill="black", font=_font(13))
            cell = Image.new("RGB", (cell_w, t.height), "white")
            cell.paste(t, ((cell_w - t.width) // 2, 0))
            sheet.paste(cell, (x, y + label_h))
            x += cell_w + pad
        y += row_h[r] + pad
    sheet.save(out_path)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    os.makedirs(SNIP_DIR, exist_ok=True)
    os.makedirs(MONTAGE_DIR, exist_ok=True)
    manifest: list[dict] = []

    for paper in PAPERS:
        qp_path = os.path.join(DL, paper["qp"])
        ms_path = os.path.join(DL, paper["ms"])
        doc = fitz.open(qp_path)
        anchors = question_anchors(doc)
        qnums = [a[2] for a in anchors]

        # Validate the anchor sequence is exactly 1..N.
        expected = list(range(1, len(anchors) + 1))
        seq_ok = qnums == expected

        ms_by_q, ms_debug = parse_mark_scheme(ms_path, qnums)

        paper_items: list[dict] = []
        for i, (p, y, qn) in enumerate(anchors):
            regions = question_regions(doc, anchors, i)
            img = stitch([render_region(doc[rp], ry0, ry1) for (rp, ry0, ry1) in regions])
            png = os.path.join(SNIP_DIR, f"{paper['code']}_Q{qn}.png")
            img.save(png, optimize=True)

            qp_text = region_text(doc, regions)
            marks = detect_marks(qp_text)
            topic = detect_topic(qp_text)
            difficulty = detect_difficulty(paper["paperType"], marks)
            ms_text = ms_by_q.get(qn, "")

            item = {
                "id": f"{paper['code']}_Q{qn}",
                "subject": "math",
                "paperType": paper["paperType"],
                "paperCode": paper["paperCode"],
                "year": paper["year"],
                "isSpecimen": paper["isSpecimen"],
                "originalQuestionNumber": qn,
                "marks": marks,
                "topic": topic,
                "difficulty": difficulty,
                "markSchemeText": ms_text,
                "questionImageUrl": f"/question_snippets/{paper['code']}_Q{qn}.png",
                # review-only fields (not uploaded)
                "_png": png,
                "_png_size_kb": os.path.getsize(png) // 1024,
                "_img_px": f"{img.width}x{img.height}",
                "n_regions": len(regions),
                "pages": sorted({rp + 1 for (rp, _, _) in regions}),
                "flag_cutoff": looks_cut_off(img),
                "has_ms": bool(ms_text.strip()),
                "ms_len": len(ms_text),
            }
            paper_items.append(item)
            manifest.append(item)

        doc.close()

        montage = os.path.join(MONTAGE_DIR, f"{paper['code']}_montage.png")
        build_montage(paper["paperCode"], paper_items, montage)

        # Per-paper console report
        ms_missing = [it["originalQuestionNumber"] for it in paper_items if not it["has_ms"]]
        cutoffs = [it["originalQuestionNumber"] for it in paper_items if it["flag_cutoff"]]
        multipage = [it["originalQuestionNumber"] for it in paper_items if it["n_regions"] > 1]
        print(f"\n=== {paper['name']}  [{paper['paperCode']}  {paper['paperType']}] ===")
        print(f"  questions: {len(paper_items)}   anchor seq 1..N ok: {seq_ok}")
        print(f"  MS reliable cols: {ms_debug['reliable_columns']}   "
              f"MS answer pages: {ms_debug['answer_pages']}")
        print(f"  MS top-levels found: {ms_debug['top_levels_found']}")
        print(f"  multi-page (stitched): {multipage}")
        print(f"  MISSING mark scheme: {ms_missing or 'none'}")
        print(f"  possible cut-off: {cutoffs or 'none'}")
        print(f"  montage -> {os.path.relpath(montage)}")

    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    # Global distributions
    from collections import Counter
    bytype = Counter(m["paperType"] for m in manifest)
    bydiff = Counter((m["paperType"], m["difficulty"]) for m in manifest)
    bytopic = Counter(m["topic"] for m in manifest)
    print("\n" + "=" * 64)
    print(f"TOTAL questions: {len(manifest)}   by paperType: {dict(bytype)}")
    print(f"by topic: {dict(bytopic)}")
    print("\ncount  /  marks-available  per (paperType, difficulty):")
    for pt in ("P2", "P4"):
        for d in ("easy", "medium", "hard"):
            sel = [m["marks"] for m in manifest if m["paperType"] == pt and m["difficulty"] == d]
            print(f"   {pt} {d:6}: {len(sel):2} questions, {sum(sel):3} marks available")
        allpt = [m["marks"] for m in manifest if m["paperType"] == pt]
        print(f"   {pt} ALL   : {len(allpt):2} questions, {sum(allpt):3} marks available "
              f"(per-Q min={min(allpt)} max={max(allpt)})")
    print(f"\nmanifest -> {os.path.relpath(MANIFEST)}")
    print(f"snippets -> {os.path.relpath(SNIP_DIR)}")


if __name__ == "__main__":
    main()
