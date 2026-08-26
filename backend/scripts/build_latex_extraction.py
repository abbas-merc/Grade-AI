"""
build_latex_extraction.py — Run the LaTeX extraction over the question bank.

Part 1 of the typesetting task: turn every sub-part's question text (and its mark
scheme) into compilable LaTeX, then **prove** it compiles before shipping it.

Pipeline
--------
1. Load the part-level bank (``part_level_questions.json``).
2. For each selected question, call ``agents.latex_extractor`` once with every
   sub-part crop. Resumable — a re-run skips questions already stored.
3. Compile-probe every produced fragment against the real document preamble
   (``utils.latex.engine.probe_fragments``). Anything that fails, or that the
   model itself flagged, or that the sanitiser had to cut, lands on a review list
   instead of being shipped silently broken (Part 1.3).

Outputs (both under scripts/part_extraction/):
  part_latex.json     {questionId: {stemLatex, subParts:{partId: {...}}}}
  latex_review.json   the review lists + counts

Run from backend/:
  python scripts/build_latex_extraction.py --sample          # the Part 1.2 spread
  python scripts/build_latex_extraction.py --paper 058021_s25
  python scripts/build_latex_extraction.py --ids A,B,C
  python scripts/build_latex_extraction.py --limit 50        # first N not yet done
  python scripts/build_latex_extraction.py                   # whole bank
  python scripts/build_latex_extraction.py --verify-only     # re-probe, no API calls
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)
load_dotenv(os.path.join(BACKEND, ".env"))

sys.path.insert(0, HERE)
from latex_extractor import MODEL, extract_question_latex  # noqa: E402
from utils.latex import engine, templates  # noqa: E402
from utils.latex.latexify import (  # noqa: E402
    ensure_math_wrapped, looks_like_plain_text, sanitize_fragment, validate_fragment,
)

PE = os.path.join(HERE, "part_extraction")
BANK = os.path.join(PE, "part_level_questions.json")
PARTS_IMG_DIR = os.path.join(HERE, "question_parts")
STEMS_IMG_DIR = os.path.join(HERE, "question_stems")
OUT = os.path.join(PE, "part_latex.json")
REVIEW = os.path.join(PE, "latex_review.json")

MAX_WORKERS = 4
# Claude Opus 5 list price, for the run-cost line only.
PRICE_IN, PRICE_OUT = 5.0, 25.0

# Part 1.2 — one question of each notation family the syllabus actually contains,
# chosen from the real bank so the test exercises real crops, not toy input.
SAMPLE_IDS = [
    "058021_s25_Q16",     # pure algebra: expand and simplify a triple product
    "0580_2_SP_2025_Q7",  # vectors: column vectors + magnitude
    "058021_2024_Q6",     # geometry with angle notation + stem diagram
    "058021_2024_Q17",    # trigonometry, exact values
    "058021_2024_Q22",    # probability
    "0580_4_SP_2025_Q7",  # probability, tree diagram, stem shared by 3 sub-parts
    "058021_s25_Q12",     # statistics, stem + histogram
    "058042_s24_Q5",      # long P4 question, 18 marks, nested (d)(i)/(ii)
    "058042_s24_Q6",      # P4 trigonometry, nested (b)(i)/(ii) + diagram
    "058021_2024_Q11",    # algebra with an inequality/number-line diagram
    "058021_s25_Q2",      # angles on parallel lines (single leaf, diagram)
]

_lock = threading.Lock()
_usage = {"in": 0, "out": 0, "cacheRead": 0, "cacheWrite": 0, "calls": 0}


def _load_bank() -> list[dict]:
    with open(BANK, encoding="utf-8") as fh:
        return json.load(fh)


def _images_for(question: dict) -> dict[str, str]:
    out = {}
    for sp in question.get("subParts") or []:
        path = os.path.join(PARTS_IMG_DIR, sp["partId"] + ".png")
        if os.path.exists(path):
            out[sp["partId"]] = path
    return out


def _figures() -> dict:
    try:
        with open(os.path.join(PE, "part_figures.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _stem_for(question: dict, figures: dict) -> dict | None:
    """The crop + raw text of the band above the first sub-part label."""
    entry = (figures.get("stems") or {}).get(question["id"])
    if not entry:
        return None
    path = os.path.join(STEMS_IMG_DIR, question["id"] + ".png")
    return {"image": path if os.path.exists(path) else "", "text": entry.get("text", "")}


def _groups_for(question: dict, figures: dict) -> list[dict]:
    """Each letter part's own introduction, when it has one."""
    out = []
    prefix = question["id"] + "_"
    for gid, entry in (figures.get("groupStems") or {}).items():
        if not gid.startswith(prefix):
            continue
        path = os.path.join(STEMS_IMG_DIR, gid + ".png")
        out.append({"letter": "".join(entry.get("path") or []),
                    "image": path if os.path.exists(path) else "",
                    "text": entry.get("text", "")})
    return sorted(out, key=lambda g: g["letter"])


