"""
utils/latex/assemble.py — Build the structured paper dict the templates consume.

The templates take a plain, engine-agnostic dict (Part 2.2). This module produces
it from whatever the paper generator actually returned, so the LaTeX pipeline
slots in behind the existing endpoints without changing their contracts.

Paper dict shape
----------------
::

    {
      "schoolName": str, "paperName": str, "subjectLabel": str,
      "paperCode": str, "session": str,
      "totalMarks": int, "timeMinutes": int, "calculatorAllowed": bool,
      "questions": [
        {"number": 1, "marks": 5, "key": "<questionId>",
         "intro": {"latex": str, "image": {"path", "widthMm", "heightMm"} | None},
         "subParts": [
           {"key": "<partId>", "label": "(a)", "depth": 0, "marks": 3,
            "latex": str,
            "image": {...} | None,
            "answerStyle": "dotted"|"blank"|"none"|"skip", "answerLines": int|None,
            # mark-scheme side, used by mark_scheme_tex:
            "answerLatex": str, "markPoints": [{"code", "latex"}]}
         ]}
      ]
    }

Sources, in priority order, for each question's LaTeX:

1. ``latexByPart`` carried on the incoming request (a caller that already has it),
2. the Firestore question document's own sub-part LaTeX fields (once the bank is
   seeded with them),
3. the build artefact ``scripts/part_extraction/part_latex.json``.

A question with no extraction at all falls back to
``utils.latex.latexify.latex_from_raw_text`` over the raw PDF text, and is
counted in ``fallbacks`` so the caller can report it rather than pretend the
notation was converted.
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache

from . import config
from .latexify import latex_from_raw_text, unicode_to_latex
from .templates import measure_image

_BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PE = os.path.join(_BACKEND, "scripts", "part_extraction")
_LATEX_JSON = os.path.join(_PE, "part_latex.json")
_FIGURES_JSON = os.path.join(_PE, "part_figures.json")
_BANK_JSON = os.path.join(_PE, "part_level_questions.json")
_UNRENDERABLE_JSON = os.path.join(_PE, "latex_unrenderable.json")
# Figures are served from backend/static like every other question image, and
# read straight off disk by the compiler.
_STATIC_FIGURES = os.path.join(_BACKEND, "static", "question_figures")
_SCRIPT_FIGURES = os.path.join(_BACKEND, "scripts", "question_figures")


def _load(path: str, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


@lru_cache(maxsize=1)
def latex_store() -> dict:
    return _load(_LATEX_JSON, {})


@lru_cache(maxsize=1)
def figure_store() -> dict:
    data = _load(_FIGURES_JSON, {})
    for key in ("parts", "shared", "stems", "groupStems"):
        data.setdefault(key, {})
    return data


@lru_cache(maxsize=1)
def bank_by_id() -> dict:
    return {q["id"]: q for q in _load(_BANK_JSON, [])}


@lru_cache(maxsize=1)
def unrenderable_ids() -> frozenset:
    """Questions the typesetter cannot print truthfully.

    Written by ``scripts/run_full_latex_extraction.py``. These are questions with
    a sub-part that carries a diagram — a blank grid to draw the graph on, a pair
    of axes to sketch, a construction line — for which no crop resolves. The
    LaTeX would compile and read correctly and the thing the student is told to
    draw on would simply not be on the page, which is worse than a compile error
    because nothing announces it. The paper generator drops them from the
    selection pool rather than print a question that cannot be answered.
    """
    return frozenset(_load(_UNRENDERABLE_JSON, []))


def reload_stores() -> None:
    """Drop the cached build artefacts (used by tests and the seed scripts)."""
    latex_store.cache_clear()
    figure_store.cache_clear()
    bank_by_id.cache_clear()
    unrenderable_ids.cache_clear()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
_PART_ID_RE = re.compile(r"^(.*_Q\d+)_")


def question_id_from_part_id(part_id: str) -> str:
    """`058041_2024_Q1_a_i` -> `058041_2024_Q1`.

    A sub-part id is "<questionId>_<path joined by underscores>", and a question
    id always ends in "_Q<number>", so the first such boundary is the split.
    """
    match = _PART_ID_RE.match(part_id or "")
    return match.group(1) if match else ""


def question_id_from_image_url(url: str) -> str:
    """`/question_snippets/058021_s25_Q2.png` -> `058021_s25_Q2`."""
    if not url:
        return ""
    return os.path.splitext(os.path.basename(url))[0]


def figure_path(image_id: str) -> str:
    """Absolute path to a published figure crop, or "" when absent."""
    if not image_id:
        return ""
    name = image_id if image_id.lower().endswith(".png") else image_id + ".png"
    for directory in (_STATIC_FIGURES, _SCRIPT_FIGURES):
        candidate = os.path.join(directory, name)
        if os.path.exists(candidate):
            return candidate
    return ""


def _stem_figure_id(figures: dict, question_id: str) -> str:
    """Asset id of the figure printed inside a question's stem, if it has one."""
    entry = figures["stems"].get(question_id) or {}
    return ((entry.get("figure") or {}).get("assetId")) or ""


