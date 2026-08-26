"""
build_part_extraction.py — Part 2: per-sub-part extraction.

Turns each whole-question crop from the existing bank into a set of SUB-PART
records: structural label tree, per-part marks, per-part mark-scheme + question
text, per-part image crops, and shared-asset (diagram/table) detection with the
dependency data Part 4 needs.

It reuses the PROVEN geometry in build_question_bank.py VERBATIM
(question_anchors / question_regions / render_region / stitch / region_text /
detect_marks / footer_bottom / _content_top / page_is_skippable) so sub-part
crops are spatially consistent with the whole-question crops already shipped.

Sub-part detection (calibrated on real 0580 papers):
  * Top-level parts "(a)".."(h)" print at x0 ~= 72 (left content margin).
  * Nested roman parts "(i)".."(x)" print further indented at x0 ~= 82..100.
  * A question with no such labels is a single leaf = the whole question.
Leaves (the mark-bearing units) are the roman parts when a letter part has them,
else the letter part, else the whole question.

Shared assets (Part 2.2):
  * A figure (vector drawing or raster image) whose vertical span overlaps >= 2
    leaf bands is a SHARED asset, attached to every overlapping leaf.
  * A letter part that has roman children AND carries intro content before its
    first roman (e.g. "The table shows ...") exposes that intro as a shared
    CONTEXT asset for all its roman leaves (they say "the table"/"the diagram").

Nothing is written to Firestore. Outputs:
  scripts/part_extraction/part_manifest.json   (structure + text + refs)
  scripts/question_parts/<partId>.png          (per-part crops; with --images)
  scripts/question_assets/<assetId>.png        (shared-asset crops; with --images)

Run from backend/:
  python scripts/build_part_extraction.py            # structure+text only (fast)
  python scripts/build_part_extraction.py --images   # also render all crops
  python scripts/build_part_extraction.py --paper 0580_s24_qp_42 --images  # one paper
"""
from __future__ import annotations

import json
import os
import re
import sys

import fitz  # PyMuPDF
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_question_bank import (  # noqa: E402
    ANCHOR_TOP_PAD, CONTENT_X0, CONTENT_X1, NEXT_GAP, ZOOM,
    _content_top, detect_marks, footer_bottom, page_is_skippable,
    parse_mark_scheme, question_anchors, question_regions, region_text,
    render_region, stitch,
)

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
PAPERS_DIR = os.path.join(BACKEND, "papers")
DL = os.path.expanduser("~/Downloads")
OUT_DIR = os.path.join(HERE, "part_extraction")
PARTS_IMG_DIR = os.path.join(HERE, "question_parts")
ASSETS_IMG_DIR = os.path.join(HERE, "question_assets")

# --------------------------------------------------------------------------- #
# Unified 24-paper inventory: 4 backfill (source in ~/Downloads) + 20 batch
# (source in backend/papers/). `code` is the id token used in every manifest.
# --------------------------------------------------------------------------- #
_BACKFILL = [
    ("058021_2024", "0580/21/2024", "P2", 2024, False,
     "569924-june-2024-question-paper-21.pdf", "569920-june-2024-mark-scheme-paper-21.pdf", DL),
    ("058041_2024", "0580/41/2024", "P4", 2024, False,
     "671439-june-2024-question-paper-41.pdf", "671437-june-2024-mark-scheme-paper-41.pdf", DL),
    ("0580_2_SP_2025", "0580/02/SP/2025", "P2", 2025, True,
     "663664-2025-specimen-paper-2.pdf", "663672-2025-specimen-paper-2-mark-scheme.pdf", DL),
    ("0580_4_SP_2025", "0580/04/SP/2025", "P4", 2025, True,
     "663668-2025-specimen-paper-4.pdf", "663676-2025-specimen-paper-4-mark-scheme.pdf", DL),
]


def _load_inventory() -> list[dict]:
    from build_batch import INVENTORY as BATCH  # noqa: E402
    inv = []
    for code, paper_code, ptype, year, spec, qp, ms, src in _BACKFILL:
        inv.append({"code": code, "paperCode": paper_code, "paperType": ptype,
                    "year": year, "isSpecimen": spec,
                    "qp": os.path.join(src, qp), "ms": os.path.join(src, ms)})
    for p in BATCH:
        inv.append({"code": p["code"], "paperCode": None, "paperType": p["paperType"],
                    "year": p["year"], "isSpecimen": p["isSpecimen"],
                    "qp": os.path.join(PAPERS_DIR, p["qp"]), "ms": os.path.join(PAPERS_DIR, p["ms"])})
    return inv


