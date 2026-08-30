"""
run_full_latex_extraction.py — Convert the WHOLE question bank to LaTeX, safely.

``build_latex_extraction.py`` converts a selection in one shot and then
compile-probes every fragment in the store. That is right for a handful of
questions and wrong for 500: a mid-run failure loses the batch, and the verify
pass re-probes the entire (growing) store each time.

This runner is the production-scale version of the same pipeline:

* **Batched.** Questions are processed in batches (default 25). Each batch is
  extracted, deterministically repaired, compile-probed and verified on its own,
  and reported before the next one starts.
* **Interruptible.** The store is written atomically (temp file + ``os.replace``)
  after every few completed questions, so Ctrl-C — or a crash — leaves a store
  that is complete for every question it contains and simply missing the rest.
  Re-running resumes exactly where it stopped. A question is never half-written:
  the record for a question is only inserted once the model call returned a
  fully parsed result.
* **Budgeted.** A hard spend ceiling (``--budget``) is checked BEFORE each batch
  using the running cost-per-question observed so far. When the next batch could
  cross the ceiling the run stops cleanly at a batch boundary rather than dying
  mid-call. This is what stops the run failing part-way the way an unbudgeted
  one does.
* **Verified to the same bar as the hand-checked first 32.** Every question goes
  through ``scripts/latex_verify.verify_question``: every sub-part has real
  LaTeX, every fragment is structurally valid AND compiles against the real
  preamble, a stem that exists in the source paper was extracted, and every
  sub-part carrying a diagram resolves to a real crop. Anything that fails lands
  on the manual-review list instead of being shipped silently broken.

Outputs (all under scripts/part_extraction/):
  part_latex.json        the store (same file/shape build_latex_extraction writes)
  latex_review.json      compile/confidence review, cumulative
  latex_manual_review.json  the human worklist: {questionId: [reasons]}
  _full_run.log          the per-batch progress report

Run from backend/:
  python scripts/run_full_latex_extraction.py                    # everything left
  python scripts/run_full_latex_extraction.py --budget 28        # spend ceiling ($)
  python scripts/run_full_latex_extraction.py --batch-size 25
  python scripts/run_full_latex_extraction.py --limit 50         # first N remaining
  python scripts/run_full_latex_extraction.py --verify-only      # no API calls
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
load_dotenv(os.path.join(BACKEND, ".env"))

from latex_extractor import MODEL, extract_question_latex  # noqa: E402
from latex_verify import review_flagged, unresolved_diagrams, verify_question  # noqa: E402
from utils.latex import assemble, engine, templates  # noqa: E402
from utils.latex.latexify import (  # noqa: E402
    ensure_math_wrapped, looks_like_plain_text, sanitize_fragment, validate_fragment,
)

PE = os.path.join(HERE, "part_extraction")
BANK = os.path.join(PE, "part_level_questions.json")
OUT = os.path.join(PE, "part_latex.json")
REVIEW = os.path.join(PE, "latex_review.json")
MANUAL = os.path.join(PE, "latex_manual_review.json")
UNRENDERABLE = os.path.join(PE, "latex_unrenderable.json")
LOG = os.path.join(PE, "_full_run.log")
PARTS_IMG_DIR = os.path.join(HERE, "question_parts")
STEMS_IMG_DIR = os.path.join(HERE, "question_stems")

MAX_WORKERS = 4
SAVE_EVERY = 5
# Claude Opus 5 list price, for the run-cost line and the budget ceiling.
PRICE_IN, PRICE_OUT = 5.0, 25.0
# Until the run has priced a batch of its own, assume the blended rate measured
# over the first hand-verified 32 questions.
SEED_COST_PER_QUESTION = 0.047

_lock = threading.Lock()
_usage = {"in": 0, "out": 0, "cacheRead": 0, "cacheWrite": 0, "calls": 0}
_log_lines: list[str] = []


def say(line: str = "") -> None:
    print(line, flush=True)
    _log_lines.append(line)
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Durable, atomic persistence
# --------------------------------------------------------------------------- #
def save_json(path: str, data) -> None:
    """Write JSON so an interrupted run can never leave a truncated file.

    The payload is written to a sibling temp file, flushed and fsync'd, then
    moved into place with ``os.replace`` — atomic on both NTFS and POSIX. A
    reader therefore sees either the previous complete file or the new complete
    file, never a half-written one.
    """
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def load_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


# --------------------------------------------------------------------------- #
# Inputs for one question
# --------------------------------------------------------------------------- #
def images_for(question: dict) -> dict[str, str]:
    out = {}
    for sp in question.get("subParts") or []:
        path = os.path.join(PARTS_IMG_DIR, sp["partId"] + ".png")
        if os.path.exists(path):
            out[sp["partId"]] = path
    return out


def stem_for(question: dict, figures: dict) -> dict | None:
    entry = (figures.get("stems") or {}).get(question["id"])
    if not entry:
        return None
    path = os.path.join(STEMS_IMG_DIR, question["id"] + ".png")
    return {"image": path if os.path.exists(path) else "", "text": entry.get("text", "")}


def groups_for(question: dict, figures: dict) -> list[dict]:
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


def missing_sources(question: dict) -> list[str]:
    """Sub-parts with no crop on disk — the model would be asked to transcribe
    nothing, so the question is sent straight to manual review instead."""
    return [sp["partId"] for sp in question.get("subParts") or []
            if not os.path.exists(os.path.join(PARTS_IMG_DIR, sp["partId"] + ".png"))]


# --------------------------------------------------------------------------- #
# Deterministic repair (identical to build_latex_extraction._repair, scoped)
# --------------------------------------------------------------------------- #
def repair(records: dict) -> int:
    changed = 0

    def fix(text: str) -> str:
        cleaned, _notes = sanitize_fragment(text or "")
        return ensure_math_wrapped(cleaned)

    for rec in records.values():
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
    return changed


# --------------------------------------------------------------------------- #
# Compile probing + review, scoped to a set of question ids
# --------------------------------------------------------------------------- #
def fragments_of(store: dict, qids) -> tuple[list[tuple[str, str]], dict]:
    fragments: list[tuple[str, str]] = []
    meta: dict[str, dict] = {}
    for qid in qids:
        rec = store.get(qid)
        if not rec:
            continue
        if rec.get("stemLatex"):
            key = qid + "::stem"
            fragments.append((key, rec["stemLatex"]))
            meta[key] = {"questionId": qid, "kind": "stem", "confidence": "n/a",
                         "notes": rec.get("stemNotes", ""),
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
                    key = f"{pid}::mark{n}"
                    fragments.append((key, point["latex"]))
                    meta[key] = {"questionId": qid, "kind": "markPoint",
                                 "confidence": part.get("confidence", ""),
                                 "notes": "", "structuralProblems": []}
    return fragments, meta


def blank_review() -> dict:
    return {"fragmentsChecked": 0, "compileFailures": {}, "lowConfidence": [],
            "mediumConfidence": [], "structuralProblems": {}, "sanitiserNotes": {},
            "plainTextSuspects": [], "missingLatex": [], "needsReview": []}


def probe_and_review(store: dict, qids, review: dict) -> dict:
    """Compile-probe the fragments of `qids` and fold the result into `review`."""
    fragments, meta = fragments_of(store, qids)
    build_dir = tempfile.mkdtemp(prefix="ga-latex-probe-")
    try:
        preamble = templates.probe_preamble(build_dir)
        failures = engine.probe_fragments(fragments, preamble, build_dir=build_dir)
    finally:
        import shutil
        shutil.rmtree(build_dir, ignore_errors=True)

    review["fragmentsChecked"] = review.get("fragmentsChecked", 0) + len(fragments)
    review["compileFailures"].update(failures)
    for pid, info in meta.items():
        if info.get("kind") != "question":
            continue
        conf = info.get("confidence")
        if conf == "low" and pid not in review["lowConfidence"]:
            review["lowConfidence"].append(pid)
        elif conf == "medium" and pid not in review["mediumConfidence"]:
            review["mediumConfidence"].append(pid)
        problems = [p for p in (info.get("structuralProblems") or [])
                    if p != "empty fragment"]
        if problems:
            review["structuralProblems"][pid] = problems
        if info.get("notes"):
            review["sanitiserNotes"][pid] = info["notes"]
        if not (info.get("latex") or "").strip():
            if pid not in review["missingLatex"]:
                review["missingLatex"].append(pid)
        elif looks_like_plain_text(info["latex"]) and any(ch.isdigit() for ch in info["latex"]):
            if pid not in review["plainTextSuspects"]:
                review["plainTextSuspects"].append(pid)

    review["needsReview"] = sorted(set(
        list(review["compileFailures"])
        + review["lowConfidence"]
        + list(review["structuralProblems"])
        + review["missingLatex"]
    ))
    return {"fragments": len(fragments), "failures": failures}


# --------------------------------------------------------------------------- #
# Extraction of one batch
# --------------------------------------------------------------------------- #
def extract_batch(client, batch: list[dict], store: dict, figures: dict) -> list[tuple[str, str]]:
    errors: list[tuple[str, str]] = []
    done = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(extract_question_latex, client, q, images_for(q),
                        stem_for(q, figures), groups_for(q, figures)): q
            for q in batch
        }
        for future in as_completed(futures):
            question = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                errors.append((question["id"], f"{type(exc).__name__}: {exc}"))
                continue
            with _lock:
                usage = result.pop("usage", None) or {}
                for src, dst in (("input", "in"), ("output", "out"),
                                 ("cacheRead", "cacheRead"), ("cacheWrite", "cacheWrite")):
                    _usage[dst] += int(usage.get(src, 0) or 0)
                _usage["calls"] += 1
                # Only a fully parsed result is inserted, so the store never
                # contains a half-written question.
                store[question["id"]] = result
                done += 1
                if done % SAVE_EVERY == 0:
                    save_json(OUT, store)
    save_json(OUT, store)
    return errors


def spend() -> float:
    return (_usage["in"] / 1e6 * PRICE_IN
            + _usage["out"] / 1e6 * PRICE_OUT
            + _usage["cacheWrite"] / 1e6 * PRICE_IN * 1.25
            + _usage["cacheRead"] / 1e6 * PRICE_IN * 0.1)


def per_question() -> float:
    return spend() / _usage["calls"] if _usage["calls"] else SEED_COST_PER_QUESTION


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-size", type=int, default=25)
    ap.add_argument("--budget", type=float, default=28.0,
                    help="hard USD ceiling for THIS run; stops at a batch boundary")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ids", default="")
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args()

    os.makedirs(PE, exist_ok=True)
    bank_list = load_json(BANK, [])
    bank = {q["id"]: q for q in bank_list}
    store = load_json(OUT, {})
    review = load_json(REVIEW, None) or blank_review()
    for key, default in blank_review().items():
        review.setdefault(key, default)
    manual: dict[str, list[str]] = load_json(MANUAL, {})
    figures = load_json(os.path.join(PE, "part_figures.json"), {})

    started = time.time()
    say("=" * 72)
    say(f"FULL LATEX EXTRACTION  ·  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    say(f"model={MODEL}  batch={args.batch_size}  budget=${args.budget:.2f}  workers={MAX_WORKERS}")

    if args.ids:
        wanted = {x.strip() for x in args.ids.split(",") if x.strip()}
        todo = [bank[i] for i in wanted if i in bank and i not in store]
    else:
        todo = [q for q in bank_list if q["id"] not in store]
    if args.limit:
        todo = todo[:args.limit]

    # A question whose source crops are missing can never be extracted honestly.
    # It goes to manual review up front rather than being sent to the model.
    skipped: list[dict] = []
    runnable: list[dict] = []
    for q in todo:
        miss = missing_sources(q)
        if miss:
            manual[q["id"]] = [f"source crop missing for {p}" for p in miss]
            skipped.append(q)
        else:
            runnable.append(q)

    say(f"bank={len(bank)}  already stored={len(store)}  to convert={len(runnable)}"
        + (f"  skipped (no source image)={len(skipped)}" if skipped else ""))
    say("")

    if not args.verify_only and runnable:
        key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
        if not key:
            raise SystemExit("ANTHROPIC_API_KEY not set")
        client = anthropic.Anthropic(api_key=key, max_retries=4, timeout=300.0)

        batches = [runnable[i:i + args.batch_size]
                   for i in range(0, len(runnable), args.batch_size)]
        stopped_for_budget = False
        for n, batch in enumerate(batches, 1):
            projected = spend() + per_question() * len(batch)
            if projected > args.budget:
                say(f"STOPPING at a clean batch boundary before batch {n}: the next "
                    f"{len(batch)} questions would project ${projected:.2f}, over the "
                    f"${args.budget:.2f} ceiling. Everything converted so far is saved "
                    f"and usable.")
                stopped_for_budget = True
                break

            t0 = time.time()
            errors = extract_batch(client, batch, store, figures)
            ids = [q["id"] for q in batch]
            repair({i: store[i] for i in ids if i in store})
            save_json(OUT, store)
            probe = probe_and_review(store, [i for i in ids if i in store], review)
            save_json(REVIEW, review)

            assemble.reload_stores()
            flagged = review_flagged(review)
            fig_store = assemble.figure_store()
            ok = 0
            for qid in ids:
                if qid not in store:
                    continue
                problems = verify_question(qid, store, bank, fig_store, flagged)
                if problems:
                    manual[qid] = problems
                else:
                    manual.pop(qid, None)
                    ok += 1
            for qid, msg in errors:
                manual[qid] = [f"extraction call failed — {msg}"]
            save_json(MANUAL, manual)

            elapsed = time.time() - started
            say(f"batch {n}/{len(batches)}  ({len(batch)} questions)"
                f"   converted+verified {ok}"
                f"   flagged {len(batch) - ok}"
                f"   fragments probed {probe['fragments']}"
                f"   compile failures {len(probe['failures'])}"
                f"   cost so far ${spend():.2f}"
                f"   elapsed {elapsed / 60:.1f} min"
                f"   ({time.time() - t0:.0f}s this batch)")
            for qid, msg in errors[:3]:
                say(f"    ERROR {qid}: {msg}")

        if stopped_for_budget:
            say("")

    # ----------------------------------------------------------------- final
    # A --verify-only pass re-probes the WHOLE store into a fresh review, so a
    # failure fixed since it was recorded stops being reported. (A normal run
    # only probes the batches it extracted, and accumulates.)
    if args.verify_only and store:
        review = blank_review()
        repaired = repair(store)
        if repaired:
            say(f"deterministic repair fixed {repaired} stored fragments")
            save_json(OUT, store)
        probe = probe_and_review(store, list(store), review)
        say(f"re-probed {probe['fragments']} fragments, "
            f"{len(probe['failures'])} compile failures")
        save_json(REVIEW, review)

    assemble.reload_stores()
    fig_store = assemble.figure_store()
    flagged = review_flagged(review)
    verified, rejected = [], {}
    for qid in sorted(store):
        problems = verify_question(qid, store, bank, fig_store, flagged)
        if problems:
            rejected[qid] = problems
        else:
            verified.append(qid)
    for qid, reasons in rejected.items():
        manual[qid] = reasons
    for qid in verified:
        manual.pop(qid, None)
    save_json(MANUAL, manual)
    save_json(OUT, store)
    save_json(REVIEW, review)

    # The subset the paper generator must not select: a sub-part needs a diagram
    # (a grid to draw on, axes to sketch on, a construction line) that no crop
    # resolves for. Those typeset perfectly and are unanswerable, so they are
    # kept out of the pool rather than printed. Everything else on the manual
    # list is a quality note, not a reason to withhold the question.
    unrenderable = sorted(
        qid for qid in store
        if qid in bank and unresolved_diagrams(bank[qid], store[qid], fig_store)
    )
    save_json(UNRENDERABLE, unrenderable)

    say("")
    say("-" * 72)
    say(f"questions in store        : {len(store)} / {len(bank)}")
    say(f"VERIFIED (shippable)      : {len(verified)}")
    say(f"needs manual review       : {len(manual)}")
    say(f"withheld from the pool    : {len(unrenderable)} (diagram cannot be printed)")
    say(f"fragments compile-checked : {review['fragmentsChecked']}")
    say(f"compile failures          : {len(review['compileFailures'])}")
    say(f"low / medium confidence   : {len(review['lowConfidence'])} / {len(review['mediumConfidence'])}")
    say(f"API calls this run        : {_usage['calls']}   cost ${spend():.2f}"
        + (f"  (${per_question():.3f}/question)" if _usage['calls'] else ""))
    say(f"total elapsed             : {(time.time() - started) / 60:.1f} min")
    say(f"-> {os.path.relpath(OUT)}")
    say(f"-> {os.path.relpath(MANUAL)}")


if __name__ == "__main__":
    main()
