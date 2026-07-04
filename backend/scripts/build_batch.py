"""
build_batch.py — Batched extraction for the 2024/2025 question-bank expansion.

This is a thin driver around the PROVEN pipeline in build_question_bank.py. It
reuses that module's anchor detection, crop/stitch, footer trimming, mark-scheme
parsing, and marks/topic/difficulty inference VERBATIM. The only differences:

  * Input PDFs come from backend/papers/ (not ~/Downloads).
  * paperCode is read AS PRINTED from each question paper's footer.
  * calculatorStatus / classificationReason are added per the agreed rule:
        - 2025 papers  -> auto by official designation (P2 non_calc_safe,
                          P4 calc_required).
        - pre-2025     -> left None ("PENDING"): a per-question reasoning task
                          the operator (AI) fills in after reading the crops +
                          mark-scheme text. NEVER auto-guessed here.
  * Output goes to a PENDING review area (scripts/pending_snippets +
    scripts/batch_review). NOTHING is written to Firestore, and no image is
    copied into backend/static until a batch is explicitly approved.

Run from backend/:  python scripts/build_batch.py <batch_key>
    e.g.            python scripts/build_batch.py batch1
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter

import fitz  # PyMuPDF

# Reuse the proven pipeline unchanged.
from build_question_bank import (  # noqa: E402
    build_montage,
    detect_difficulty,
    detect_marks,
    detect_topic,
    looks_cut_off,
    parse_mark_scheme,
    question_anchors,
    question_regions,
    region_text,
    render_region,
    stitch,
)

HERE = os.path.dirname(os.path.abspath(__file__))
PAPERS_DIR = os.path.join(os.path.dirname(HERE), "papers")
PENDING_SNIP_DIR = os.path.join(HERE, "pending_snippets")
REVIEW_DIR = os.path.join(HERE, "batch_review")

# Feb/March = m, May/June = s, Oct/Nov = w.
_SESSION_META = {
    "m": ("Feb/March", "F/M"),
    "s": ("May/June", "M/J"),
    "w": ("Oct/Nov", "O/N"),
}

# --------------------------------------------------------------------------- #
# Full 20-paper inventory. `qp`/`ms` are explicit filenames (so the oddly-named
# s25 P2 v22 scheme maps correctly). `batch` follows the approved plan.
# code: collision-free doc-id/image token  0580{variant}_{session}{yy}.
# --------------------------------------------------------------------------- #
def _p(session_letter, year, variant, qp, ms, batch):
    session_name, _ = _SESSION_META[session_letter]
    yy = str(year)[2:]
    paper_num = int(str(variant)[0])  # 2 -> P2, 4 -> P4
    return {
        "code": f"0580{variant}_{session_letter}{yy}",
        "paperType": f"P{paper_num}",
        "variant": str(variant),
        "session": session_name,
        "sessionLetter": session_letter,
        "year": year,
        "isSpecimen": False,
        "name": f"IGCSE Math 0580 Paper {paper_num} v{str(variant)[1]} {session_name} {year}",
        "qp": qp,
        "ms": ms,
        "batch": batch,
    }


INVENTORY = [
    # Batch 1 — 2024 pilot (manual classification checkpoint)
    _p("m", 2024, "22", "0580_m24_qp_22.pdf", "0580_m24_ms_22.pdf", "batch1"),
    _p("m", 2024, "42", "0580_m24_qp_42.pdf", "0580_m24_ms_42.pdf", "batch1"),
    # Batch 2 — rest of 2024
    _p("s", 2024, "22", "0580_s24_qp_22.pdf", "0580_s24_ms_22.pdf", "batch2"),
    _p("s", 2024, "23", "0580_s24_qp_23.pdf", "0580_s24_ms_23.pdf", "batch2"),
    _p("s", 2024, "42", "0580_s24_qp_42.pdf", "0580_s24_ms_42.pdf", "batch2"),
    _p("s", 2024, "43", "0580_s24_qp_43.pdf", "0580_s24_ms_43.pdf", "batch2"),
    # Batch 3 — 2025 non-calc P2 (designation-trusted)
    _p("m", 2025, "22", "0580_m25_qp_22.pdf", "0580_m25_ms_22.pdf", "batch3"),
    _p("s", 2025, "21", "0580_s25_qp_21.pdf", "0580_s25_ms_21.pdf", "batch3"),
    _p("s", 2025, "22", "0580_s25_qp_22.pdf", "0580_s25_ms_22 (1).pdf", "batch3"),  # odd MS name
    _p("s", 2025, "23", "0580_s25_qp_23.pdf", "0580_s25_ms_23.pdf", "batch3"),
    _p("w", 2025, "21", "0580_w25_qp_21.pdf", "0580_w25_ms_21.pdf", "batch3"),
    _p("w", 2025, "22", "0580_w25_qp_22.pdf", "0580_w25_ms_22.pdf", "batch3"),
    _p("w", 2025, "23", "0580_w25_qp_23.pdf", "0580_w25_ms_23.pdf", "batch3"),
    # Batch 4 — 2025 calc P4 (designation-trusted)
    _p("m", 2025, "42", "0580_m25_qp_42.pdf", "0580_m25_ms_42.pdf", "batch4"),
    _p("s", 2025, "41", "0580_s25_qp_41.pdf", "0580_s25_ms_41.pdf", "batch4"),
    _p("s", 2025, "42", "0580_s25_qp_42.pdf", "0580_s25_ms_42.pdf", "batch4"),
    _p("s", 2025, "43", "0580_s25_qp_43.pdf", "0580_s25_ms_43.pdf", "batch4"),
    _p("w", 2025, "41", "0580_w25_qp_41.pdf", "0580_w25_ms_41.pdf", "batch4"),
    _p("w", 2025, "42", "0580_w25_qp_42.pdf", "0580_w25_ms_42.pdf", "batch4"),
    _p("w", 2025, "43", "0580_w25_qp_43.pdf", "0580_w25_ms_43.pdf", "batch4"),
]

_CODE_RE = re.compile(r"0580/\d{2}/[A-Z]/[A-Z]/\d{2}")


def printed_paper_code(doc, paper) -> str:
    """The paper code exactly as printed in the footer, e.g. '0580/22/F/M/24'.
    Falls back to a constructed code if the scan finds nothing (flagged)."""
    for pi in range(len(doc)):
        m = _CODE_RE.search(doc[pi].get_text("text") or "")
        if m:
            return m.group(0)
    _, sess_code = _SESSION_META[paper["sessionLetter"]]
    return f"0580/{paper['variant']}/{sess_code}/{str(paper['year'])[2:]}"


def classify_2025(paper) -> tuple[str, str]:
    """Official designation for 2025 papers — no analysis needed."""
    if paper["paperType"] == "P2":
        return "non_calc_safe", "2025 official designation: Paper 2 is a non-calculator paper."
    return "calc_required", "2025 official designation: Paper 4 is a calculator paper."


def process_paper(paper: dict) -> list[dict]:
    qp_path = os.path.join(PAPERS_DIR, paper["qp"])
    ms_path = os.path.join(PAPERS_DIR, paper["ms"])
    for pth in (qp_path, ms_path):
        if not os.path.exists(pth):
            raise FileNotFoundError(pth)

    doc = fitz.open(qp_path)
    anchors = question_anchors(doc)
    qnums = [a[2] for a in anchors]
    seq_ok = qnums == list(range(1, len(anchors) + 1))
    paper_code = printed_paper_code(doc, paper)

    ms_by_q, ms_debug = parse_mark_scheme(ms_path, qnums)

    items: list[dict] = []
    for i, (p, y, qn) in enumerate(anchors):
        regions = question_regions(doc, anchors, i)
        img = stitch([render_region(doc[rp], ry0, ry1) for (rp, ry0, ry1) in regions])
        png = os.path.join(PENDING_SNIP_DIR, f"{paper['code']}_Q{qn}.png")
        img.save(png, optimize=True)

        qp_text = region_text(doc, regions)
        marks = detect_marks(qp_text)
        topic = detect_topic(qp_text)
        difficulty = detect_difficulty(paper["paperType"], marks)
        ms_text = ms_by_q.get(qn, "")

        # calculatorStatus: auto for 2025, PENDING (operator reasoning) for pre-2025.
        if paper["year"] >= 2025:
            calc_status, calc_reason = classify_2025(paper)
        else:
            calc_status, calc_reason = None, "PENDING — manual per-step classification"

        items.append({
            "id": f"{paper['code']}_Q{qn}",
            "subject": "math",
            "paperType": paper["paperType"],
            "paperCode": paper_code,
            "year": paper["year"],
            "isSpecimen": paper["isSpecimen"],
            "originalQuestionNumber": qn,
            "marks": marks,
            "topic": topic,
            "difficulty": difficulty,
            "calculatorStatus": calc_status,
            "classificationReason": calc_reason,
            "markSchemeText": ms_text,
            "questionImageUrl": f"/question_snippets/{paper['code']}_Q{qn}.png",
            # review-only
            "_png": png,
            "_png_size_kb": os.path.getsize(png) // 1024,
            "_img_px": f"{img.width}x{img.height}",
            "n_regions": len(regions),
            "pages": sorted({rp + 1 for (rp, _, _) in regions}),
            "flag_cutoff": looks_cut_off(img),
            "has_ms": bool(ms_text.strip()),
            "ms_len": len(ms_text),
            "qp_text": qp_text,
        })

    doc.close()

    montage = os.path.join(REVIEW_DIR, f"{paper['code']}_montage.png")
    build_montage(paper_code, items, montage)

    ms_missing = [it["originalQuestionNumber"] for it in items if not it["has_ms"]]
    cutoffs = [it["originalQuestionNumber"] for it in items if it["flag_cutoff"]]
    multipage = [it["originalQuestionNumber"] for it in items if it["n_regions"] > 1]
    print(f"\n=== {paper['name']}  [{paper_code}  {paper['paperType']}] ===")
    print(f"  questions: {len(items)}   anchor seq 1..N ok: {seq_ok}")
    print(f"  MS reliable cols: {ms_debug['reliable_columns']}   MS answer pages: {ms_debug['answer_pages']}")
    print(f"  MS top-levels found: {ms_debug['top_levels_found']}")
    print(f"  multi-page (stitched): {multipage}")
    print(f"  MISSING mark scheme: {ms_missing or 'none'}")
    print(f"  possible cut-off: {cutoffs or 'none'}")
    print(f"  montage -> {os.path.relpath(montage)}")
    return items


def main() -> None:
    batch = sys.argv[1] if len(sys.argv) > 1 else "batch1"
    papers = [p for p in INVENTORY if p["batch"] == batch]
    if not papers:
        raise SystemExit(f"No papers for batch {batch!r}")

    os.makedirs(PENDING_SNIP_DIR, exist_ok=True)
    os.makedirs(REVIEW_DIR, exist_ok=True)

    manifest: list[dict] = []
    for paper in papers:
        manifest.extend(process_paper(paper))

    # Machine-readable manifest (keeps qp_text + ms text for classification).
    manifest_path = os.path.join(REVIEW_DIR, f"{batch}_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    # Human-readable per-question dump: QP text + MS text, for classification.
    dump_path = os.path.join(REVIEW_DIR, f"{batch}_questions.txt")
    with open(dump_path, "w", encoding="utf-8") as f:
        for it in manifest:
            f.write("=" * 78 + "\n")
            f.write(f"{it['id']}  |  {it['paperCode']}  {it['paperType']}  "
                    f"Q{it['originalQuestionNumber']}  |  {it['marks']} marks  |  "
                    f"{it['topic']}/{it['difficulty']}\n")
            f.write("-" * 78 + "\n")
            f.write("QUESTION TEXT:\n" + (it["qp_text"].strip() or "[none extracted]") + "\n\n")
            f.write("MARK SCHEME:\n" + (it["markSchemeText"].strip() or "[none extracted]") + "\n\n")

    print("\n" + "=" * 64)
    print(f"BATCH {batch}: {len(manifest)} questions")
    print(f"  by paperType: {dict(Counter(m['paperType'] for m in manifest))}")
    print(f"  by topic: {dict(Counter(m['topic'] for m in manifest))}")
    print(f"  by difficulty: {dict(Counter(m['difficulty'] for m in manifest))}")
    print(f"  by calculatorStatus: {dict(Counter(str(m['calculatorStatus']) for m in manifest))}")
    print(f"  manifest -> {os.path.relpath(manifest_path)}")
    print(f"  question dump -> {os.path.relpath(dump_path)}")
    print(f"  pending snippets -> {os.path.relpath(PENDING_SNIP_DIR)}")


if __name__ == "__main__":
    main()
