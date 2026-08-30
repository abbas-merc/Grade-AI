"""
build_part_figures.py — Diagram-ONLY crops, per sub-part and per shared figure.

The part-level extraction already ships two kinds of image:

* ``question_parts/<partId>.png``   — the whole sub-part, **text included**
* ``question_assets/<assetId>.png`` — figures/contexts shared by 2+ sub-parts

Neither is usable by the LaTeX pipeline. The first would print the question text
twice (once as typeset LaTeX, once as a picture of itself). The second is close,
but its detector (``build_part_extraction._figures_in_regions``) treats Cambridge's
full-height page-edge registration bar as a drawing: because that bar spans every
question on the page, the "figure" band it produces stretches from the top of the
question to the bottom of its answer space, so the crop is the whole question
again. That is harmless where those assets are used today (they are only ever
shown as an extra context picture) but fatal here.

So this script does its own, stricter detection — same page regions, same
renderer, same zoom as ``build_question_bank`` so the crops stay aligned with
everything already shipped, but with page furniture excluded:

* only geometry that actually intersects the content column (x 38..560) counts,
  which drops the edge bar and the margin registration marks outright;
* nothing taller than ``MAX_BAND_FRACTION`` of the page counts, as a second guard;
* full-width hairlines (answer rules, separators) are dropped;
* the surviving primitives are clustered vertically into bands, and a band must
  be at least ``MIN_BAND_PT`` tall to be a diagram at all.

A band overlapping exactly one leaf becomes that sub-part's own figure; a band
overlapping several becomes a shared figure recorded against every leaf that
needs it, so the template can print it once above the group; a band above the
first "(a)" belongs to the question stem and is recorded against the question.

It also crops and OCR-free-extracts the question STEM — everything above the
first "(a)" label. ``build_leaves`` assigns that band to no leaf, so before this
the shared stem ("Amira goes fishing. The probability that it rains is ...") was
simply absent from the extraction input and vanished from the generated paper.

Outputs:
  scripts/question_figures/<partId|assetId>.png
  scripts/question_stems/<questionId|<qid>_<letter>.png   (extraction input only)
  scripts/part_extraction/part_figures.json
      {"parts":  {partId:  {...}},
       "shared": {assetId: {usedByParts, ...}},
       "stems":  {questionId: {...}},          # everything above the first "(a)"
       "groupStems": {"<qid>_<letter>": {...}}}  # a letter part's own intro

Run from backend/:
  python scripts/build_part_figures.py                     # all papers
  python scripts/build_part_figures.py --paper 058021_s25  # one paper (additive)
"""
from __future__ import annotations

import json
import os
import re
import sys

import fitz  # PyMuPDF

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_part_extraction import _load_inventory, _overlaps_leaf, build_leaves  # noqa: E402
from build_question_bank import (  # noqa: E402
    CONTENT_X0, CONTENT_X1, question_anchors, question_regions, region_text,
    render_region, stitch,
)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "part_extraction")
FIG_IMG_DIR = os.path.join(HERE, "question_figures")
STEM_IMG_DIR = os.path.join(HERE, "question_stems")
OUT_JSON = os.path.join(OUT_DIR, "part_figures.json")

# Vertical padding (PDF points) around a detected band. Point labels ("D", "C")
# and the "NOT TO SCALE" note are TEXT, so they sit outside the drawing's own
# bounding box — without generous padding above, the crop decapitates them.
PAD_TOP_PT = 13.0
PAD_BOTTOM_PT = 8.0
# Fixed padding is not enough on its own: a graph's axis labels sit further out
# than any pad that is safe to apply blindly (the "120" at the top of the y-axis,
# the tick row and the "Time (hours)" title below the x-axis). So the band is
# also GROWN over text that belongs to the figure — see _grow_over_labels.
LABEL_GAP_PT = 18.0       # how far outside the band a label may still sit
LABEL_SIDE_PT = 45.0      # how far outside the drawing's x-span a label may sit
LABEL_MAX_WORDS = 8       # more words than this is prose, unless all numeric
# Body text and sub-part labels start at the left edge of the content column;
# a centred figure's labels never do.
PROSE_LEFT_PT = 24.0
# A horizontal text row is never taller than this; anything taller is rotated
# margin furniture (see _text_rows).
MAX_TEXT_ROW_PT = 40.0
# "(c)", "(ii)" — a sub-part label, never a figure label.
_SUBPART_LABEL_RE = re.compile(r"\(\s*[a-z]{1,4}\s*\)")
# Lower-case function words: a caption reads like a sentence, a label does not.
_PROSE_WORDS = {"a", "an", "the", "is", "are", "of", "and", "with", "in", "on",
                "for", "to", "by", "this", "that", "each", "from", "at", "as",
                "it", "its", "has", "have", "shows", "show", "made", "when"}