# --------------------------------------------------------------------------- #
# Sub-part label detection
# --------------------------------------------------------------------------- #
# Exact standalone label tokens. Letters are [a-h] ONLY (never 'i'), so the
# token itself disambiguates the (i) letter/roman collision — a "(i)" word is
# always a roman. Detection is at WORD level (not line-start) so labels printed
# INLINE are still caught: the question-number line "10 (a) ..." and a shared
# line "(d) (i) ..." both hide labels a line-start regex misses.
_ROMAN = r"(?:i{1,3}|iv|ix|vi{0,3}|v|x)"
_LETTER_TOKEN = re.compile(r"^\(([a-h])\)$")
_ROMAN_TOKEN = re.compile(rf"^\(({_ROMAN})\)$")
# A real label sits in the left half of the content column; this rejects any
# stray "(a)"/"(x)" appearing mid-prose on the right.
LABEL_X_MAX = 140.0
_MARK_RE = re.compile(r"\[(\d{1,2})\]")


def _lines_in_regions(doc, regions):
    """Ordered [(page, y, x0, text)] for every non-empty line inside `regions`."""
    out = []
    for (pi, y0, y1) in regions:
        for block in doc[pi].get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                ly, lx = line["bbox"][1], line["bbox"][0]
                if ly < y0 - 1 or ly > y1 + 1:
                    continue
                txt = "".join(s["text"] for s in line.get("spans", [])).strip()
                if txt:
                    out.append((pi, ly, lx, txt))
    return out


def _label_anchors(doc, regions):
    """Detect [(page, y, level, key, token)] for sub-part labels via word tokens.
    level 0 = top-level letter part, level 1 = nested roman part."""
    anchors = []
    for reg_i, (pi, y0, y1) in enumerate(regions):
        for (wx0, wy0, wx1, wy1, word, *_rest) in doc[pi].get_text("words"):
            if wy0 < y0 - 1 or wy0 > y1 + 1 or wx0 > LABEL_X_MAX:
                continue
            mL = _LETTER_TOKEN.match(word)
            mR = _ROMAN_TOKEN.match(word)
            if mL:
                anchors.append((reg_i, pi, wy0, wx0, 0, mL.group(1), word))
            elif mR:
                anchors.append((reg_i, pi, wy0, wx0, 1, mR.group(1), word))
    # Reading order: region order, then y, then x (so inline "(d) (i)" -> d before i).
    anchors.sort(key=lambda a: (a[0], a[2], a[3]))
    # Drop the region-index/x helper cols now that ordering is fixed.
    return [(pi, y, lvl, key, tok) for (_reg, pi, y, _x, lvl, key, tok) in anchors]


def _slice_regions(regions, start, end):
    """Sub-regions of `regions` between (page,y) start and (page,y) end."""
    out = []
    for (p, ry0, ry1) in regions:
        if p < start[0] or p > end[0]:
            continue
        seg0, seg1 = ry0, ry1
        if p == start[0]:
            seg0 = max(seg0, start[1])
        if p == end[0]:
            seg1 = min(seg1, end[1])
        if seg1 - seg0 > 3:
            out.append((p, seg0, seg1))
    return out


def _region_end(regions):
    p, _, y1 = regions[-1]
    return (p, y1)


