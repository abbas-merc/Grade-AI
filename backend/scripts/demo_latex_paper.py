"""
demo_latex_paper.py — DEMO ONLY. Generate a paper from the verified-LaTeX subset.

Why this exists
---------------
Only part of the 538-question bank has been through the LaTeX extraction
(``scripts/build_latex_extraction.py``). A paper containing an unextracted
question still generates — it falls back to raw-text LaTeX — which is honest in
production (the fallback count rides back on ``X-GradeAI-Latex-Fallbacks``) but
useless for a demo, where every question on the page has to be the real thing.

This script builds a paper from **only** the questions whose extraction is
present and verified, and refuses to write a PDF if even one sub-part fell back.

Isolation (deliberate, do not remove)
-------------------------------------
* It is a CLI. The module raises on import, so no router, worker or app code can
  reach it even by accident — see the ``__name__`` guard below.
* It imports the production selection logic (``partlevel_selection.select_paper``)
  and the production typesetter (``utils.latex.service``) rather than
  reimplementing them, so what it demonstrates is what the app does. The *only*
  difference is the pool it is allowed to draw from.
* It changes nothing about ``/api/generate-paper*``. Real users keep the full
  bank, keep the fallback, and keep the fallback counter that tells them the
  bank's true state.

Run from backend/:
  python scripts/demo_latex_paper.py --audit                 # what is verified, and why not
  python scripts/demo_latex_paper.py --marks 50              # build the demo paper
  python scripts/demo_latex_paper.py --marks 40 --topics algebra,number
  python scripts/demo_latex_paper.py --marks 30 --paper-type P2 --difficulty easy
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys

if __name__ != "__main__":  # isolation gate — see the module docstring
    raise RuntimeError(
        "scripts/demo_latex_paper.py is a demo-only CLI and must not be imported "
        "by application code. The production path is routers/paper_generator.py."
    )

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
REPO = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)

from partlevel_selection import select_paper  # noqa: E402
from utils.latex import assemble, service  # noqa: E402
from utils.latex.engine import engine_status  # noqa: E402
from utils.latex.fonts import resolve_font  # noqa: E402
from utils.latex.latexify import validate_fragment  # noqa: E402

# The topic -> syllabus-section mapping the real endpoint uses. Imported, never
# copied, so the demo cannot drift from production topic semantics.
from routers.paper_generator import (  # noqa: E402
    _TOPIC_SECTIONS, _allowed_codes_from_topics,
)

PE = os.path.join(HERE, "part_extraction")
REVIEW_PATH = os.path.join(PE, "latex_review.json")
DEFAULT_OUTDIR = os.path.join(REPO, "demo")

# A stem crop whose OCR text is shorter than this is page furniture (the question
# number, a registration mark), not a scenario — those questions legitimately
# have no stem, so an empty stemLatex is correct rather than missing.
_MIN_MEANINGFUL_STEM_CHARS = 12


def _meaningful(text: str) -> bool:
    return len(re.sub(r"[^A-Za-z0-9]", "", text or "")) >= _MIN_MEANINGFUL_STEM_CHARS


def _review_flagged() -> set[str]:
    """Question ids the extraction's own review pass flagged as not shippable."""
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


# --------------------------------------------------------------------------- #
# Verification — what counts as "genuinely converted"
# --------------------------------------------------------------------------- #
def verify_question(qid: str, store: dict, bank: dict, figures: dict,
                    flagged: set[str]) -> list[str]:
    """Return the reasons `qid` is NOT demo-safe. Empty list == verified."""
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
    if _meaningful(stem_entry.get("text", "")) and not (extraction.get("stemLatex") or "").strip():
        problems.append("question stem exists in the source paper but was not extracted")

    # Same, for a letter part that carries its own introduction.
    groups = extraction.get("groups") or {}
    for gid, entry in (figures.get("groupStems") or {}).items():
        if not gid.startswith(qid + "_"):
            continue
        letter = gid[len(qid) + 1:]
        if _meaningful(entry.get("text", "")) and not ((groups.get(letter) or {}).get("latex") or "").strip():
            problems.append(f"letter part ({letter}) introduction was not extracted")

    # A sub-part the extractor saw a diagram in, whose crop does not resolve,
    # would print as text with the diagram silently gone. Correct LaTeX, wrong
    # question — so it is barred from the demo pool even though it compiles.
    for pid in unresolved_diagrams(question, extraction, figures):
        problems.append(f"{pid}: carries a diagram but no crop resolves for it")

    return problems