# A tick number: "0", "-2", "12.5", "10,5".
_NUMERIC_TOKEN_RE = re.compile(r"[-‐-−]?\d+(?:[.,]\d+)?")
# Shorter than this is a rule or a stray box, not a diagram worth printing.
MIN_BAND_PT = 24.0
# Taller than this fraction of the page is page furniture, not a figure.
MAX_BAND_FRACTION = 0.60
# Vertical gap at which two primitives still belong to the same figure.
CLUSTER_GAP_PT = 30.0
# Minimum horizontal overlap with the content column for a primitive to count.
MIN_CONTENT_OVERLAP_PT = 20.0


def _in_content_column(x0: float, x1: float) -> bool:
    overlap = min(x1, CONTENT_X1) - max(x0, CONTENT_X0)
    return overlap >= MIN_CONTENT_OVERLAP_PT


def _primitives(page, y0: float, y1: float) -> list[tuple[float, float, float, float]]:
    """(y0, y1, x0, x1) of every drawing/raster on the page that could be a figure."""
    spans: list[tuple[float, float, float, float]] = []
    page_h = page.rect.height
    content_w = CONTENT_X1 - CONTENT_X0

    for info in page.get_image_info():
        bb = info.get("bbox")
        if not bb:
            continue
        if bb[3] < y0 or bb[1] > y1:
            continue
        if not _in_content_column(bb[0], bb[2]):
            continue
        if (bb[3] - bb[1]) > 20 and (bb[2] - bb[0]) > 40:
            spans.append((max(bb[1], y0), min(bb[3], y1), bb[0], bb[2]))

    for d in page.get_drawings():
        r = d["rect"]
        if r.y1 < y0 or r.y0 > y1:
            continue
        if r.width < 8 or r.height < 8:
            continue                                   # hairline / tick
        if not _in_content_column(r.x0, r.x1):
            continue                                   # margin furniture
        if r.height > MAX_BAND_FRACTION * page_h:
            continue                                   # page-edge bar
        if r.width > 0.98 * content_w and r.height < 6:
            continue                                   # full-width rule
        spans.append((max(r.y0, y0), min(r.y1, y1), r.x0, r.x1))
    return spans


def _cluster(spans, page_h: float) -> list[tuple[float, float, float, float]]:
    """Group vertically-adjacent spans into figure bands, tracking x extent too."""
    if not spans:
        return []
    spans = sorted(spans)
    bands: list[list[float]] = [list(spans[0])]
    for a, b, x0, x1 in spans[1:]:
        if a <= bands[-1][1] + CLUSTER_GAP_PT:
            bands[-1][1] = max(bands[-1][1], b)
            bands[-1][2] = min(bands[-1][2], x0)
            bands[-1][3] = max(bands[-1][3], x1)
        else:
            bands.append([a, b, x0, x1])
    return [tuple(band) for band in bands
            if MIN_BAND_PT <= band[1] - band[0] <= MAX_BAND_FRACTION * page_h]