def _select(bank: list[dict], argv: list[str]) -> list[dict]:
    if "--sample" in argv:
        by_id = {q["id"]: q for q in bank}
        chosen = [by_id[i] for i in SAMPLE_IDS if i in by_id]
        missing = [i for i in SAMPLE_IDS if i not in by_id]
        if missing:
            print("sample ids not in bank (skipped):", ", ".join(missing))
        return chosen
    if "--ids" in argv:
        wanted = {x.strip() for x in argv[argv.index("--ids") + 1].split(",") if x.strip()}
        return [q for q in bank if q["id"] in wanted]
    if "--paper" in argv:
        code = argv[argv.index("--paper") + 1]
        return [q for q in bank if q["id"].startswith(code + "_Q")]
    return list(bank)


def _run_extraction(selected: list[dict], store: dict) -> list[tuple[str, str]]:
    todo = [q for q in selected if q["id"] not in store]
    print(f"extracting {len(todo)} questions "
          f"({len(selected) - len(todo)} already stored)   model={MODEL}")
    if not todo:
        return []

    key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        raise SystemExit("ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=key, max_retries=4, timeout=300.0)

    figures = _figures()
    errors: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(extract_question_latex, client, q, _images_for(q),
                        _stem_for(q, figures), _groups_for(q, figures)): q
            for q in todo
        }
        for i, future in enumerate(as_completed(futures), 1):
            question = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # network / schema / parse
                errors.append((question["id"], str(exc)))
                print(f"  ERROR {question['id']}: {exc}")
                continue
            with _lock:
                usage = result.pop("usage")
                for k_src, k_dst in (("input", "in"), ("output", "out"),
                                     ("cacheRead", "cacheRead"), ("cacheWrite", "cacheWrite")):
                    _usage[k_dst] += usage[k_src]
                _usage["calls"] += 1
                store[question["id"]] = result
                if i % 10 == 0 or i == len(todo):
                    _save(store)
                    print(f"  {i}/{len(todo)} extracted")
    _save(store)
    return errors


def _save(store: dict) -> None:
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=2, ensure_ascii=False)


def _repair(store: dict) -> int:
    """Re-apply the deterministic fixes to everything already stored.

    Idempotent, and runs on every invocation — so tightening the sanitiser or the
    bare-maths repair improves fragments extracted by earlier runs without paying
    for the API calls again.
    """
    changed = 0

    def fix(text: str) -> str:
        cleaned, _notes = sanitize_fragment(text or "")
        return ensure_math_wrapped(cleaned)

    for rec in store.values():
        stem = fix(rec.get("stemLatex", ""))
        if stem != rec.get("stemLatex"):
            rec["stemLatex"], changed = stem, changed + 1
        rec["stemProblems"] = validate_fragment(stem) if stem else []
        for group in (rec.get("groups") or {}).values():
            fixed = fix(group.get("latex", ""))
            if fixed != group.get("latex"):
                group["latex"], changed = fixed, changed + 1
            group["structuralProblems"] = validate_fragment(fixed) if fixed else []
        for part in (rec.get("subParts") or {}).values():
            for key in ("latex", "answerLatex"):
                fixed = fix(part.get(key, ""))
                if fixed != part.get(key):
                    part[key], changed = fixed, changed + 1
            for point in part.get("markPoints") or []:
                fixed = fix(point.get("latex", ""))
                if fixed != point.get("latex"):
                    point["latex"], changed = fixed, changed + 1
            part["structuralProblems"] = (validate_fragment(part["latex"])
                                          if part.get("latex") else ["model returned no LaTeX"])
    if changed:
        _save(store)
    return changed


