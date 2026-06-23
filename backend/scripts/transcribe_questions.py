"""
transcribe_questions.py — Re-transcribe each question CLEANLY from the source
PDF using Claude vision, fixing the mangled text-extraction (stray Symbol-font
artefacts like '#', 'G G', 'e o'; shattered equations; 'm2' -> 'm²'; broken
mid-sentence line wraps; dropped [marks]).

Why vision: the figures/maths are vector + Symbol-font encoded, so plain text
extraction is corrupt. Rendering the question region and letting the model READ
the real typography yields clean, faithful text. We pin temperature 0 and
instruct strict fidelity (no solving, no inventing, preserve every number and
[mark]). Nothing is written to Firestore — outputs are for human review.

  --only id1,id2     transcribe just these question ids (for spot-checking)
  --limit N          stop after N questions

Outputs (in diagram_out/):
  transcribed_proposed.json        {id: clean questionText}
  transcribed_before_after.txt     human-review diff

Run from backend/:  venv/Scripts/python.exe scripts/transcribe_questions.py --only math_2021_MJ_058042_Q6,math_2021_MJ_058042_Q3
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys

import fitz
import anthropic
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from scripts.extract_diagrams import PAPERS, _question_anchors  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "diagram_out")
DOWNLOADS = os.path.expanduser(r"~/Downloads")
MODEL = "claude-sonnet-4-6"
RENDER_ZOOM = 2.2

SYSTEM = (
    "You transcribe IGCSE Cambridge Mathematics exam questions from an image "
    "into clean, faithful plain text. You are a transcriber, NOT a solver."
)

RULES_COMMON = (
    "Transcribe ONLY the question shown. Rules:\n"
    "- Reproduce every number, variable, ratio and mark allocation EXACTLY as "
    "printed. Never solve, add, omit, or 'correct' anything.\n"
    "- Use proper Unicode maths: ² ³ for powers/areas/volumes (cm², cm³), × ÷ ≤ "
    "≥ ≠ √ π °, and a/b for fractions. Fix obvious extraction artefacts (stray "
    "'#', 'G', 'e o', 'f p', lone '=' lines) into the correct maths.\n"
    "- Output PLAIN TEXT ONLY. NO Markdown whatsoever: no '**' or '*' for "
    "bold/italic, no '#' headings, no backticks. Write variables plainly (ABCD, "
    "not *ABCD*).\n"
    "- Do NOT include the original top-level question number. Do not begin the "
    "output with a number like '8' or '8 (a)'. Begin with the question's intro "
    "sentence, or its first sub-part label '(a)'.\n"
    "- Write sub-part labels as plain '(a)', '(b)', '(i)', each starting a new line.\n"
    "- End every part with its mark allocation in square brackets, e.g. [3]. Do "
    "NOT drop these.\n"
    "- For answer/working space, write a single short placeholder '.................' "
    "with any unit and the [marks]; do not reproduce long dot runs.\n"
    "- Use single line breaks; do not insert blank lines between every part.\n"
    "- Output ONLY the transcription text. No preamble, no commentary, no code fences."
)

RULES_IMAGE = (
    "\n- This question's diagram is shown to the student SEPARATELY as a figure, "
    "so DO NOT transcribe any text that is part of the diagram (vertex letters, "
    "'NOT TO SCALE', angles/lengths written on the figure, axis numbers). "
    "Transcribe only the prose, equations, tables, answer lines and marks."
)

RULES_TEXT = (
    "\n- If the question includes a diagram, replace it with a single concise "
    "line: '[Diagram: <short description>, with: <list the labelled values, e.g. "
    "AB = 16 m, angle A = 57°>]'. Keep all labelled values so the question stays "
    "solvable. Otherwise transcribe the text only."
)


def _spans(doc):
    """qnum -> (page_idx, y0) start anchor, plus a sorted anchor list."""
    anchors = _question_anchors(doc)
    start = {}
    for (pi, y, qn) in anchors:
        start.setdefault(qn, (pi, y))
    ordered = sorted(set((pi, y) for (pi, y, _qn) in anchors))
    return start, anchors, ordered


def _region_images(doc, qnum, start, anchors):
    """Render the page band(s) the question occupies into PNG bytes list."""
    if qnum not in start:
        return []
    p0, y0 = start[qnum]
    # End = the next anchor strictly after this question's start, in reading order.
    later = sorted((pi, y) for (pi, y, qn) in anchors if (pi, y) > (p0, y0) and qn != qnum)
    if later:
        p1, y1 = later[0]
    else:
        p1, y1 = len(doc) - 1, doc[len(doc) - 1].rect.height
    images = []
    for pi in range(p0, p1 + 1):
        page = doc[pi]
        r = page.rect
        top = y0 - 4 if pi == p0 else r.y0
        bot = y1 + 2 if pi == p1 else r.y1
        band = fitz.Rect(r.x0, max(r.y0, top), r.x1, min(r.y1, bot))
        if band.height < 8:
            continue
        pix = page.get_pixmap(clip=band, matrix=fitz.Matrix(RENDER_ZOOM, RENDER_ZOOM), alpha=False)
        images.append(pix.tobytes("png"))
    return images


def _postprocess(text: str) -> str:
    """Safety net: strip any Markdown emphasis the model still emitted and
    collapse blank-line runs, so output is plain and compact for both renderers."""
    import re
    text = text.replace("**", "").replace("*", "")  # no bold/italic markers
    text = "\n".join(ln.rstrip() for ln in text.split("\n"))
    text = re.sub(r"\n\s*\n+", "\n", text)            # drop blank lines
    return text.strip()


def _transcribe(client, images, has_image):
    rules = RULES_COMMON + (RULES_IMAGE if has_image else RULES_TEXT)
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
               "data": base64.b64encode(im).decode()}} for im in images]
    content.append({"type": "text", "text": rules})
    msg = client.messages.create(
        model=MODEL, max_tokens=1500, temperature=0, system=SYSTEM,
        messages=[{"role": "user", "content": content}],
    )
    return _postprocess(msg.content[0].text.strip())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    only = set(x for x in args.only.split(",") if x)

    rows = json.load(open(os.path.join(OUT, "questions_dump.json"), encoding="utf-8"))
    if only:
        rows = [r for r in rows if r["id"] in only]
    if args.limit:
        rows = rows[: args.limit]

    key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    client = anthropic.Anthropic(api_key=key, max_retries=4, timeout=120.0)

    docs = {code: fitz.open(os.path.join(DOWNLOADS, pdf)) for code, (pdf, _p) in PAPERS.items()}
    spans = {code: _spans(d) for code, d in docs.items()}

    proposed = json.load(open(os.path.join(OUT, "transcribed_proposed.json"), encoding="utf-8")) \
        if os.path.exists(os.path.join(OUT, "transcribed_proposed.json")) else {}
    report = []

    for i, r in enumerate(rows, 1):
        code, qno, qid = r["paperCode"], int(r["qNo"]), r["id"]
        doc = docs[code]
        start, anchors, _ = spans[code]
        imgs = _region_images(doc, qno, start, anchors)
        if not imgs:
            print(f"[{i}/{len(rows)}] {qid}: NO REGION (skipped)")
            continue
        try:
            clean = _transcribe(client, imgs, r["hasImage"])
        except Exception as exc:
            print(f"[{i}/{len(rows)}] {qid}: API ERROR {exc}")
            continue
        proposed[qid] = clean
        print(f"[{i}/{len(rows)}] {qid}: {len(imgs)} img -> {len(clean)} chars")
        report.append((qid, r, clean))

    with open(os.path.join(OUT, "transcribed_proposed.json"), "w", encoding="utf-8") as f:
        json.dump(proposed, f, indent=2, ensure_ascii=False)
    with open(os.path.join(OUT, "transcribed_before_after.txt"), "w", encoding="utf-8") as f:
        for qid, r, clean in report:
            f.write("=" * 92 + f"\n{qid} | {r['paperCode']} Q{r['qNo']} | {r['topic']} | "
                    f"hasImage={r['hasImage']}\n" + "-" * 40 + " BEFORE " + "-" * 40 + "\n")
            for ln in r["questionText"].split("\n"):
                f.write(f"  | {ln}\n")
            f.write("-" * 40 + " AFTER  " + "-" * 40 + "\n")
            for ln in clean.split("\n"):
                f.write(f"  | {ln}\n")
            f.write("\n")
    print(f"\nWrote {len(report)} transcripts -> {os.path.join(OUT,'transcribed_before_after.txt')}")


if __name__ == "__main__":
    main()