def _text_rows(page, y0: float, y1: float) -> list[tuple[float, float, float, float, str]]:
    """(y0, y1, x0, x1, text) per logical text ROW inside the region.

    PyMuPDF reports a "line" per run, so one sentence of a Cambridge paper comes
    back as a dozen fragments ("AB", "=", "10 4", " cm and "). Each fragment is
    short and sits inside a diagram's x-span, so tested individually every one of
    them looks like a figure label. Rows sharing a baseline are merged first, and
    the label tests below then see the sentence they are meant to reject.
    """
    frags: list[list] = []
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            lx0, ly0, lx1, ly1 = line["bbox"]
            if ly1 <= y0 or ly0 >= y1:
                continue
            # Cambridge prints "DO NOT WRITE IN THIS MARGIN" rotated down the
            # full height of the page. It is a text line whose bbox covers the
            # whole page, so left in it would swallow every real row and defeat
            # both label tests. Horizontal text is never this tall.
            if ly1 - ly0 > MAX_TEXT_ROW_PT:
                continue
            text = "".join(span["text"] for span in line["spans"])
            if not text.strip():
                continue
            frags.append([ly0, ly1, lx0, lx1, text])

    rows: list[list] = []
    for ly0, ly1, lx0, lx1, text in sorted(frags):
        for row in rows:
            # Same row when the vertical spans mostly coincide. Measured against
            # the TALLER of the two: a short fragment sitting inside a taller
            # one's span is a different row (a super/subscript, a stacked label),
            # not part of it.
            overlap = min(ly1, row[1]) - max(ly0, row[0])
            if overlap > 0.55 * max(ly1 - ly0, row[1] - row[0]):
                row[0], row[1] = min(row[0], ly0), max(row[1], ly1)
                row[2], row[3] = min(row[2], lx0), max(row[3], lx1)
                row[4] += " " + text
                break
        else:
            rows.append([ly0, ly1, lx0, lx1, text])
    return [tuple(r) for r in rows]


def _top_after_labels(page, top: float, drawing_top: float,
                      band_x0: float, band_x1: float) -> float:
    """Pull the crop's top edge below any text that is not part of the figure.

    The top padding exists to catch point labels ("D", "C") printed just above a
    drawing — but it also catches the source paper's own question number, which
    then appears as a stray "2" in the corner of the crop, and the tail of the
    prose line above. Anything in the padding strip that is not a figure label
    (see ``_is_figure_label``) puts the crop's top edge below itself.
    """
    limit = top
    for ly0, ly1, lx0, lx1, text in _text_rows(page, top, drawing_top):
        if ly1 <= top or ly0 >= drawing_top:
            continue
        if not _is_figure_label(text, lx0, lx1, band_x0, band_x1):
            limit = max(limit, ly1 + 1.0)
    return min(limit, drawing_top)


def _is_figure_label(text: str, lx0: float, lx1: float,
                     bx0: float, bx1: float) -> bool:
    """Is this text line part of the figure rather than the prose around it?

    A figure's labels sit inside (or barely outside) the drawing's own horizontal
    span and are either very short ("NOT TO SCALE", "Time (hours)", "Solid A") or
    pure numbers (an axis's tick row). Anything else is prose — which is what
    separates "0 2 4 6 8 10" under an axis both from "The cumulative frequency
    diagram shows this information." above one and from the caption
    "The diagram shows a cuboid, ABCDEFGH." printed under one.
    """
    words = text.split()
    if not words:
        return False
    if lx0 <= CONTENT_X0 + PROSE_LEFT_PT:
        return False                                   # prose / "(a)" column
    if _SUBPART_LABEL_RE.match(text.strip()):
        return False               # "(c)", "(ii)" — alone, or merged with
                                   # a figure label sharing its baseline
    if lx0 < bx0 - LABEL_SIDE_PT or lx1 > bx1 + LABEL_SIDE_PT:
        return False                                   # outside the figure
    if all(_NUMERIC_TOKEN_RE.fullmatch(w) for w in words):
        return True                                    # an axis tick row
    if len(words) > LABEL_MAX_WORDS:
        return False
    # A caption is a sentence and reads like one; a label is a noun phrase.
    # Tested lower-case-only so "NOT TO SCALE" keeps its "TO".
    return not any(w.strip(".,;:()").lower() in _PROSE_WORDS and w[:1].islower()
                   for w in words)


