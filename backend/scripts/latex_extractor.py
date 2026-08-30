"""
latex_extractor.py — Vision extraction that emits LaTeX, not plain text.

The marking pipeline's vision step (``agents/vision_extractor.py``) already reads
question images; this is the same idea pointed at the *question bank* instead of
a student's answer, and with a much stricter output contract: every sub-part's
question text comes back as **compilable LaTeX**, so a fraction is
``\\frac{a}{b}`` rather than ``a/b`` and a column vector is a real ``pmatrix``
rather than three lines of PDF-extraction debris.

One API call per question — the model sees every sub-part crop together, which is
what lets it resolve "the diagram above", carry a stem into part (b), and keep
notation consistent across the whole question. The same call also converts that
question's mark scheme, because the mark scheme has exactly the same maths
notation problem and re-sending the images for it would double the cost.

Output is constrained by a JSON schema (``output_config.format``) so parsing
cannot drift, and every fragment is passed through
``utils.latex.latexify.sanitize_fragment`` before it is returned.

It lives under ``scripts/`` rather than ``agents/`` because, like
``tag_subparts.py``, it is an offline bank-building tool: it runs once over the
question bank at build time and is not part of a student's grading session, so
the per-session API-call and cost limits in ``agents/CLAUDE.md`` do not govern it.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import sys
from typing import Any

import anthropic
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.latex.latexify import (  # noqa: E402
    ensure_math_wrapped, latex_from_raw_text, sanitize_fragment, validate_fragment,
)

__all__ = ["MODEL", "extract_question_latex", "latex_from_raw_text"]

load_dotenv()

MODEL = (os.getenv("GA_LATEX_EXTRACT_MODEL") or "claude-opus-5").strip()
MAX_TOKENS = 16000
# Sub-part crops are rendered at ~200 DPI. Cambridge body text stays comfortably
# legible at half that, and image tokens scale with pixel area, so downscaling
# roughly halves the cost of every call.
MAX_IMAGE_WIDTH_PX = 1000
MAX_IMAGE_HEIGHT_PX = 1400

SYSTEM = r"""You transcribe Cambridge IGCSE Mathematics (0580) exam questions into LaTeX.

You are given the cropped images of each sub-part of ONE question, plus the raw
text layer extracted from the source PDF (which is often mangled — treat the
IMAGE as the truth and the text only as a hint for spelling and numbers).

Return LaTeX that compiles under XeLaTeX with amsmath + unicode-math loaded.

NOTATION RULES — these are the whole point of the task, follow them exactly:
* Fractions: \frac{a}{b} (or \dfrac in display). Never "a/b" and never a
  two-line PDF artefact.
* Surds: \sqrt{x}, \sqrt[3]{x}. Powers/indices: x^{2}, x^{-1}, a_{n}.
* Standard form: 1.5\times10^{-3}  (never "1.5 x 10-3").
* Degrees: 47^\circ. Units: 8.4\,\text{cm}, 44.2\,\text{cm}^{2} — always
  \text{} for units, always a thin space \, before them.
* Column vectors: \begin{pmatrix}3\\-2\end{pmatrix}. Named vectors, exactly as
  the 0580 syllabus prints them: \overrightarrow{AB} or \mathbf{a}. Magnitude:
  \left|\overrightarrow{AB}\right| or |\mathbf{a}|.
