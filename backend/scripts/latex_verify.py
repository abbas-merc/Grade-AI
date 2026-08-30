"""
latex_verify.py — What counts as a GENUINELY converted question.

The single source of truth for "is this question's LaTeX extraction shippable",
shared by:

* ``scripts/run_full_latex_extraction.py`` — the batch runner, so every question
  in the full-bank run is held to the same bar as the first hand-checked 32.
* ``scripts/demo_latex_paper.py`` — the demo pool.

A question is verified only when ALL of these hold:

1. it exists in the part-level bank and has sub-parts;
2. every sub-part has stored LaTeX (never the raw-text fallback);
3. every fragment — question body, answer, each mark point — is structurally
   valid (``validate_fragment``);
4. the extraction review pass did not flag it (compile failure, low confidence,
   structural problem, missing LaTeX);
5. a question stem that exists in the source paper was actually extracted, and
   likewise for a letter part that carries its own introduction;
6. every sub-part the extractor saw a diagram in resolves to a real crop —
   otherwise the page would print correct LaTeX with the diagram silently gone,
   which is the wrong question rather than a broken one.

Checks 5 and 6 are the two failure modes found by hand while verifying the first
32 (the missing-stem bug and the orphaned/stale figure crop); they are applied
here up front so the full run never has to rediscover them.
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from utils.latex import assemble  # noqa: E402
from utils.latex.latexify import validate_fragment  # noqa: E402

PE = os.path.join(HERE, "part_extraction")
REVIEW_PATH = os.path.join(PE, "latex_review.json")

# A stem crop whose OCR text is shorter than this is page furniture (the question
# number, a registration mark), not a scenario — those questions legitimately
# have no stem, so an empty stemLatex is correct rather than missing.
_MIN_MEANINGFUL_STEM_CHARS = 12


def meaningful(text: str) -> bool:
    return len(re.sub(r"[^A-Za-z0-9]", "", text or "")) >= _MIN_MEANINGFUL_STEM_CHARS


def review_flagged(review: dict | None = None) -> set[str]:
    """Question ids the extraction's own review pass flagged as not shippable."""
    if review is None:
        try:
            with open(REVIEW_PATH, encoding="utf-8") as fh:
                review = json.load(fh)
        except Exception:
            return set()
    flagged: set[str] = set()
    for key in ("needsReview", "missingLatex", "lowConfidence"):
        for item in review.get(key) or []:
            flagged.add(assemble.question_id_from_part_id(str(item)) or str(item))
    for key in ("compileFailures", "structuralProblems"):
        for item in (review.get(key) or {}):
            flagged.add(assemble.question_id_from_part_id(str(item)) or str(item))
    return flagged


def unresolved_diagrams(question: dict, extraction: dict, figures: dict) -> list[str]:
    """Sub-parts the extractor said carry a diagram but whose crop won't resolve.

    Mirrors the image lookup ``assemble`` performs at render time: the sub-part's
    own crop, then the question stem's figure, then any shared asset the sub-part
    belongs to. A miss here is the "orphaned / stale crop" failure — the LaTeX is
    fine, the diagram is simply not on the page.
    """
    qid = question["id"]
    stored = (extraction or {}).get("subParts") or {}
    out = []
    for sp in question.get("subParts") or []:
        pid = sp.get("partId", "")
        if not (stored.get(pid) or {}).get("hasDiagram"):
            continue
        if assemble.figure_path(pid):
            continue
        if assemble.figure_path(assemble._stem_figure_id(figures, qid)):
            continue
        if any(assemble.figure_path(a.get("assetId", ""))
               for a in question.get("sharedAssets") or []
               if pid in (a.get("usedByParts") or [])):
            continue
        out.append(pid)
    return out


def verify_question(qid: str, store: dict, bank: dict, figures: dict,
                    flagged: set[str]) -> list[str]:
    """Return the reasons `qid` is NOT shippable. Empty list == verified."""
    problems: list[str] = []
    question = bank.get(qid)
    extraction = store.get(qid)
    if question is None:
        return ["not in the part-level bank"]
    if not extraction:
        return ["no LaTeX extraction stored"]
    if qid in flagged:
        problems.append("flagged by the extraction review pass")

    sub_parts = question.get("subParts") or []
    if not sub_parts:
        problems.append("bank record has no sub-parts")

    stored_parts = extraction.get("subParts") or {}
    for sp in sub_parts:
        pid = sp.get("partId", "")
        body = ((stored_parts.get(pid) or {}).get("latex") or "").strip()
        if not body:
            problems.append(f"{pid}: no LaTeX (would fall back to raw text)")
            continue
        for label, fragment in (
            ("question", body),
            ("answer", (stored_parts.get(pid) or {}).get("answerLatex") or ""),
            *[(f"mark point {i + 1}", mp.get("latex") or "")
              for i, mp in enumerate((stored_parts.get(pid) or {}).get("markPoints") or [])],
        ):
            if fragment.strip():
                for issue in validate_fragment(fragment):
                    problems.append(f"{pid}: {label} LaTeX invalid — {issue}")

    # The stem bug this pipeline was built to fix: a scenario that exists in the
    # source paper but never made it into the extraction.
    stem_entry = (figures.get("stems") or {}).get(qid) or {}
    if meaningful(stem_entry.get("text", "")) and not (extraction.get("stemLatex") or "").strip():
        problems.append("question stem exists in the source paper but was not extracted")

    # Same, for a letter part that carries its own introduction.
    groups = extraction.get("groups") or {}
    for gid, entry in (figures.get("groupStems") or {}).items():
        if not gid.startswith(qid + "_"):
            continue
        letter = gid[len(qid) + 1:]
        if meaningful(entry.get("text", "")) and not ((groups.get(letter) or {}).get("latex") or "").strip():
            problems.append(f"letter part ({letter}) introduction was not extracted")

    for pid in unresolved_diagrams(question, extraction, figures):
        problems.append(f"{pid}: carries a diagram but no crop resolves for it")

    return problems


def verified_pool() -> tuple[list[dict], dict[str, list[str]]]:
    """(bank records that are verified, {rejected qid: reasons})."""
    assemble.reload_stores()
    store, bank, figures = assemble.latex_store(), assemble.bank_by_id(), assemble.figure_store()
    flagged = review_flagged()
    pool, rejected = [], {}
    for qid in sorted(store):
        problems = verify_question(qid, store, bank, figures, flagged)
        if problems:
            rejected[qid] = problems
        else:
            pool.append(bank[qid])
    return pool, rejected