def _grow_over_labels(page, y0: float, y1: float,
                      band: tuple[float, float, float, float]) -> tuple[float, float]:
    """Extend a drawing band over the figure's own labels, above and below.

    Without this the crop is cut to the geometry: a cumulative-frequency graph
    loses the "120" at the top of its axis, the tick numbers along the bottom and
    the axis title under them, because all of those are text sitting outside the
    drawing's bounding box by more than any blind padding could safely cover.
    """
    top, bottom, bx0, bx1 = band
    lines = [(ly0, ly1) for ly0, ly1, lx0, lx1, text in _text_rows(page, y0, y1)
             if _is_figure_label(text, lx0, lx1, bx0, bx1)]

    changed = True
    while changed:                       # a label may sit under another label
        changed = False
        for ly0, ly1 in lines:
            # A label above the band, or straddling its edge (an axis's topmost
            # tick number is centred ON the top gridline, so half of it is out).
            # The gap is measured to the label's near edge, so a tall label is
            # not rejected for the space its own height occupies.
            if ly0 < top and ly1 >= top - LABEL_GAP_PT and ly0 >= y0:
                top, changed = ly0, True
            elif ly1 > bottom and ly0 <= bottom + LABEL_GAP_PT and ly1 <= y1:
                bottom, changed = ly1, True
    return top, bottom


def _figure_bands(doc, regions) -> list[tuple[int, float, float, float, float]]:
    """(page, crop_y0, crop_y1, core_y0, core_y1) for every figure band.

    The crop is the band grown over the figure's labels and padded; the *core* is
    the drawing's own extent. Ownership (which sub-part a figure belongs to) is
    decided from the core, so growing a crop to keep an axis title can never move
    a figure from the question stem into the sub-part printed underneath it.
    """
    bands: list[tuple[int, float, float, float, float]] = []
    for (pi, y0, y1) in regions:
        page = doc[pi]
        for a, b, bx0, bx1 in _cluster(_primitives(page, y0, y1), page.rect.height):
            grown_top, grown_bottom = _grow_over_labels(page, y0, y1, (a, b, bx0, bx1))
            top = _top_after_labels(page, max(grown_top - PAD_TOP_PT, y0),
                                    grown_top, bx0, bx1)
            bands.append((pi, top, min(grown_bottom + PAD_BOTTOM_PT, y1), a, b))
    return bands


def _stem_regions(q_regions, leaves, containers=()) -> list[tuple[int, float, float]]:
    """The part of a question that sits ABOVE its first sub-part label.

    That band holds the shared stem ("Amira goes fishing...", a table, a figure)
    that every sub-part depends on. ``build_leaves`` deliberately excludes it —
    it belongs to no leaf — which is exactly why it was missing from the
    extraction until now.

    Containers count as boundaries too: a question whose first label is "(a)" and
    whose (a) carries its own introduction has that introduction captured as a
    *group* stem, so the question stem must stop above it rather than swallow it
    and print the same text twice.
    """
    first = None
    for node in list(leaves) + list(containers):
        for region in node.get("regions") or []:
            if first is None or (region[0], region[1]) < (first[0], first[1]):
                first = region
    if first is None:
        return []
    out: list[tuple[int, float, float]] = []
    for (pi, y0, y1) in q_regions:
        if pi < first[0]:
            out.append((pi, y0, y1))
        elif pi == first[0] and y0 < first[1]:
            out.append((pi, y0, min(y1, first[1])))
    return [r for r in out if r[2] - r[1] > 6]