def build_leaves(doc, q_regions):
    """Return (leaves, containers).

    leaves: ordered list of dicts {label, path, start, end, regions}.
    containers: letter parts that have roman children, with their shared-context
                region (intro before the first roman), if any.
    A question with no labels -> one leaf spanning the whole question.
    """
    anchors = _label_anchors(doc, q_regions)
    q_end = _region_end(q_regions)

    if not anchors:
        return ([{"label": "", "path": ["_"], "start": (q_regions[0][0], q_regions[0][1]),
                  "end": q_end, "regions": q_regions}], [])

    # Group into a tree: each letter part owns the roman anchors until the next
    # letter. Real part labels form a strict a,b,c,... run; a repeated or
    # out-of-order letter token (e.g. an in-prose "(b)" reference sitting in the
    # left margin band) is dropped so it can't spawn a duplicate leaf.
    letters = []
    expected = "a"
    for a in [x for x in anchors if x[2] == 0]:
        if a[3] == expected:
            letters.append(a)
            expected = chr(ord(expected) + 1)
    leaves, containers = [], []

    def next_anchor_pos(idx_in_anchors):
        if idx_in_anchors + 1 < len(anchors):
            na = anchors[idx_in_anchors + 1]
            return (na[0], na[1])
        return q_end

    # If there are romans but no letters (rare), treat romans as top-level leaves.
    if not letters:
        for i, a in enumerate(anchors):
            start = (a[0], a[1])
            end = next_anchor_pos(i)
            regs = _slice_regions(q_regions, start, end)
            leaves.append({"label": a[4].split(")")[0] + ")", "path": [a[3]],
                           "start": start, "end": end, "regions": regs})
        return (leaves, containers)

    for li, letter in enumerate(letters):
        l_idx = anchors.index(letter)
        # letter part spans until the next LETTER (or question end)
        letter_end = (letters[li + 1][0], letters[li + 1][1]) if li + 1 < len(letters) else q_end
        # roman children = roman anchors after this letter, before next letter
        romans = [a for a in anchors if a[2] == 1 and _pos_le((letter[0], letter[1]), (a[0], a[1]))
                  and _pos_lt((a[0], a[1]), letter_end)]
        # keep only a strict i,ii,iii,... run (drop repeated/stray roman tokens)
        _ROMAN_SEQ = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"]
        _kept, _ri = [], 0
        for a in romans:
            if _ri < len(_ROMAN_SEQ) and a[3] == _ROMAN_SEQ[_ri]:
                _kept.append(a); _ri += 1
        romans = _kept
        if not romans:
            start = (letter[0], letter[1])
            regs = _slice_regions(q_regions, start, letter_end)
            leaves.append({"label": f"({letter[3]})", "path": [letter[3]],
                           "start": start, "end": letter_end, "regions": regs})
        else:
            # intro/context = from letter anchor to first roman
            ctx_start = (letter[0], letter[1])
            ctx_end = (romans[0][0], romans[0][1])
            ctx_regs = _slice_regions(q_regions, ctx_start, ctx_end)
            containers.append({"label": f"({letter[3]})", "path": [letter[3]],
                               "regions": ctx_regs, "child_paths": []})
            for ri, r in enumerate(romans):
                start = (r[0], r[1])
                end = (romans[ri + 1][0], romans[ri + 1][1]) if ri + 1 < len(romans) else letter_end
                regs = _slice_regions(q_regions, start, end)
                path = [letter[3], r[3]]
                containers[-1]["child_paths"].append(path)
                leaves.append({"label": f"({letter[3]})({r[3]})", "path": path,
                               "start": start, "end": end, "regions": regs})
    return (leaves, containers)


def _pos_le(a, b):
    return (a[0], a[1]) <= (b[0], b[1])


def _pos_lt(a, b):
    return (a[0], a[1]) < (b[0], b[1])


# --------------------------------------------------------------------------- #
# Diagram / figure detection (geometry only)
# --------------------------------------------------------------------------- #
def _figures_in_regions(doc, regions):
    """[(page, y_top, y_bottom)] bounding boxes of vector-art clusters + raster
    images inside `regions`. Used to attach shared diagrams to leaves."""
    figs = []
    for (pi, y0, y1) in regions:
        page = doc[pi]
        # raster images
        for info in page.get_image_info():
            bb = info.get("bbox")
            if not bb:
                continue
            ry0, ry1 = bb[1], bb[3]
            if ry1 < y0 or ry0 > y1:
                continue
            if (ry1 - ry0) > 20 and (bb[2] - bb[0]) > 40:
                figs.append((pi, max(ry0, y0), min(ry1, y1)))
        # vector drawings — cluster by proximity into one band
        ys = []
        for d in page.get_drawings():
            r = d["rect"]
            if r.y1 < y0 or r.y0 > y1:
                continue
            if r.width < 8 or r.height < 8:
                continue
            ys.append((r.y0, r.y1))
        if ys:
            ys.sort()
            cy0, cy1 = ys[0]
            for a, b in ys[1:]:
                if a <= cy1 + 30:
                    cy1 = max(cy1, b)
                else:
                    if cy1 - cy0 > 30:
                        figs.append((pi, max(cy0, y0), min(cy1, y1)))
                    cy0, cy1 = a, b
            if cy1 - cy0 > 30:
                figs.append((pi, max(cy0, y0), min(cy1, y1)))
    return figs