def _group_figure_id(figures: dict, question_id: str, letter: str) -> str:
    """Asset id of the figure inside a letter part's own introduction, if any."""
    entry = (figures.get("groupStems") or {}).get(f"{question_id}_{letter}") or {}
    return ((entry.get("figure") or {}).get("assetId")) or ""


def _image_block(image_id: str, body_width_mm: float) -> dict | None:
    path = figure_path(image_id)
    if not path:
        return None
    width, height = measure_image(path, body_width_mm)
    return {"path": path, "widthMm": width, "heightMm": height}


def _display_label(path: list[str] | None, label: str) -> tuple[str, int]:
    """(label to print, nesting depth) from a sub-part's structural path.

    Cambridge prints the deepest token only, indented under its parent —
    ``(b)`` then ``(ii)`` — never the flattened ``(b)(ii)``.
    """
    if path and path != ["_"]:
        return "(" + path[-1] + ")", max(0, len(path) - 1)
    if label and label != "(whole)":
        return label, 0
    return "", 0


def _body_width_mm(depth: int) -> float:
    width = 210.0 - 2 * config.PAGE_MARGIN_MM
    indent = config.QUESTION_LABEL_WIDTH_MM + config.NEST_INDENT_MM * depth
    return width - indent - config.SUBPART_LABEL_WIDTH_MM


# --------------------------------------------------------------------------- #
# Per-question assembly
# --------------------------------------------------------------------------- #
def build_question(question_id: str, number: int, *,
                   latex_override: dict | None = None) -> tuple[dict, bool]:
    """(question dict for the templates, used_fallback)."""
    bank = bank_by_id().get(question_id) or {}
    stored = latex_override or latex_store().get(question_id) or {}
    parts_latex = stored.get("subParts") or {}
    figures = figure_store()
    used_fallback = False

    stem_image = _image_block(_stem_figure_id(figures, question_id), _body_width_mm(0))

    # Which sub-part each shared figure should be printed above: the first one
    # that uses it, so the group sees it once, in reading order.
    shared_for: dict[str, str] = {}
    for asset_id, asset in figures["shared"].items():
        members = asset.get("usedByParts") or []
        if members and members[0].startswith(question_id):
            shared_for[members[0]] = asset_id

    sub_parts: list[dict] = []
    seen_groups: set[str] = set()
    for sp in bank.get("subParts") or []:
        part_id = sp.get("partId", "")
        path = sp.get("path") or []
        label, depth = _display_label(path, sp.get("label", ""))

        # A nested roman leaf needs its letter parent printed above it once, so
        # "(b) (i) ... (ii) ..." reads the way Cambridge sets it.
        if depth > 0 and path:
            group = path[0]
            if group not in seen_groups:
                seen_groups.add(group)
                group_latex = ((stored.get("groups") or {}).get(group) or {}).get("latex", "")
                sub_parts.append({
                    "key": f"{question_id}_group_{group}",
                    "label": "(" + group + ")", "depth": 0, "marks": 0,
                    "latex": group_latex,
                    "image": _image_block(_group_figure_id(figures, question_id, group),
                                          _body_width_mm(0)),
                    "answerStyle": "skip", "answerLines": 0,
                    "isGroupHeader": True,
                })

        stored_part = parts_latex.get(part_id) or {}
        latex = (stored_part.get("latex") or "").strip()
        if not latex:
            latex = latex_from_raw_text(sp.get("questionText", ""))
            used_fallback = True

        width = _body_width_mm(depth)
        image = _image_block(part_id, width)
        if image is None and part_id in shared_for:
            image = _image_block(shared_for[part_id], width)

        sub_parts.append({
            "key": part_id,
            "label": label,
            "depth": depth,
            "marks": int(sp.get("marks", 0) or 0),
            "latex": latex,
            "image": image,
            "answerStyle": "dotted",
            "answerLines": None,
            "msLabel": sp.get("label", ""),
            "answerLatex": stored_part.get("answerLatex", ""),
            "markPoints": stored_part.get("markPoints") or [],
        })

    if not sub_parts:  # question not in the part-level bank at all
        used_fallback = True
        sub_parts = [{
            "key": question_id, "label": "", "depth": 0,
            "marks": int(bank.get("marks", 0) or 0),
            "latex": unicode_to_latex(bank.get("questionText", "")),
            "image": None, "answerStyle": "dotted", "answerLines": None,
            "answerLatex": "", "markPoints": [],
        }]

    return {
        "number": number,
        "key": question_id,
        "marks": int(bank.get("marks", 0) or 0),
        "sourceCode": bank.get("paperCode", ""),
        "intro": {"latex": (stored.get("stemLatex") or "").strip(), "image": stem_image},
        "subParts": sub_parts,
    }, used_fallback