def process_paper(paper: dict, write_images: bool) -> tuple[dict, dict, dict, dict]:
    qp_path = paper["qp"]
    if not os.path.exists(qp_path):
        return {}, {}, {}, {}
    doc = fitz.open(qp_path)
    anchors = question_anchors(doc)
    parts: dict[str, dict] = {}
    shared: dict[str, dict] = {}
    stems: dict[str, dict] = {}
    group_stems: dict[str, dict] = {}

    def _render(bands, out_id, directory=FIG_IMG_DIR) -> list[int] | None:
        images = [render_region(doc[b[0]], b[1], b[2]) for b in bands]
        images = [im for im in images if im is not None]
        if not images:
            return None
        im = images[0] if len(images) == 1 else stitch(images)
        os.makedirs(directory, exist_ok=True)
        im.save(os.path.join(directory, out_id + ".png"), optimize=True)
        return [im.width, im.height]

    def _render_stem(_doc, regions, out_id) -> list[int] | None:
        return _render(regions, out_id, STEM_IMG_DIR)

    for i, (_p, _y, qn) in enumerate(anchors):
        q_regions = question_regions(doc, anchors, i)
        qid = f"{paper['code']}_Q{qn}"
        leaves, containers = build_leaves(doc, q_regions)
        bands = _figure_bands(doc, q_regions)

        # A letter part that has roman children can carry its own introduction
        # ("(b) Matilda records the distances that 80 different cars ..."). That
        # text belongs to no leaf either, so it needs the same treatment as the
        # question stem or it silently disappears from the generated paper.
        group_regions: dict[str, list] = {}
        for container in containers:
            regions = [r for r in (container.get("regions") or []) if r[2] - r[1] > 8]
            if not regions:
                continue
            gid = qid + "_" + "_".join(container["path"])
            text = region_text(doc, regions).strip()
            entry = {"assetId": gid, "questionId": qid, "path": container["path"],
                     "text": text,
                     "usedByParts": [qid + "_" + "_".join(p)
                                     for p in container.get("child_paths") or []],
                     "imageUrl": f"/question_stems/{gid}.png",
                     "regions": [[r[0], round(r[1], 1), round(r[2], 1)] for r in regions]}
            if write_images:
                px = _render_stem(doc, regions, gid)
                if px:
                    entry["px"] = px
            group_stems[gid] = entry
            group_regions[gid] = regions

        stem_regions = _stem_regions(q_regions, leaves, containers)
        if stem_regions:
            text = region_text(doc, stem_regions).strip()
            entry = {"questionId": qid, "text": text,
                     "imageUrl": f"/question_stems/{qid}.png",
                     "regions": [[r[0], round(r[1], 1), round(r[2], 1)]
                                 for r in stem_regions]}
            if write_images and (text or bands):
                px = _render_stem(doc, stem_regions, qid)
                if px:
                    entry["px"] = px
            if text or bands:
                stems[qid] = entry

        for fi, band in enumerate(bands):
            core = (band[0], band[3], band[4])   # the drawing itself, not the crop
            hits = [leaf for leaf in leaves if _overlaps_leaf(core, leaf)]
            if not hits:
                # A figure inside a letter part's own introduction belongs to
                # that group, not to the question stem.
                owner = next((gid for gid, regions in group_regions.items()
                              if _overlaps_leaf(core, {"regions": regions})), "")
                if owner:
                    fig_id = f"{owner}_fig{fi + 1}"
                    entry = {"assetId": fig_id, "questionId": qid,
                             "imageUrl": f"/question_figures/{fig_id}.png",
                             "band": [band[0], round(band[1], 1), round(band[2], 1)]}
                    if write_images:
                        px = _render([band], fig_id)
                        if px is None:
                            continue
                        entry["px"] = px
                    group_stems[owner].setdefault("figure", entry)
                    continue
                # Above the first "(a)" label: this figure belongs to the
                # question stem, which every sub-part reads from.
                out_id = f"{qid}_stemfig{fi + 1}"
                entry = {"assetId": out_id, "questionId": qid,
                         "imageUrl": f"/question_figures/{out_id}.png",
                         "band": [band[0], round(band[1], 1), round(band[2], 1)]}
                if write_images:
                    px = _render([band], out_id)
                    if px is None:
                        continue
                    entry["px"] = px
                stems.setdefault(qid, {"questionId": qid, "text": "", "regions": []})
                stems[qid].setdefault("figure", entry)
                continue
            if len(hits) == 1:
                out_id = qid + "_" + "_".join(hits[0]["path"])
                entry = {"partId": out_id,
                         "imageUrl": f"/question_figures/{out_id}.png",
                         "band": [band[0], round(band[1], 1), round(band[2], 1)]}
                if write_images:
                    px = _render([band], out_id)
                    if px is None:
                        continue
                    entry["px"] = px
                parts[out_id] = entry
            else:
                out_id = f"{qid}_sharedfig{fi + 1}"
                entry = {"assetId": out_id,
                         "imageUrl": f"/question_figures/{out_id}.png",
                         "usedByParts": [qid + "_" + "_".join(h["path"]) for h in hits],
                         "band": [band[0], round(band[1], 1), round(band[2], 1)]}
                if write_images:
                    px = _render([band], out_id)
                    if px is None:
                        continue
                    entry["px"] = px
                shared[out_id] = entry

    doc.close()
    return parts, shared, stems, group_stems