def unresolved_diagrams(question: dict, extraction: dict, figures: dict) -> list[str]:
    """Sub-parts the extractor said carry a diagram but whose crop won't resolve.

    Mirrors the image lookup ``assemble.from_partlevel_paper`` performs: the
    sub-part's own crop, then the question stem's figure, then any shared asset
    the sub-part belongs to.
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


def verified_pool() -> tuple[list[dict], dict[str, list[str]]]:
    """(bank records that are demo-safe, {rejected qid: reasons})."""
    assemble.reload_stores()
    store, bank, figures = assemble.latex_store(), assemble.bank_by_id(), assemble.figure_store()
    flagged = _review_flagged()
    pool, rejected = [], {}
    for qid in sorted(store):
        problems = verify_question(qid, store, bank, figures, flagged)
        if problems:
            rejected[qid] = problems
        else:
            pool.append(bank[qid])
    return pool, rejected


# --------------------------------------------------------------------------- #
# Paper construction — production selection logic, demo-restricted pool
# --------------------------------------------------------------------------- #
def build_paper_payload(pool: list[dict], *, topics: list[str], marks: int,
                        paper_type: str, difficulty: str, seed: int,
                        school: str, name: str, subject: str = "math") -> dict:
    """A payload shaped exactly like a ``POST /api/generate-paper/partlevel``
    response, so the same typesetter call the router makes renders it."""
    allowed = _allowed_codes_from_topics(topics)
    rng = random.Random(seed)
    result = select_paper(pool, allowed, marks, paper_type=paper_type,
                          difficulty=difficulty, shuffle=rng.shuffle)

    questions = []
    for number, q in enumerate(result["questions"], start=1):
        sub_parts = []
        for sp in q.get("subParts", []):
            sub_parts.append({
                "partId": sp.get("partId", ""), "label": sp.get("label", ""),
                "marks": int(sp.get("marks", 0) or 0),
                "syllabusCodes": sp.get("syllabusCodes", []) or [],
                "imageUrl": (sp.get("imageRefs") or [""])[0] and f"/question_parts/{sp['partId']}.png",
                "substituted": bool(sp.get("_sourceQuestion")
                                    and sp.get("_sourceQuestion") != q.get("id")),
            })
        questions.append({
            "assignedNumber": number,
            "originalPaperCode": q.get("paperCode", "") or "",
            "marks": int(q.get("marks", 0) or 0),
            "syllabusCodes": q.get("syllabusCodes", []) or [],
            "assembled": bool(q.get("assembled")),
            "subParts": sub_parts,
        })

    return {
        "paperId": f"demo-{seed}", "subject": subject, "paperType": paper_type,
        "schoolName": school, "paperName": name,
        "targetMarks": marks, "totalMarks": result["totalMarks"],
        "numQuestions": result["numQuestions"], "questions": questions,
        "warnings": result["warnings"], "log": result["log"],
    }


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def _write(path: str, data: bytes) -> str:
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def render_pages(pdf_path: str, outdir: str, stem: str, dpi: int = 110) -> int:
    import fitz
    os.makedirs(outdir, exist_ok=True)
    with fitz.open(pdf_path) as doc:
        for i, page in enumerate(doc, 1):
            page.get_pixmap(dpi=dpi).save(os.path.join(outdir, f"{stem}_p{i:02d}.png"))
        return doc.page_count


def pdf_report(path: str) -> dict:
    """Fonts, pages and ruled-line count read back out of the produced PDF."""
    import fitz
    fonts, rules = set(), 0
    with fitz.open(path) as doc:
        pages = doc.page_count
        for page in doc:
            for f in page.get_fonts(full=True):
                fonts.add(f[3].split("+")[-1])
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        bbox = span["bbox"]
                        if span["text"].count(".") >= 8 and (bbox[2] - bbox[0]) >= 250.0:
                            rules += 1
    return {"pages": pages, "fonts": sorted(fonts), "answerLines": rules}


def write_summary(path: str, ctx: dict) -> str:
    bank = assemble.bank_by_id()
    lines = [
        "# GradeAI — demo paper: what is actually in it",
        "",
        f"Generated {ctx['when']} by `backend/scripts/demo_latex_paper.py` "
        f"(demo-only CLI — not reachable from the app).",
        "",
        "## The paper",
        "",
        f"* **{ctx['numQuestions']} questions, {ctx['totalMarks']} marks** "
        f"(requested {ctx['targetMarks']}).",
        f"* Topics requested: {', '.join(ctx['topics'])}.",
        f"* Paper type: {ctx['paperType']}  ·  difficulty: {ctx['difficulty']}  "
        f"·  seed: {ctx['seed']} (re-run with the same seed for the same paper).",
        f"* Question paper: **{ctx['qpPages']} pages**, {ctx['answerLines']} ruled "
        f"answer lines.  Mark scheme: **{ctx['msPages']} pages**.",
        f"* Typeset by {ctx['engine']} in {ctx['qpSeconds']:.1f}s + {ctx['msSeconds']:.1f}s.",
        f"* Font embedded in the PDF: **{ctx['font']}** ({ctx['fontMode']}). "
        f"Fonts found in the file: {', '.join(ctx['qpFonts'])}.",
        "",
        "## Every question is real converted LaTeX — 0 fallbacks",
        "",
        f"* The pool this paper could draw from was **{ctx['poolSize']} questions "
        f"/ {ctx['poolMarks']} marks** — every one of them verified: LaTeX stored "
        "for every sub-part, every fragment structurally valid, question stem "
        "present where the source paper has one, nothing on the extraction "
        "review list.",
        "* The typesetter reports fallbacks per sub-part. This build reported "
        f"**{ctx['fallbacks']}**. The script refuses to write a PDF otherwise.",
        *([f"* {ctx['storeSize'] - ctx['poolSize']} extracted question(s) were held "
           "OUT of the demo pool, so the numbers above reconcile: "
           + "; ".join(f"`{qid}` — {why[0]}" for qid, why in ctx["rejected"].items())]
          if ctx["rejected"] else []),
        "",
        "## Questions in the paper",
        "",
        "| # | Source paper | Q | Marks | Sub-parts | Syllabus codes |",
        "|---|---|---|---|---|---|",
    ]
    for q in ctx["questions"]:
        qid = assemble.question_id_from_part_id(q["subParts"][0]["partId"]) if q["subParts"] else ""
        original = (bank.get(qid) or {}).get("originalQuestionNumber", "")
        lines.append(
            f"| {q['assignedNumber']} | {q['originalPaperCode'] or '—'} | {original} | "
            f"{q['marks']} | {len(q['subParts'])} | {', '.join(q['syllabusCodes']) or '—'} |")
    lines += ["", "## Topic coverage", ""]
    for section, detail in sorted(ctx["sections"].items()):
        lines.append(f"* **{section}** — {detail['marks']} marks "
                     f"({', '.join(sorted(detail['codes']))})")
    if ctx["warnings"]:
        lines += ["", "## Selector warnings", ""] + [f"* {w}" for w in ctx["warnings"]]
    lines += [
        "", "## What this demo does not show", "",
        f"* The rest of the bank. {ctx['bankSize']} questions exist; "
        f"{ctx['storeSize']} have been through LaTeX extraction so far. A paper "
        "generated from the whole bank in the app today would contain raw-text "
        "fallback questions for the remainder — correct symbols, but no "
        "reconstructed notation.",
        "* Production font. Century Gothic is licensed to this machine via "
        "Microsoft Office; a Linux server needs licensed files supplied at "
        "`GA_CENTURY_GOTHIC_DIR`, otherwise papers render in TeX Gyre Adventor.",
        "",
    ]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path


# --------------------------------------------------------------------------- #
def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Demo-only paper from verified-LaTeX questions.")
    ap.add_argument("--marks", type=int, default=50, help="target total marks (default 50)")
    ap.add_argument("--topics", default="", help="comma-separated topic chips; default: every topic present in the verified pool")
    ap.add_argument("--paper-type", default="both", choices=["P2", "P4", "both"])
    ap.add_argument("--difficulty", default="mixed", choices=["mixed", "easy", "medium", "hard"])
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--outdir", default=DEFAULT_OUTDIR)
    ap.add_argument("--school", default="Riverside International School")
    ap.add_argument("--name", default="Demo Practice Paper")
    ap.add_argument("--audit", action="store_true", help="print the verified pool and exit")
    ap.add_argument("--dry-run", action="store_true", help="select and report the mix, but do not typeset")
    ap.add_argument("--no-png", action="store_true", help="skip per-page PNG rendering")
    args = ap.parse_args()

    print("=" * 78)
    print("GradeAI demo paper — VERIFIED-LATEX QUESTIONS ONLY (demo path, not production)")
    print("=" * 78)

    pool, rejected = verified_pool()
    bank, store = assemble.bank_by_id(), assemble.latex_store()
    pool_marks = sum(int(q.get("marks", 0) or 0) for q in pool)
    print(f"bank: {len(bank)} questions   extraction stored for: {len(store)}   "
          f"verified & demo-safe: {len(pool)} ({pool_marks} marks)")
    if rejected:
        print(f"rejected from the demo pool: {len(rejected)}")
        for qid, why in rejected.items():
            print(f"   - {qid}: {why[0]}" + (f" (+{len(why) - 1} more)" if len(why) > 1 else ""))

    if args.audit:
        print("\nverified pool:")
        for q in sorted(pool, key=lambda x: x["id"]):
            print(f"   {q['id']:22s} {q.get('marks', 0):3d} marks  "
                  f"{len(q.get('subParts') or []):2d} parts  {q.get('difficulty', ''):6s} "
                  f"{','.join(q.get('syllabusCodes') or [])}")
        return 0

    if not pool:
        print("\nNo verified questions. Run scripts/build_latex_extraction.py first.")
        return 1

    topics = [t.strip() for t in args.topics.split(",") if t.strip()]
    if not topics:
        sections = {int(c[1:].split(".")[0]) for q in pool for c in (q.get("syllabusCodes") or [])
                    if len(c) > 1 and c[1:].split(".")[0].isdigit()}
        topics = sorted({name for name, secs in _TOPIC_SECTIONS.items()
                         if secs & sections and name != "calculus"})
    print(f"\ntopics: {', '.join(topics)}   target: {args.marks} marks   "
          f"type: {args.paper_type}   difficulty: {args.difficulty}   seed: {args.seed}")

    status = engine_status()
    if not status["available"]:
        print("\nLaTeX engine not available. Run: python scripts/install_tectonic.py")
        return 1
    font = resolve_font()
    print(f"engine: {status['version']}   font: {font.family} ({font.mode})")

    payload = build_paper_payload(
        pool, topics=topics, marks=args.marks, paper_type=args.paper_type,
        difficulty=args.difficulty, seed=args.seed, school=args.school, name=args.name)
    if not payload["questions"]:
        print("\nSelector produced no questions for those filters.")
        return 1
    print(f"selected: {payload['numQuestions']} questions, {payload['totalMarks']} marks")
    for w in payload["warnings"]:
        print("  warning:", w)
    for q in payload["questions"]:
        print(f"   {q['assignedNumber']:2d}. {q['originalPaperCode'] or '-':16s} "
              f"{q['marks']:3d} marks  {len(q['subParts'])} sub-part(s)  "
              f"{','.join(q['syllabusCodes'])}")
    if args.dry_run:
        covered = sorted({int(c[1:].split('.')[0]) for q in payload["questions"]
                          for c in q["syllabusCodes"] if c[1:].split('.')[0].isdigit()})
        print(f"\nsyllabus sections covered: {covered}   (dry run — nothing typeset)")
        return 0

    print("\ntypesetting...")
    try:
        qp = service.question_paper(payload, partlevel=True)
        ms = service.mark_scheme(payload, partlevel=True)
    except service.PaperBuildError as exc:
        print(f"\nBUILD FAILED [{exc.status}] {exc.message}"
              + (f"  (sub-part: {exc.part})" if exc.part else ""))
        return 1

    # The whole point of the demo pool. If this ever trips, the pool filter and
    # the typesetter disagree and the PDF must not be shipped as a demo.
    if qp.fallbacks or ms.fallbacks:
        print("\nABORTED: raw-text fallback used for "
              f"{sorted(set(qp.fallbacks) | set(ms.fallbacks))}. "
              "No PDF written — a demo paper must be 100% converted LaTeX.")
        return 1

    outdir = os.path.abspath(args.outdir)
    os.makedirs(outdir, exist_ok=True)
    qp_path = _write(os.path.join(outdir, "GradeAI_Demo_Question_Paper.pdf"), qp.pdf)
    ms_path = _write(os.path.join(outdir, "GradeAI_Demo_Mark_Scheme.pdf"), ms.pdf)
    with open(os.path.join(outdir, "demo_paper_payload.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)

    qp_info, ms_info = pdf_report(qp_path), pdf_report(ms_path)
    print(f"  question paper: {qp_info['pages']} pages, {qp_info['answerLines']} ruled "
          f"answer lines, fonts: {', '.join(qp_info['fonts'])}")
    print(f"  mark scheme   : {ms_info['pages']} pages, fonts: {', '.join(ms_info['fonts'])}")
    print(f"  fallbacks: {len(qp.fallbacks)}  (a demo paper must be 0)")

    expected = font.expected_pdf_tokens
    normalised = {f.lower().replace("-", "").replace(" ", "") for f in qp_info["fonts"]}
    font_ok = any(tok in n for tok in expected for n in normalised)
    cm = [f for f in qp_info["fonts"] if re.match(r"(?i)^(cm[a-z]{1,3}\d|LMRoman|LMSans)", f)]
    print(f"  document font is {font.family}: {'PASS' if font_ok else 'FAIL'}")
    print(f"  no Computer Modern fallback: {'PASS' if not cm else 'FAIL — ' + ', '.join(cm)}")

    if not args.no_png:
        pages_dir = os.path.join(outdir, "pages")
        n = render_pages(qp_path, pages_dir, "question_paper")
        n += render_pages(ms_path, pages_dir, "mark_scheme")
        print(f"  {n} page PNGs -> {pages_dir}")

    sections: dict[str, dict] = {}
    section_names = {1: "Number", 2: "Algebra and graphs", 3: "Coordinate geometry",
                     4: "Geometry", 5: "Mensuration", 6: "Trigonometry",
                     7: "Transformations and vectors", 8: "Probability", 9: "Statistics"}
    for q in payload["questions"]:
        for sp in q["subParts"]:
            for code in sp["syllabusCodes"]:
                sec = section_names.get(int(code[1:].split(".")[0]), code)
                entry = sections.setdefault(sec, {"marks": 0, "codes": set()})
                entry["codes"].add(code)
            if sp["syllabusCodes"]:
                sec = section_names.get(int(sp["syllabusCodes"][0][1:].split(".")[0]),
                                        sp["syllabusCodes"][0])
                sections[sec]["marks"] += sp["marks"]

    import datetime
    summary = write_summary(os.path.join(outdir, "DEMO_PAPER_SUMMARY.md"), {
        "when": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "numQuestions": payload["numQuestions"], "totalMarks": payload["totalMarks"],
        "targetMarks": payload["targetMarks"], "topics": topics,
        "paperType": args.paper_type, "difficulty": args.difficulty, "seed": args.seed,
        "qpPages": qp_info["pages"], "msPages": ms_info["pages"],
        "answerLines": qp_info["answerLines"], "qpFonts": qp_info["fonts"],
        "engine": status["version"], "qpSeconds": qp.seconds, "msSeconds": ms.seconds,
        "font": font.family, "fontMode": font.mode,
        "poolSize": len(pool), "poolMarks": pool_marks, "fallbacks": len(qp.fallbacks),
        "questions": payload["questions"], "sections": sections,
        "rejected": rejected,
        "warnings": payload["warnings"], "bankSize": len(bank), "storeSize": len(store),
    })

    print(f"\nwritten to {outdir}")
    for p in (qp_path, ms_path, summary):
        print("   ", os.path.basename(p))
    return 0


sys.exit(main())