def _overlaps_leaf(fig, leaf):
    fp, fy0, fy1 = fig
    for (p, y0, y1) in leaf["regions"]:
        if p == fp and not (fy1 < y0 or fy0 > y1):
            return True
    return False


# --------------------------------------------------------------------------- #
# Per-part mark-scheme text slicing
# --------------------------------------------------------------------------- #
def slice_ms_by_part(ms_text: str, qn: int, leaves) -> dict:
    """Split a question's mark-scheme blob into per-leaf slices by label."""
    if not ms_text.strip():
        return {}
    # Build ordered label patterns for each leaf, e.g. "3(a)(i)" / "3(a)" / "3".
    labels = []
    for leaf in leaves:
        if leaf["path"] == ["_"]:
            labels.append((leaf["path"][0], re.compile(rf"(?m)^\s*{qn}\b")))
        else:
            lab = "".join(f"({p})" for p in leaf["path"])
            pat = re.compile(rf"(?m)^\s*{qn}\s*{re.escape(lab)}")
            labels.append((tuple(leaf["path"]), pat))
    # Find each label's position; slice between consecutive found positions.
    positions = []
    for key, pat in labels:
        m = pat.search(ms_text)
        positions.append((key, m.start() if m else None))
    out = {}
    found = [(k, p) for (k, p) in positions if p is not None]
    for i, (key, pos) in enumerate(positions):
        if pos is None:
            out[key] = ""
            continue
        # end = next found position greater than pos
        later = [p for (_, p) in found if p is not None and p > pos]
        end = min(later) if later else len(ms_text)
        out[key] = ms_text[pos:end].strip()
    return out


def render_leaf_image(doc, leaf) -> Image.Image | None:
    imgs = []
    for (p, y0, y1) in leaf["regions"]:
        if y1 - y0 < 6:
            continue
        imgs.append(render_region(doc[p], y0, y1))
    if not imgs:
        return None
    return stitch(imgs)