def _referenced_figure_ids(data: dict) -> set[str]:
    """Every figure asset id the manifest still points at."""
    ids = set(data.get("parts") or {}) | set(data.get("shared") or {})
    for group in ("stems", "groupStems"):
        for entry in (data.get(group) or {}).values():
            figure = entry.get("figure")
            if figure and figure.get("assetId"):
                ids.add(figure["assetId"])
    return ids


def _prune_stale_images(data: dict, codes: list[str]) -> list[str]:
    """Delete crops a rebuild has orphaned.

    A band that moves can change a figure's id — a stem figure becoming a
    sub-part figure, a sub-part figure becoming a shared one. The manifest is
    rewritten, but the old PNG stays on disk, and ``assemble.figure_path`` looks
    crops up BY ID: the stale file is found and printed, so a question can end up
    showing the previous run's crop next to the current one. Rebuilding a paper
    therefore removes that paper's unreferenced crops.
    """
    if not os.path.isdir(FIG_IMG_DIR):
        return []
    keep = _referenced_figure_ids(data)
    removed = []
    for name in os.listdir(FIG_IMG_DIR):
        stem, ext = os.path.splitext(name)
        if ext.lower() != ".png" or stem in keep:
            continue
        if codes and not any(stem.startswith(code + "_Q") for code in codes):
            continue                      # another paper's crop, not this run's
        os.remove(os.path.join(FIG_IMG_DIR, name))
        removed.append(stem)
    return removed


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    only = None
    if "--paper" in sys.argv:
        only = sys.argv[sys.argv.index("--paper") + 1]
    write_images = "--no-images" not in sys.argv

    os.makedirs(OUT_DIR, exist_ok=True)
    inv = _load_inventory()
    if only:
        inv = [p for p in inv if p["code"] == only]

    data = {"parts": {}, "shared": {}, "stems": {}, "groupStems": {}}
    if only and os.path.exists(OUT_JSON):  # single-paper reruns are additive
        data = json.load(open(OUT_JSON, encoding="utf-8"))
        for key in ("parts", "shared", "stems", "groupStems"):
            data.setdefault(key, {})

    missing = []
    for paper in inv:
        if not os.path.exists(paper["qp"]):
            missing.append(paper["code"])
            continue
        parts, shared, stems, groups = process_paper(paper, write_images)
        data["parts"].update(parts)
        data["shared"].update(shared)
        data["stems"].update(stems)
        data["groupStems"].update(groups)
        print(f"  {paper['code']}: {len(parts)} sub-part, {len(shared)} shared, "
              f"{len(stems)} stem, {len(groups)} group-stem")

    if write_images:
        stale = _prune_stale_images(data, [p["code"] for p in inv])
        if stale:
            print(f"  pruned {len(stale)} stale crop(s): {', '.join(stale)}")

    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)

    print(f"\nsub-part figures: {len(data['parts'])}   shared: {len(data['shared'])}   "
          f"stem: {len(data['stems'])}")
    if missing:
        print("missing source PDFs:", ", ".join(missing))
    print("->", os.path.relpath(OUT_JSON))
    if write_images:
        print("->", os.path.relpath(FIG_IMG_DIR))


if __name__ == "__main__":
    main()