def _verify(store: dict, only_ids: set[str] | None) -> dict:
    """Compile-check every fragment and assemble the review lists (Part 1.3)."""
    fragments: list[tuple[str, str]] = []
    meta: dict[str, dict] = {}
    for qid, rec in store.items():
        if only_ids and qid not in only_ids:
            continue
        if rec.get("stemLatex"):
            fragments.append((qid + "::stem", rec["stemLatex"]))
            meta[qid + "::stem"] = {"questionId": qid, "kind": "stem",
                                    "confidence": "n/a", "notes": rec.get("stemNotes", ""),
                                    "structuralProblems": rec.get("stemProblems", [])}
        for letter, group in (rec.get("groups") or {}).items():
            if group.get("latex"):
                key = f"{qid}::group{letter}"
                fragments.append((key, group["latex"]))
                meta[key] = {"questionId": qid, "kind": "group", "confidence": "n/a",
                             "notes": group.get("notes", ""),
                             "structuralProblems": group.get("structuralProblems", [])}
        for pid, part in (rec.get("subParts") or {}).items():
            if part.get("latex"):
                fragments.append((pid, part["latex"]))
            meta[pid] = {"questionId": qid, "kind": "question", **part}
            if part.get("answerLatex"):
                fragments.append((pid + "::answer", part["answerLatex"]))
                meta[pid + "::answer"] = {"questionId": qid, "kind": "answer",
                                          "confidence": part.get("confidence", ""),
                                          "notes": "", "structuralProblems": []}
            for n, point in enumerate(part.get("markPoints") or []):
                if point.get("latex"):
                    fragments.append((f"{pid}::mark{n}", point["latex"]))
                    meta[f"{pid}::mark{n}"] = {"questionId": qid, "kind": "markPoint",
                                               "confidence": part.get("confidence", ""),
                                               "notes": "", "structuralProblems": []}

    print(f"compile-probing {len(fragments)} LaTeX fragments ...")
    build_dir = tempfile.mkdtemp(prefix="ga-latex-probe-")
    preamble = templates.probe_preamble(build_dir)
    failures = engine.probe_fragments(fragments, preamble, build_dir=build_dir)

    review = {
        "fragmentsChecked": len(fragments),
        "compileFailures": failures,
        "lowConfidence": [], "mediumConfidence": [],
        "structuralProblems": {}, "sanitiserNotes": {},
        "plainTextSuspects": [], "missingLatex": [],
    }
    for pid, info in meta.items():
        if info.get("kind") != "question":
            continue
        conf = info.get("confidence")
        if conf == "low":
            review["lowConfidence"].append(pid)
        elif conf == "medium":
            review["mediumConfidence"].append(pid)
        problems = [p for p in (info.get("structuralProblems") or [])
                    if p != "empty fragment"]
        if problems:
            review["structuralProblems"][pid] = problems
        if info.get("notes"):
            review["sanitiserNotes"][pid] = info["notes"]
        if not (info.get("latex") or "").strip():
            review["missingLatex"].append(pid)
        elif looks_like_plain_text(info["latex"]) and any(
                ch.isdigit() for ch in info["latex"]):
            # Prose containing numbers but no markup at all: usually correct
            # ("Write down the order of rotational symmetry."), occasionally a
            # sign the model gave up on the notation. Worth a human glance.
            review["plainTextSuspects"].append(pid)

    review["needsReview"] = sorted(set(
        list(failures)
        + review["lowConfidence"]
        + list(review["structuralProblems"])
        + review["missingLatex"]
    ))
    with open(REVIEW, "w", encoding="utf-8") as fh:
        json.dump(review, fh, indent=2, ensure_ascii=False)
    return review


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    argv = sys.argv[1:]
    os.makedirs(PE, exist_ok=True)

    bank = _load_bank()
    selected = _select(bank, argv)
    if "--limit" in argv:
        selected = selected[:int(argv[argv.index("--limit") + 1])]

    store: dict = {}
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as fh:
            store = json.load(fh)

    errors: list[tuple[str, str]] = []
    if "--verify-only" not in argv:
        errors = _run_extraction(selected, store)

    repaired = _repair(store)
    if repaired:
        print(f"deterministic repair fixed {repaired} stored fragments")

    review = _verify(store, {q["id"] for q in selected} if selected != bank else None)

    if _usage["calls"]:
        cost = _usage["in"] / 1e6 * PRICE_IN + _usage["out"] / 1e6 * PRICE_OUT
        cost += _usage["cacheWrite"] / 1e6 * PRICE_IN * 1.25
        cost += _usage["cacheRead"] / 1e6 * PRICE_IN * 0.1
        print(f"\nAPI: {_usage['calls']} calls  in={_usage['in']}  out={_usage['out']}  "
              f"cacheW={_usage['cacheWrite']}  cacheR={_usage['cacheRead']}  ~${cost:.2f}"
              f"  (~${cost / _usage['calls']:.3f}/question)")

    sub_parts = sum(len(r.get("subParts") or {}) for r in store.values())
    print(f"\nquestions stored: {len(store)}   sub-parts: {sub_parts}")
    print(f"fragments compile-checked: {review['fragmentsChecked']}")
    print(f"compile FAILURES: {len(review['compileFailures'])}")
    for key, msg in list(review["compileFailures"].items())[:12]:
        print(f"   {key}: {msg}")
    print(f"low confidence: {len(review['lowConfidence'])}   "
          f"medium: {len(review['mediumConfidence'])}   "
          f"structural: {len(review['structuralProblems'])}   "
          f"no LaTeX: {len(review['missingLatex'])}   "
          f"plain-text suspects: {len(review['plainTextSuspects'])}")
    print(f"NEEDS HUMAN REVIEW: {len(review['needsReview'])}")
    if errors:
        print(f"extraction errors: {len(errors)}")
        for qid, msg in errors[:5]:
            print(f"   {qid}: {msg}")
    print(f"\n-> {os.path.relpath(OUT)}\n-> {os.path.relpath(REVIEW)}")


if __name__ == "__main__":
    main()