# --------------------------------------------------------------------------- #
# Paper-level assembly
# --------------------------------------------------------------------------- #
def _header(paper_data: dict, total_marks: int) -> dict:
    subject = paper_data.get("subject", "math")
    subject_label = {"math": "Mathematics (0580) Extended",
                     "physics": "Physics (0625)",
                     "chemistry": "Chemistry (0620)"}.get(subject, str(subject).title())
    calc = (paper_data.get("paperType") or "").upper() != "P2"
    if "calculatorAllowed" in paper_data:
        calc = bool(paper_data["calculatorAllowed"])
    minutes = int(round(total_marks * config.MINUTES_PER_MARK / 15.0) * 15) or 15
    return {
        "schoolName": (paper_data.get("schoolName") or "").strip(),
        "paperName": (paper_data.get("paperName") or "").strip() or "Custom Practice Paper",
        "title": "Custom Practice Paper",
        "subjectLabel": subject_label,
        # Placeholders, deliberately not a real Cambridge paper code — this is a
        # school practice paper assembled from past-paper content.
        "paperCode": (paper_data.get("paperCode") or "").strip() or "Practice/01",
        "session": (paper_data.get("session") or "").strip() or "Practice",
        "totalMarks": total_marks,
        "timeMinutes": minutes,
        "calculatorAllowed": calc,
    }


def from_generated_paper(paper_data: dict) -> dict:
    """Assemble from a ``POST /api/generate-paper`` response.

    That response identifies each question only by its snippet URL, which carries
    the question id — enough to recover the full part-level record.
    """
    questions: list[dict] = []
    fallbacks: list[str] = []
    overrides = paper_data.get("latexByQuestion") or {}
    # The generator's response carries Cambridge's own mark-scheme text for every
    # question. It is only needed when the extraction did not cover the question,
    # but it is the honest thing to print in that case.
    raw_schemes = {int(m.get("questionNumber", 0) or 0): (m.get("markSchemeText") or "")
                   for m in paper_data.get("markScheme") or []}
    for item in paper_data.get("questions", []):
        qid = (item.get("questionId")
               or question_id_from_image_url(item.get("questionImageUrl", "")))
        number = int(item.get("assignedNumber") or len(questions) + 1)
        question, fell_back = build_question(qid, number,
                                             latex_override=overrides.get(qid))
        if fell_back:
            fallbacks.append(qid or f"question {number}")
            question["rawMarkScheme"] = latex_from_raw_text(raw_schemes.get(number, ""))
        # The generator's own mark total for this question is authoritative.
        if item.get("marks"):
            question["marks"] = int(item["marks"])
        questions.append(question)

    total = sum(int(q.get("marks", 0) or 0) for q in questions) or \
        int(paper_data.get("totalMarks", 0) or 0)
    paper = _header(paper_data, total)
    paper["questions"] = questions
    paper["fallbacks"] = fallbacks
    return paper


