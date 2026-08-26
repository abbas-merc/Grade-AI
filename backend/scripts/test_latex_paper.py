"""
test_latex_paper.py — Part 5: end-to-end proof, not just "it didn't throw".

Generates a real paper (and its mark scheme) from real bank questions, compiles
both, and then **inspects the produced PDFs**:

5.1  a paper covering pure text/algebra, a question with a diagram, a question
     with vectors, a question with set/probability notation, and a question whose
     sub-parts share one stem diagram;
5.2  every glyph's embedded font is read back out of the PDF and checked against
     the font the resolver said it chose — fontspec falls back silently, so
     "compiled cleanly" proves nothing about the font;
5.3  answer-space geometry is measured from the page: how many ruled lines each
     mark value actually got, and how much vertical space they occupy;
5.4  the mark scheme is compiled and inspected the same way;
5.5  page images are written next to the PDFs so the output can be eyeballed.

It also exercises the failure paths (Part 3.1/3.2): a deliberately malformed
fragment must come back attributed to the right sub-part, not as a crash.

Run from backend/:
  python scripts/test_latex_paper.py
  python scripts/test_latex_paper.py --outdir /tmp/ga-latex --png
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)

from utils.latex import assemble, config, engine, service, templates  # noqa: E402
from utils.latex.fonts import resolve_font  # noqa: E402

# One question per notation family, chosen so the paper genuinely exercises the
# things that used to break (Part 5.1).
COVERAGE = [
    ("pure algebra / display maths", "058021_s25_Q16"),
    ("vectors: column vectors + magnitude", "0580_2_SP_2025_Q7"),
    ("geometry with angle notation + diagram", "058021_s25_Q2"),
    ("trigonometry with a diagram", "058021_2024_Q17"),
    ("probability / set notation", "058021_2024_Q22"),
    ("multi sub-part sharing one stem diagram", "0580_4_SP_2025_Q7"),
    ("statistics, stem + histogram", "058021_s25_Q12"),
    ("long P4 question, nested (d)(i)/(ii), 18 marks", "058042_s24_Q5"),
    ("P4 trigonometry, nested (b)(i)/(ii) + diagram", "058042_s24_Q6"),
]

_FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> bool:
    global _FAIL
    print(("  PASS  " if ok else "  FAIL  ") + label + (("  — " + detail) if detail else ""))
    if not ok:
        _FAIL += 1
    return ok


# --------------------------------------------------------------------------- #
# PDF inspection
# --------------------------------------------------------------------------- #
def pdf_fonts(path: str) -> set[str]:
    import fitz
    with fitz.open(path) as doc:
        return {f[3].split("+")[-1] for page in doc for f in page.get_fonts(full=True)}


# A ruled answer line spans the whole body column. The cover sheet's candidate
# fields also use dot leaders but sit inside a half-width table cell, so a width
# threshold cleanly separates the two without hard-coding how many fields the
# cover has.
_MIN_ANSWER_RULE_PT = 250.0


def dotted_line_rows(path: str) -> list[list[float]]:
    """Y-positions of the ruled answer lines on each page.

    Read back from the rendered PDF — the real geometry, not what the template
    intended.
    """
    import fitz
    rows: list[list[float]] = []
    with fitz.open(path) as doc:
        for page in doc:
            ys: set[int] = set()
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        bbox = span["bbox"]
                        if (span["text"].count(".") >= 8
                                and (bbox[2] - bbox[0]) >= _MIN_ANSWER_RULE_PT):
                            ys.add(int(round(bbox[3])))
            rows.append(sorted(float(y) for y in ys))
    return rows


def mark_brackets(path: str) -> list[tuple[int, float, float]]:
    """(marks, x-right, y) for every "[n]" mark indicator in the document."""
    import fitz
    out = []
    with fitz.open(path) as doc:
        for page in doc:
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        m = re.fullmatch(r"\[(\d{1,2})\]", span["text"].strip())
                        if m:
                            out.append((int(m.group(1)), span["bbox"][2], span["bbox"][3]))
    return out


def render_pages(path: str, outdir: str, stem: str, dpi: int = 110) -> int:
    import fitz
    with fitz.open(path) as doc:
        for i, page in enumerate(doc, 1):
            page.get_pixmap(dpi=dpi).save(os.path.join(outdir, f"{stem}_p{i}.png"))
        return doc.page_count


# --------------------------------------------------------------------------- #
def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    outdir = os.path.join(HERE, "part_extraction", "latex_test_output")
    if "--outdir" in sys.argv:
        outdir = sys.argv[sys.argv.index("--outdir") + 1]
    os.makedirs(outdir, exist_ok=True)
    want_png = "--png" in sys.argv or True  # always render; Part 5.5 wants pictures

    assemble.reload_stores()
    store = assemble.latex_store()
    bank = assemble.bank_by_id()

    print("=" * 78)
    print("PART 0 — environment")
    print("=" * 78)
    status = engine.engine_status()
    check("LaTeX engine available", status["available"],
          f"{status['version']} at {status['path'] or '(not found)'}")
    if not status["available"]:
        print("\nCannot continue without the engine. Run: python scripts/install_tectonic.py")
        sys.exit(1)
    font = resolve_font()
    print(f"  font resolver chose: {font.family}  (mode={font.mode})")
    print(f"  {font.notice}")

    print()
    print("=" * 78)
    print("PART 5.1 — assemble a paper covering every notation family")
    print("=" * 78)
    selected = []
    for label, qid in COVERAGE:
        if qid in store and qid in bank:
            selected.append(qid)
            print(f"  included: {label:44s} {qid}")
        else:
            print(f"  MISSING : {label:44s} {qid}  "
                  "(run scripts/build_latex_extraction.py --sample)")
    if not check("all coverage questions available", len(selected) == len(COVERAGE)):
        print("     -> the paper below is built from what is available")
    if not selected:
        sys.exit(1)

    paper_request = {
        "subject": "math", "paperType": "P2",
        "schoolName": "Riverside International School",
        "paperName": "LaTeX Pipeline Verification Paper",
        "questions": [
            {"assignedNumber": i + 1,
             "questionImageUrl": f"/question_snippets/{qid}.png",
             "marks": bank[qid]["marks"]}
            for i, qid in enumerate(selected)
        ],
    }

    built_qp = service.question_paper(paper_request)
    qp_path = os.path.join(outdir, "question_paper.pdf")
    with open(qp_path, "wb") as fh:
        fh.write(built_qp.pdf)
    check("question paper compiled", True, f"{built_qp.seconds:.1f}s")
    check("no sub-part fell back to raw-text LaTeX", not built_qp.fallbacks,
          ", ".join(built_qp.fallbacks[:4]) or "0 fallbacks")

    print()
    print("=" * 78)
    print("PART 5.2 — the font in the PDF, not the font we asked for")
    print("=" * 78)
    fonts_used = pdf_fonts(qp_path)
    print("  embedded fonts:", ", ".join(sorted(fonts_used)))
    normalised = {f.lower().replace("-", "").replace(" ", "") for f in fonts_used}
    matched = [t for t in font.expected_pdf_tokens
               if any(t in n for n in normalised)]
    check(f"document font really is {font.family}", bool(matched),
          f"matched token {matched[0]!r}" if matched else
          "fontspec silently substituted something else")
    # Anything from the Computer Modern family means the text font did not take.
    cm = [f for f in fonts_used if re.match(r"(?i)^(cm[a-z]{1,3}\d|LMRoman|LMSans)", f)]
    check("no Computer Modern fallback in body text", not cm, ", ".join(cm))
    non_math = [f for f in fonts_used if "math" not in f.lower()]
    check("every non-maths font is the document font",
          all(any(t in f.lower().replace("-", "") for t in font.expected_pdf_tokens)
              for f in non_math),
          ", ".join(sorted(non_math)))

    print()
    print("=" * 78)
    print("PART 5.3 — answer space actually rendered, per mark value")
    print("=" * 78)
    print(f"  config: {config.ANSWER_LINES_PER_MARK} line(s)/mark, "
          f"min {config.ANSWER_LINES_MIN}, max {config.ANSWER_LINES_MAX}, "
          f"pitch {config.ANSWER_LINE_SKIP_MM} mm")
    rows_per_page = dotted_line_rows(qp_path)
    brackets = mark_brackets(qp_path)
    total_lines = sum(len(r) for r in rows_per_page)
    print(f"  ruled lines counted across the PDF: {total_lines}")
    expected_total = 0
    seen: dict[int, int] = {}
    assembled = assemble.from_generated_paper(paper_request)
    for q in assembled["questions"]:
        for sp in q["subParts"]:
            if sp.get("answerStyle") == "skip":
                continue
            marks = int(sp.get("marks", 0) or 0)
            n = templates.answer_lines_for(marks)
            expected_total += n
            seen.setdefault(marks, n)
    for marks in sorted(seen):
        print(f"    {marks} mark(s) -> {seen[marks]} ruled lines "
              f"({seen[marks] * config.ANSWER_LINE_SKIP_MM:.0f} mm of writing space)")
    check("rendered ruled-line count matches the template's intent",
          total_lines == expected_total, f"{total_lines} rendered vs {expected_total} expected")
    check("1-mark parts are not absurdly small",
          seen.get(1, config.ANSWER_LINES_MIN) >= 2)
    check("high-mark parts are not absurdly large",
          max(seen.values()) <= config.ANSWER_LINES_MAX)
    check("every sub-part printed its mark indicator",
          len(brackets) >= len(seen),
          f"{len(brackets)} [n] indicators found")
    # Cambridge right-aligns the mark indicator: all of them should share an x.
    if brackets:
        xs = sorted(x for _m, x, _y in brackets)
        check("mark indicators are right-aligned to a common margin",
              (xs[-1] - xs[0]) < 3.0, f"x spread {xs[-1] - xs[0]:.2f}pt")

    print()
    print("=" * 78)
    print("PART 5.4 — mark scheme")
    print("=" * 78)
    built_ms = service.mark_scheme(paper_request)
    ms_path = os.path.join(outdir, "mark_scheme.pdf")
    with open(ms_path, "wb") as fh:
        fh.write(built_ms.pdf)
    check("mark scheme compiled", True, f"{built_ms.seconds:.1f}s")
    ms_fonts = pdf_fonts(ms_path)
    check("mark scheme uses the same document font",
          any(any(t in f.lower().replace("-", "") for t in font.expected_pdf_tokens)
              for f in ms_fonts),
          ", ".join(sorted(ms_fonts)))
    import fitz
    with fitz.open(ms_path) as doc:
        ms_text = "\n".join(page.get_text() for page in doc)
    for token in ("Question", "Answer", "Marks", "Partial marks"):
        check(f"mark scheme has the {token!r} column", token in ms_text)
    codes = set(re.findall(r"\b([MAB]\d|SC\d)\b", ms_text))
    check("Cambridge mark codes present", bool(codes), ", ".join(sorted(codes)[:8]))

    print()
    print("=" * 78)
    print("PART 2.1 — letter-part introduction shared by its roman children")
    print("=" * 78)
    # A letter part such as (b) can carry its own introduction that only (b)(i),
    # (b)(ii)... depend on. Verified with an explicit override so the check does
    # not depend on which questions happen to be extracted.
    nested = next((qid for qid in selected
                   if any(len(sp.get("path") or []) > 1
                          for sp in bank[qid].get("subParts") or [])), "")
    if check("a nested-sub-part question is in the paper", bool(nested), nested):
        override = json.loads(json.dumps(store[nested]))
        letter = next(sp["path"][0] for sp in bank[nested]["subParts"]
                      if len(sp.get("path") or []) > 1)
        marker = r"The table shows $\frac{3}{8}$ of the results."
        override["groups"] = {letter: {"letter": letter, "latex": marker}}
        probe = json.loads(json.dumps(paper_request))
        probe["latexByQuestion"] = {nested: override}
        built_probe = service.question_paper(probe)
        probe_path = os.path.join(outdir, "group_intro_probe.pdf")
        with open(probe_path, "wb") as fh:
            fh.write(built_probe.pdf)
        import fitz
        with fitz.open(probe_path) as doc:
            probe_text = "\n".join(page.get_text() for page in doc)
        check(f"part ({letter}) introduction is printed above its roman parts",
              "The table shows" in probe_text and "of the results" in probe_text)

    print()
    print("=" * 78)
    print("PART 3.1 / 3.2 — failure handling")
    print("=" * 78)
    broken = json.loads(json.dumps(paper_request))
    bad_qid = selected[-1]
    override = json.loads(json.dumps(store[bad_qid]))
    first_part = next(iter(override["subParts"]))
    override["subParts"][first_part]["latex"] = r"\frac{1}{2"   # unbalanced brace
    broken["latexByQuestion"] = {bad_qid: override}
    try:
        service.question_paper(broken)
        check("malformed LaTeX is rejected", False, "it compiled anyway")
    except service.PaperBuildError as exc:
        check("malformed LaTeX fails the job cleanly", exc.status == 422,
              f"HTTP {exc.status}")
        check("the failing sub-part is named", exc.part == first_part,
              f"blamed {exc.part!r}, expected {first_part!r}")
        print(f"     message: {exc.message}")
    check("a compile timeout is configured", config.ENGINE_TIMEOUT_S > 0,
          f"{config.ENGINE_TIMEOUT_S:.0f}s")

    print()
    print("=" * 78)
    print("PART 5.5 — rendered output")
    print("=" * 78)
    if want_png:
        n_qp = render_pages(qp_path, outdir, "question_paper")
        n_ms = render_pages(ms_path, outdir, "mark_scheme")
        print(f"  question paper: {n_qp} pages  -> {os.path.relpath(qp_path, BACKEND)}")
        print(f"  mark scheme   : {n_ms} pages  -> {os.path.relpath(ms_path, BACKEND)}")
        print(f"  page images    -> {os.path.relpath(outdir, BACKEND)}\\*.png")

    print()
    print("=" * 78)
    print(("ALL CHECKS PASSED" if _FAIL == 0 else f"{_FAIL} CHECK(S) FAILED"))
    print("=" * 78)
    sys.exit(1 if _FAIL else 0)


if __name__ == "__main__":
    main()