* Inequalities: \leqslant \geqslant (Cambridge's slanted forms), \neq.
* Sets: \in \notin \subseteq \cup \cap \emptyset. The universal set prints as
  \mathcal{E}. Set-builder: \{x : 1\leqslant x\leqslant 12\}. Complement: A'.
  Number of elements: \mathrm{n}(A).
* Probability: \mathrm{P}(A), \mathrm{P}(A\cap B).
* Functions: \mathrm{f}(x), \mathrm{g}(x), \mathrm{f}^{-1}(x), \mathrm{fg}(x)
  — upright f/g, as Cambridge prints them. Trig: \sin, \cos, \tan.
* Recurring decimals, ratios (3 : 5), and money keep their normal characters.
* Matrices use pmatrix; simultaneous equations may use \begin{cases}.

STRUCTURE RULES:
* Return ONLY the sub-part's own prose and maths. NEVER include: the question
  number, the "(a)" / "(ii)" label, the answer dotted lines, the "Answer ="
  prompt, or the "[3]" mark indicator. The typesetting template adds all of them.
* Never emit \includegraphics, \begin{document}, \usepackage, \newcommand,
  \input, or any page-break command. If the sub-part contains a diagram, graph,
  table drawing or grid, set hasDiagram=true and simply omit it from the LaTeX —
  the pipeline inserts the extracted image itself.
* A data table that is genuinely tabular MAY use a tabular environment.
* Inline maths uses $...$. Use \[...\] only for a formula the paper genuinely
  displays on its own line.
* Keep the wording verbatim. Do not solve, rephrase, or add instructions.

STEM: if the question has text before its first (a) that all sub-parts depend on,
put it in stemLatex and do NOT repeat it inside the sub-parts.

GROUP INTRODUCTIONS: a letter part such as (b) can carry its own introduction
that only its roman children ((b)(i), (b)(ii), ...) depend on. When one is
supplied below, return it in `groups` keyed by that letter, and do NOT repeat it
inside the roman sub-parts.

MARK SCHEME: convert each sub-part's mark scheme too.
* answerLatex = the final required answer, as LaTeX (short). It must be a
  complete fragment: if it contains any maths at all, wrap it in $...$ yourself
  (write "$3x^{3}-24$", never a bare "3x^{3}-24").
* markPoints = the ordered award lines. code is the Cambridge token exactly as
  printed (M1, A1, B1, M2, B2, SC1, ...) or "" if the line has no code. latex is
  that line's text with its maths converted, again with every maths run inside
  $...$. Keep cao / oe / ft / isw / nfww / dep as literal words.

CONFIDENCE: "high" when the image is clear and every symbol is unambiguous;
"medium" when you inferred a character or the crop is partly cut off; "low" when
you are genuinely unsure what the notation is. Put the reason in notes."""

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "stemLatex": {
            "type": "string",
            "description": "Shared text before the first sub-part; \"\" if none.",
        },
        "groups": {
            "type": "array",
            "description": "One entry per letter-part introduction supplied; [] if none.",
            "items": {
                "type": "object",
                "properties": {
                    "letter": {"type": "string",
                               "description": "the letter alone, e.g. 'b' for part (b)"},
                    "latex": {"type": "string"},
                    "hasDiagram": {"type": "boolean"},
                },
                "required": ["letter", "latex", "hasDiagram"],
                "additionalProperties": False,
            },
        },
        "subParts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string",
                              "description": "the sub-part label exactly as supplied, e.g. '(b)(ii)' or '(whole)'"},
                    "latex": {"type": "string"},
                    "hasDiagram": {"type": "boolean"},
                    "answerLatex": {"type": "string"},
                    "markPoints": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "code": {"type": "string"},
                                "latex": {"type": "string"},
                            },
                            "required": ["code", "latex"],
                            "additionalProperties": False,
                        },
                    },
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "notes": {"type": "string"},
                },
                "required": ["label", "latex", "hasDiagram", "answerLatex",
                             "markPoints", "confidence", "notes"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["stemLatex", "groups", "subParts"],
    "additionalProperties": False,
}


def _encode_image(path: str) -> dict | None:
    """Downscaled base64 image block, or None if the file is unusable."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((MAX_IMAGE_WIDTH_PX, MAX_IMAGE_HEIGHT_PX), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=88, optimize=True)
    except Exception:
        return None
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg",
                   "data": base64.standard_b64encode(buf.getvalue()).decode("ascii")},
    }


def _label(sub_part: dict) -> str:
    return (sub_part.get("label") or "").strip() or "(whole)"


def build_content(question: dict, image_for: dict[str, str],
                  stem: dict | None = None,
                  groups: list[dict] | None = None) -> list[dict]:
    """User content blocks: stem, letter-part intros, then one crop per sub-part."""
    content: list[dict] = [{
        "type": "text",
        "text": (f"Question {question.get('id', '?')} "
                 f"(paper {question.get('paperType', '?')}, "
                 f"{question.get('marks', '?')} marks). "
                 f"It has {len(question.get('subParts') or [])} sub-part(s). "
                 "Transcribe each one."),
    }]

    # The stem is everything printed above the first "(a)". It is a separate
    # crop because Cambridge questions routinely put the whole scenario there and
    # then say only "Find the probability ..." in each part.
    if stem and (stem.get("image") or stem.get("text")):
        content.append({"type": "text", "text": "\n--- QUESTION STEM (shared by all sub-parts) ---"})
        block = _encode_image(stem["image"]) if stem.get("image") else None
        if block:
            content.append(block)
        content.append({
            "type": "text",
            "text": ("RAW STEM TEXT (hint only, often mangled):\n"
                     + ((stem.get("text") or "")[:1800] or "[none]")),
        })

    # A letter part can carry its own introduction that only its roman children
    # depend on — "(a) The table shows the areas, in km^2, of the four largest
    # rainforests", then (a)(i)...(a)(v). Each one is emitted immediately before
    # its first child, so the model reads the question in the order Cambridge
    # printed it. Without this the intro reaches the model nowhere at all and the
    # scenario is silently missing from the paper.
    by_letter = {(g.get("letter") or "").strip(): g for g in (groups or [])}
    emitted: set[str] = set()

    for sp in question.get("subParts") or []:
        path = sp.get("path") or []
        letter = path[0] if path and path != ["_"] else ""
        group = by_letter.get(letter)
        if group and letter not in emitted:
            emitted.add(letter)
            content.append({
                "type": "text",
                "text": f"\n--- INTRODUCTION TO PART ({letter}) "
                        f"(shared by every ({letter}) sub-part below) ---",
            })
            block = _encode_image(group["image"]) if group.get("image") else None
            if block:
                content.append(block)
            content.append({
                "type": "text",
                "text": ("RAW TEXT (hint only, often mangled):\n"
                         + ((group.get("text") or "")[:1800] or "[none]")),
            })

        label = _label(sp)
        content.append({"type": "text",
                        "text": f"\n--- Sub-part {label} ({sp.get('marks', 0)} marks) ---"})
        img = image_for.get(sp.get("partId", ""))
        block = _encode_image(img) if img else None
        if block:
            content.append(block)
        else:
            content.append({"type": "text", "text": "[no image available for this sub-part]"})
        raw = (sp.get("questionText") or "").strip()
        ms = (sp.get("markSchemeText") or "").strip()
        content.append({
            "type": "text",
            "text": ("RAW PDF TEXT (hint only, often mangled):\n" + (raw[:1800] or "[none]") +
                     "\n\nRAW MARK SCHEME:\n" + (ms[:1200] or "[none]")),
        })

    # Safety net: a group whose letter matched no sub-part path would otherwise
    # be dropped on the floor. Send it anyway rather than lose the text.
    for letter, group in by_letter.items():
        if letter in emitted:
            continue
        content.append({"type": "text",
                        "text": f"\n--- INTRODUCTION TO PART ({letter}) ---"})
        block = _encode_image(group["image"]) if group.get("image") else None
        if block:
            content.append(block)
        content.append({
            "type": "text",
            "text": ("RAW TEXT (hint only, often mangled):\n"
                     + ((group.get("text") or "")[:1800] or "[none]")),
        })
    return content