def from_partlevel_paper(paper_data: dict) -> dict:
    """Assemble from a ``POST /api/generate-paper/partlevel`` response.

    The part-level response already names every sub-part, including donor
    sub-parts substituted in from another question, so each one is resolved by
    its own ``partId`` rather than by its host question.
    """
    latex = latex_store()
    figures = figure_store()
    questions: list[dict] = []
    fallbacks: list[str] = []

    for index, item in enumerate(paper_data.get("questions", []), start=1):
        number = int(item.get("assignedNumber") or index)
        host_id = ""
        sub_parts: list[dict] = []
        seen_groups: set[str] = set()

        for sp in item.get("subParts", []):
            part_id = sp.get("partId", "")
            source_qid = question_id_from_part_id(part_id)
            host_id = host_id or source_qid
            bank_part = _bank_subpart(source_qid, part_id)
            path = (bank_part or {}).get("path") or []
            label, depth = _display_label(path, sp.get("label", ""))

            if depth > 0 and path:
                group = path[0]
                marker = source_qid + "/" + group
                if marker not in seen_groups:
                    seen_groups.add(marker)
                    group_latex = ((((latex.get(source_qid) or {}).get("groups") or {})
                                    .get(group)) or {}).get("latex", "")
                    sub_parts.append({
                        "key": marker, "label": "(" + group + ")", "depth": 0,
                        "marks": 0, "latex": group_latex,
                        "image": _image_block(
                            _group_figure_id(figures, source_qid, group),
                            _body_width_mm(0)),
                        "answerStyle": "skip", "answerLines": 0, "isGroupHeader": True,
                    })

            stored = ((latex.get(source_qid) or {}).get("subParts") or {}).get(part_id) or {}
            body = (stored.get("latex") or "").strip()
            if not body:
                body = latex_from_raw_text((bank_part or {}).get("questionText", ""))
                fallbacks.append(part_id)

            width = _body_width_mm(depth)
            image = _image_block(part_id, width)
            if image is None:
                for asset_id, asset in figures["shared"].items():
                    if part_id in (asset.get("usedByParts") or []):
                        image = _image_block(asset_id, width)
                        break

            sub_parts.append({
                "key": part_id, "label": label, "depth": depth,
                "marks": int(sp.get("marks", 0) or 0), "latex": body, "image": image,
                "answerStyle": "dotted", "answerLines": None,
                "msLabel": sp.get("label", "") or (bank_part or {}).get("label", ""),
                "answerLatex": stored.get("answerLatex", ""),
                "markPoints": stored.get("markPoints") or [],
            })

        stem = (latex.get(host_id) or {}).get("stemLatex", "") if host_id else ""
        stem_image = _image_block(
            _stem_figure_id(figures, host_id), _body_width_mm(0))
        # An assembled question (donor sub-parts spliced in) must not inherit the
        # host question's stem — the stem describes content that is no longer all
        # there. Cambridge-faithful and, more importantly, not misleading.
        if item.get("assembled"):
            stem, stem_image = "", None

        questions.append({
            "number": number, "key": host_id or f"Q{number}",
            "marks": int(item.get("marks", 0) or 0),
            "sourceCode": item.get("originalPaperCode", ""),
            "intro": {"latex": stem, "image": stem_image},
            "subParts": sub_parts,
        })

    total = int(paper_data.get("totalMarks", 0) or 0) or \
        sum(int(q["marks"]) for q in questions)
    paper = _header(paper_data, total)
    paper["questions"] = questions
    paper["fallbacks"] = fallbacks
    return paper


def _bank_subpart(question_id: str, part_id: str) -> dict | None:
    question = bank_by_id().get(question_id)
    if not question:
        return None
    for sp in question.get("subParts") or []:
        if sp.get("partId") == part_id:
            return sp
    return None
