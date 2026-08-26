"""
build_syllabus_codes.py — Extract the canonical IGCSE 0580 topic taxonomy from
the official syllabus PDF into scripts/syllabus_codes.json (Part 1.1).

Source of truth: docs/igcse_0580_syllabus_2025-2027.pdf
  (Cambridge IGCSE Mathematics 0580, Version 3, for exams in 2025-2027,
   downloaded from cambridgeinternational.org/Images/662466-2025-2027-syllabus.pdf)

Every syllabus code used anywhere else in the pipeline MUST come from this file.
Codes are NEVER invented — this script only transcribes what the PDF contains.

Output structure (syllabus_codes.json):
  {
    "syllabus": "...", "version": "...", "source_pdf": "...",
    "sections": [
      { "number": 1, "name": "Number",
        "subsections": [
          { "subsection": "1.1", "name": "Types of number",
            "core_code": "C1.1", "extended_code": "E1.1",
            "tier": "both" | "extended_only",
            "extended_only": false,
            "content": "<objectives + notes/examples verbatim>" }
        ] } ],
    "flat_codes": [ {"code":"E1.1","subsection":"1.1","section":1,
                     "section_name":"Number","name":"Types of number",
                     "tier":"extended"} , ... ]
  }

Run from backend/:  python scripts/build_syllabus_codes.py
"""
from __future__ import annotations

import json
import os
import re
import sys

import fitz  # PyMuPDF

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
PDF = os.path.join(REPO, "docs", "igcse_0580_syllabus_2025-2027.pdf")
OUT = os.path.join(HERE, "syllabus_codes.json")

SECTION_NAMES = {
    1: "Number",
    2: "Algebra and graphs",
    3: "Coordinate geometry",
    4: "Geometry",
    5: "Mensuration",
    6: "Trigonometry",
    7: "Transformations and vectors",
    8: "Probability",
    9: "Statistics",
}

CODE_RE = re.compile(r"^([CE])(\d+)\.(\d+)\s*$")
# Noise lines that appear on every content page (headers / footers / column head).
NOISE = re.compile(
    r"^(www\.cambridgeinternational\.org|Back to contents page|"
    r"Cambridge IGCSE Mathematics 0580 syllabus|Notes and examples|"
    r"Core subject content|Extended subject content|\d{1,3})\s*$"
)


def _clean_block(lines: list[str]) -> str:
    out = []
    for l in lines:
        s = l.strip()
        if not s or NOISE.match(s):
            continue
        if s in SECTION_NAMES.values():
            continue
        out.append(s)
    return "\n".join(out).strip()


def parse() -> dict:
    doc = fitz.open(PDF)
    # Subject content lives on pages 11..55 (Core then Extended). Concatenate the
    # raw lines in document order; C-codes precede E-codes in the stream.
    lines: list[str] = []
    for i in range(11, 56):
        lines.extend(doc.load_page(i).get_text().splitlines())

    # Walk the stream: each code anchor opens a block that runs to the next anchor.
    anchors: list[tuple[str, int, str]] = []  # (code, line_index, title)
    for idx, l in enumerate(lines):
        m = CODE_RE.match(l.strip())
        if not m:
            continue
        code = f"{m.group(1)}{m.group(2)}.{m.group(3)}"
        # title = next non-empty line
        title = ""
        for k in range(idx + 1, min(idx + 4, len(lines))):
            if lines[k].strip():
                title = lines[k].strip()
                break
        anchors.append((code, idx, title))

    # Content block per anchor = lines between this anchor's title and the next.
    blocks: dict[str, str] = {}
    titles: dict[str, str] = {}
    for a_i, (code, idx, title) in enumerate(anchors):
        end = anchors[a_i + 1][1] if a_i + 1 < len(anchors) else len(lines)
        body = lines[idx + 1 : end]
        # keep title as name; body (minus the title line) is content
        titles.setdefault(code, title)
        block = _clean_block(body)
        blocks[code] = (blocks.get(code, "") + "\n" + block).strip()

    # Merge into per-subsection records keyed by "<section>.<sub>".
    subs: dict[str, dict] = {}
    for code, title in titles.items():
        tier_letter, sec, sub = code[0], int(code[1]), code.split(".")[1]
        key = f"{sec}.{sub}"
        rec = subs.setdefault(
            key,
            {"subsection": key, "section": sec, "name": None,
             "core_code": None, "extended_code": None, "content": ""},
        )
        # Prefer the Extended title/content as canonical; fall back to Core.
        is_ext_only_placeholder = title.lower().startswith("extended content only")
        if tier_letter == "C":
            rec["core_code"] = code if not is_ext_only_placeholder else None
        else:
            rec["extended_code"] = code
        # name: take a real (non-placeholder) title, preferring Extended's
        if not is_ext_only_placeholder:
            if rec["name"] is None or tier_letter == "E":
                # strip a trailing "(continued)" duplicate
                rec["name"] = re.sub(r"\s*\(continued\)\s*$", "", title).strip()
        # content: prefer Extended block; else Core
        blk = blocks.get(code, "")
        if blk and (tier_letter == "E" or not rec["content"]):
            rec["content"] = blk

    # Finalise tier + assemble sections
    sections = []
    flat = []
    for sec_num in sorted(SECTION_NAMES):
        sec_subs = [v for k, v in subs.items() if v["section"] == sec_num]
        sec_subs.sort(key=lambda r: int(r["subsection"].split(".")[1]))
        out_subs = []
        for r in sec_subs:
            extended_only = r["core_code"] is None
            tier = "extended_only" if extended_only else "both"
            rec = {
                "subsection": r["subsection"],
                "name": r["name"],
                "core_code": r["core_code"],
                "extended_code": r["extended_code"],
                "tier": tier,
                "extended_only": extended_only,
                "content": r["content"],
            }
            out_subs.append(rec)
            # flat lookup: emit the canonical code(s)
            if r["core_code"]:
                flat.append({"code": r["core_code"], "subsection": r["subsection"],
                             "section": sec_num, "section_name": SECTION_NAMES[sec_num],
                             "name": r["name"], "tier": "core"})
            if r["extended_code"]:
                flat.append({"code": r["extended_code"], "subsection": r["subsection"],
                             "section": sec_num, "section_name": SECTION_NAMES[sec_num],
                             "name": r["name"], "tier": "extended"})
        sections.append({"number": sec_num, "name": SECTION_NAMES[sec_num],
                         "subsections": out_subs})

    return {
        "syllabus": "Cambridge IGCSE Mathematics 0580",
        "version": "Version 3 — for exams in 2025, 2026 and 2027",
        "source_pdf": "docs/igcse_0580_syllabus_2025-2027.pdf",
        "source_url": "https://www.cambridgeinternational.org/Images/662466-2025-2027-syllabus.pdf",
        "note": "Canonical topic taxonomy. All pipeline tags must reference these exact codes.",
        "sections": sections,
        "flat_codes": flat,
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    data = parse()
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    n_sub = sum(len(s["subsections"]) for s in data["sections"])
    n_ext_only = sum(1 for s in data["sections"] for x in s["subsections"] if x["extended_only"])
    print(f"Wrote {OUT}")
    print(f"  sections: {len(data['sections'])}")
    print(f"  subsections: {n_sub}  (extended_only: {n_ext_only})")
    print(f"  flat codes: {len(data['flat_codes'])}")
    # sanity: every subsection must have a name and an extended_code
    missing = [x['subsection'] for s in data['sections'] for x in s['subsections']
               if not x['name'] or not x['extended_code']]
    print(f"  subsections missing name/extended_code: {missing}")


if __name__ == "__main__":
    main()
