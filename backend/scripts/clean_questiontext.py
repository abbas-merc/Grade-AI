"""
clean_questiontext.py — Propose cleaned questionText by removing the diagram-
label fragments that the extracted figure now shows (so they aren't duplicated
as messy text above the image).

Why this is safe (vs blind pattern-stripping): we only strip a line when the
SAME text physically lives inside that question's figure bounding box in the
source PDF. Mangled-math prose (e.g. "2 0 5 . - . 1"), real number rows (Q10's
"1 8 27 64"), and un-imaged figure labels are NOT inside a figure box for an
image question, so they are never touched. Cleaning runs ONLY for the 31
questions that actually have an extracted image to replace the labels.

Outputs (no Firestore writes):
  diagram_out/cleantext_before_after.txt   human review: per-question diff
  diagram_out/cleantext_proposed.json      {id: cleaned questionText} for apply step

Run from backend/:  python scripts/clean_questiontext.py
"""
from __future__ import annotations

import json
import os
import re
import sys

import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "diagram_out")
DOWNLOADS = os.path.expanduser(r"~/Downloads")

PAPER_PDF = {
    "0580/42/M/J/21": "0580_s21_qp_42.pdf",
    "0580/42/M/J/22": "0580_s22_qp_42.pdf",
    "0580/42/M/J/23": "0580_s23_qp_42.pdf",
    "0580/42/O/N/22": "0580_w22_qp_42.pdf",
    "0580/42/O/N/23": "0580_w23_qp_42.pdf",
}

# "NOT TO SCALE" is never prose — always a diagram annotation — so for an image
# question it is always safe to drop, in any split form.
_NTS_TOKENS = {"NOT", "TO", "SCALE"}
# A lowercase word of >=3 letters marks real prose ("The", "diagram" → keep the
# line). Units (cm, m, kg) are <=2 letters so they don't trip this guard.
_PROSE_RE = re.compile(r"[a-z]{3,}")
_WS_RE = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS_RE.sub(" ", s).strip()


def _figure_label_sets(manifest_entry: dict):
    """Return (label_lines, label_tokens) for a question's figure region(s):
    the exact text the image displays, taken from inside each figure box."""
    pdf = os.path.join(DOWNLOADS, PAPER_PDF[manifest_entry["paperCode"]])
    doc = fitz.open(pdf)
    lines: set[str] = set()
    tokens: set[str] = set()
    for page_1based, box in zip(manifest_entry["pages"], manifest_entry["boxes"]):
        page = doc[page_1based - 1]
        text = page.get_text("text", clip=fitz.Rect(*box))
        for raw in text.split("\n"):
            ln = _norm(raw)
            if not ln:
                continue
            lines.add(ln)
            for tok in ln.split(" "):
                tokens.add(tok)
                tokens.add(tok.rstrip("°"))  # tolerate "57" vs "57°" split
    doc.close()
    return lines, tokens


def _is_label_line(line: str, label_lines: set[str], label_tokens: set[str]) -> bool:
    """True if a questionText line is purely diagram-label text the image shows."""
    norm = _norm(line)
    if not norm:
        return False
    # Keep anything that reads as prose, carries a mark/answer slot, or is a
    # sub-part marker — these are never "just a label".
    if _PROSE_RE.search(norm):
        return False
    if "[" in norm or "...." in norm or "=" in norm:
        return False
    if re.match(r"^\([a-z]{1,4}\)", norm):  # (a) (i) ...
        return False
    if norm in label_lines:
        return True
    toks = norm.split(" ")
    # Every token must be shown in the figure (or be a NOT TO SCALE token).
    return all((t in label_tokens) or (t.rstrip("°") in label_tokens) or (t in _NTS_TOKENS)
               for t in toks)


def _clean(text: str, label_lines: set[str], label_tokens: set[str]):
    kept, removed = [], []
    for raw in text.split("\n"):
        if _is_label_line(raw, label_lines, label_tokens):
            removed.append(raw.rstrip())
        else:
            kept.append(raw.rstrip())
    # Collapse 3+ blank lines to one; trim leading/trailing blanks.
    out: list[str] = []
    for ln in kept:
        if not ln.strip() and (not out or not out[-1].strip()):
            continue
        out.append(ln)
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out), removed


def main() -> None:
    manifest = {m["questionId"]: m for m in
                json.load(open(os.path.join(OUT, "_manifest.json"), encoding="utf-8"))
                if m["status"] == "OK"}
    rows = json.load(open(os.path.join(OUT, "questions_dump.json"), encoding="utf-8"))

    proposed: dict[str, str] = {}
    changed, unchanged = [], []
    report_lines: list[str] = []

    for r in rows:
        qid, before = r["id"], r["questionText"]
        if qid in manifest:
            labels = _figure_label_sets(manifest[qid])
            after, removed = _clean(before, *labels)
        else:
            after, removed = before, []
        if after != before:
            changed.append((qid, r, before, after, removed))
            proposed[qid] = after
        else:
            unchanged.append((qid, r))

    # Human-review report.
    report_lines.append(f"CHANGED: {len(changed)}   UNCHANGED: {len(unchanged)}\n")
    report_lines.append("=== UNCHANGED (no figure-label text removed) ===")
    for qid, r in unchanged:
        tag = "image" if r["hasImage"] else "text-only"
        report_lines.append(f"  {qid:<28} {r['paperCode']} Q{r['qNo']:<2} [{tag}]")
    report_lines.append("")
    for qid, r, before, after, removed in changed:
        report_lines.append("=" * 92)
        report_lines.append(f"{qid}  | {r['paperCode']} Q{r['qNo']} | {r['topic']} | "
                            f"removed {len(removed)} line(s)")
        report_lines.append("-" * 92)
        report_lines.append("REMOVED LINES:")
        for ln in removed:
            report_lines.append(f"   - {ln!r}")
        report_lines.append("\nAFTER (cleaned questionText):")
        for ln in after.split("\n"):
            report_lines.append(f"   | {ln}")
        report_lines.append("")

    with open(os.path.join(OUT, "cleantext_before_after.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    with open(os.path.join(OUT, "cleantext_proposed.json"), "w", encoding="utf-8") as f:
        json.dump(proposed, f, indent=2, ensure_ascii=False)

    print(f"CHANGED: {len(changed)}   UNCHANGED: {len(unchanged)}")
    print(f"Review: {os.path.join(OUT, 'cleantext_before_after.txt')}")
    print(f"Proposed: {os.path.join(OUT, 'cleantext_proposed.json')}")
    print("\nChanged questions:")
    for qid, r, before, after, removed in changed:
        print(f"  {qid:<28} removed {len(removed):>2} line(s)")


if __name__ == "__main__":
    main()