def _clean(fragment: str) -> tuple[str, list[str]]:
    """Sanitise a model-produced fragment and repair bare maths."""
    cleaned, notes = sanitize_fragment(fragment or "")
    wrapped = ensure_math_wrapped(cleaned)
    if wrapped != cleaned:
        notes.append("wrapped bare maths in $...$")
    return wrapped, notes


def extract_question_latex(client: anthropic.Anthropic, question: dict,
                           image_for: dict[str, str],
                           stem: dict | None = None,
                           groups: list[dict] | None = None) -> dict:
    """Convert one whole question (paper + mark scheme) to LaTeX.

    ``stem`` is ``{"image": path, "text": str}`` for the band above the first
    sub-part label; ``groups`` is the same shape plus ``letter`` for each letter
    part that carries its own introduction.
    Returns ``{"stemLatex", "groups": {letter: {...}},
    "subParts": {partId: {...}}, "usage": {...}}``.
    Raises only on transport failure — the caller retries or records the error.
    """
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        messages=[{"role": "user",
                   "content": build_content(question, image_for, stem, groups)}],
    )
    text = next((b.text for b in response.content if b.type == "text"), "")
    data = json.loads(text)

    by_label = {(item.get("label") or "").strip(): item for item in data.get("subParts", [])}
    out_parts: dict[str, dict] = {}
    for sp in question.get("subParts") or []:
        label = _label(sp)
        item = by_label.get(label) or by_label.get(sp.get("label", "")) or {}
        latex, notes = _clean(item.get("latex", ""))
        answer, answer_notes = _clean(item.get("answerLatex", ""))
        points = []
        for point in item.get("markPoints") or []:
            point_latex, point_notes = _clean(point.get("latex", ""))
            notes.extend(point_notes)
            points.append({"code": (point.get("code") or "").strip(), "latex": point_latex})
        notes.extend(answer_notes)

        problems = validate_fragment(latex) if latex else ["model returned no LaTeX"]
        out_parts[sp["partId"]] = {
            "partId": sp["partId"],
            "label": sp.get("label", ""),
            "marks": sp.get("marks", 0),
            "latex": latex,
            "hasDiagram": bool(item.get("hasDiagram")),
            "answerLatex": answer,
            "markPoints": points,
            "confidence": item.get("confidence", "low") if latex else "low",
            "notes": " | ".join(filter(None, [item.get("notes", "")] + notes)),
            "structuralProblems": problems,
        }

    group_latex: dict[str, dict] = {}
    for item in data.get("groups") or []:
        letter = (item.get("letter") or "").strip().strip("()")
        if not letter:
            continue
        latex, notes = _clean(item.get("latex", ""))
        group_latex[letter] = {
            "letter": letter, "latex": latex,
            "hasDiagram": bool(item.get("hasDiagram")),
            "notes": " | ".join(notes),
            "structuralProblems": validate_fragment(latex) if latex else [],
        }

    stem, stem_notes = _clean(data.get("stemLatex", ""))
    usage = response.usage
    return {
        "questionId": question.get("id"),
        "stemLatex": stem,
        "stemProblems": validate_fragment(stem) if stem else [],
        "stemNotes": " | ".join(stem_notes),
        "groups": group_latex,
        "subParts": out_parts,
        "usage": {
            "input": usage.input_tokens,
            "output": usage.output_tokens,
            "cacheRead": getattr(usage, "cache_read_input_tokens", 0) or 0,
            "cacheWrite": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        },
    }