# --------------------------------------------------------------------------- #
# Main extraction
# --------------------------------------------------------------------------- #
def process_paper(paper, want_images: bool) -> list[dict]:
    qp_path, ms_path = paper["qp"], paper["ms"]
    if not os.path.exists(qp_path):
        return [{"__missing__": True, "code": paper["code"], "qp": qp_path}]
    doc = fitz.open(qp_path)
    anchors = question_anchors(doc)
    qnums = [a[2] for a in anchors]
    ms_by_q = {}
    if os.path.exists(ms_path):
        ms_by_q, _ = parse_mark_scheme(ms_path, qnums)

    records = []
    for i, (p, y, qn) in enumerate(anchors):
        q_regions = question_regions(doc, anchors, i)
        qid = f"{paper['code']}_Q{qn}"
        leaves, containers = build_leaves(doc, q_regions)
        figs = _figures_in_regions(doc, q_regions)

        # per-leaf marks + text
        leaf_recs = []
        for leaf in leaves:
            qp_txt = region_text(doc, leaf["regions"]) if leaf["regions"] else ""
            marks = detect_marks(qp_txt)
            leaf_recs.append({
                "path": leaf["path"],
                "label": leaf["label"],
                "marks": marks,
                "questionText": qp_txt.strip(),
                "regions": leaf["regions"],
            })

        # shared diagrams: a figure overlapping >= 2 leaves
        shared_assets = []
        for fi, fig in enumerate(figs):
            hits = [leaf for leaf in leaves if _overlaps_leaf(fig, leaf)]
            if len(hits) >= 2:
                shared_assets.append({
                    "assetId": f"{qid}_fig{fi+1}",
                    "kind": "diagram",
                    "usedByPaths": [h["path"] for h in hits],
                    "region": fig,
                })

        # shared context: a letter container's intro used by its roman leaves
        for c in containers:
            if c["regions"] and any(seg[2] - seg[1] > 12 for seg in c["regions"]):
                ctx_txt = region_text(doc, c["regions"]).strip()
                if len(ctx_txt) > 25 or any(_overlaps_leaf(f, {"regions": c["regions"]}) for f in figs):
                    shared_assets.append({
                        "assetId": f"{qid}_ctx_{''.join(c['path'])}",
                        "kind": "context",
                        "usedByPaths": c["child_paths"],
                        "region": (c["regions"][0][0], c["regions"][0][1], c["regions"][-1][2]),
                        "text": ctx_txt[:400],
                    })

        rec = {
            "id": qid,
            "code": paper["code"],
            "paperType": paper["paperType"],
            "originalQuestionNumber": qn,
            "n_leaves": len(leaf_recs),
            "leaf_marks_sum": sum(l["marks"] for l in leaf_recs),
            "subParts": leaf_recs,
            "sharedAssets": shared_assets,
            "markSchemeByPart": {"".join(k) if isinstance(k, tuple) else k: v
                                 for k, v in slice_ms_by_part(ms_by_q.get(qn, ""), qn, leaves).items()},
            "extractionStatus": "extracted",
        }

        if want_images:
            os.makedirs(PARTS_IMG_DIR, exist_ok=True)
            os.makedirs(ASSETS_IMG_DIR, exist_ok=True)
            for lr in leaf_recs:
                leaf = next(x for x in leaves if x["path"] == lr["path"])
                im = render_leaf_image(doc, leaf)
                if im is not None:
                    part_id = qid + "_" + "_".join(lr["path"])
                    png = os.path.join(PARTS_IMG_DIR, part_id + ".png")
                    im.save(png, optimize=True)
                    lr["imageUrl"] = f"/question_parts/{part_id}.png"
                    lr["_img_px"] = f"{im.width}x{im.height}"
            for a in shared_assets:
                fp, fy0, fy1 = a["region"]
                im = render_region(doc[fp], fy0, fy1)
                png = os.path.join(ASSETS_IMG_DIR, a["assetId"] + ".png")
                im.save(png, optimize=True)
                a["imageUrl"] = f"/question_assets/{a['assetId']}.png"

        records.append(rec)
    doc.close()
    return records


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    want_images = "--images" in sys.argv
    only = None
    if "--paper" in sys.argv:
        only = sys.argv[sys.argv.index("--paper") + 1]

    os.makedirs(OUT_DIR, exist_ok=True)
    inv = _load_inventory()
    if only:
        inv = [p for p in inv if p["code"] == only]

    manifest, missing = [], []
    for paper in inv:
        recs = process_paper(paper, want_images)
        if recs and recs[0].get("__missing__"):
            missing.append(recs[0])
            continue
        manifest.extend(recs)

    # Reconcile per-part marks against the authoritative bank total. A question
    # whose leaves don't sum to its bank total has a dropped/merged sub-part and
    # is flagged `partial` for review rather than shipped silently wrong.
    bank = _load_bank_totals()
    partial = []
    for r in manifest:
        bt = bank.get(r["id"])
        r["bankMarks"] = bt
        r["marksReconciled"] = (bt is not None and bt == r["leaf_marks_sum"])
        if bt is not None and not r["marksReconciled"]:
            r["extractionStatus"] = "partial"
            partial.append(r["id"])

    out = os.path.join(OUT_DIR, "part_manifest.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    total_leaves = sum(r["n_leaves"] for r in manifest)
    print(f"papers processed: {len(inv) - len(missing)}   missing source: {len(missing)}")
    for m in missing:
        print(f"   MISSING: {m['code']}  ({m['qp']})")
    print(f"questions: {len(manifest)}   total sub-part leaves: {total_leaves}")
    print(f"questions with >1 leaf: {sum(1 for r in manifest if r['n_leaves'] > 1)}")
    print(f"questions with shared assets: {sum(1 for r in manifest if r['sharedAssets'])}")
    print(f"marks reconciled to bank total: {sum(1 for r in manifest if r['marksReconciled'])}/{len(manifest)}")
    print(f"flagged 'partial' (marks mismatch, needs review): {partial or 'none'}")
    print(f"manifest -> {os.path.relpath(out)}")
    if want_images:
        print(f"part crops -> {os.path.relpath(PARTS_IMG_DIR)}")
        print(f"asset crops -> {os.path.relpath(ASSETS_IMG_DIR)}")


def _load_bank_totals() -> dict:
    """{questionId: bank marks total} from the 81 backfill + 457 batch manifests."""
    import glob
    totals = {}
    files = [os.path.join(HERE, "question_bank_manifest.json")]
    files += glob.glob(os.path.join(HERE, "batch_review", "batch*_manifest.json"))
    for fp in files:
        if os.path.exists(fp):
            for q in json.load(open(fp, encoding="utf-8")):
                totals[q["id"]] = q.get("marks")
    return totals


if __name__ == "__main__":
    main()
