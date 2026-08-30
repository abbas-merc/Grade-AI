"""
utils/latex/templates.py — Assembled-paper dict -> XeLaTeX source.

Two templates, one geometry:

* :func:`question_paper_tex` — the candidate-facing paper: cover formalities,
  Cambridge-style numbering (``1`` / ``(a)`` / ``(ii)``), diagrams anchored
  inside the sub-part that needs them, ruled answer space sized from the mark
  allocation, and a right-aligned ``[3]`` on the final answer line.
* :func:`mark_scheme_tex` — the examiner-facing scheme in Cambridge's four-column
  shape (Question | Answer | Marks | Partial marks), same font, same maths.

Both are generated **programmatically** from a plain dict (see the module
docstring of :mod:`utils.latex.assemble` for its shape) — no .tex is ever
hand-edited per paper.

Page-break policy (Part 2.1, final bullet). A sub-part's text, its diagram and
its answer space must never be split across a page. Every block whose estimated
height fits inside ``ATOMIC_MAX_PAGE_FRACTION`` of the text block is emitted
inside a ``minipage``, which LaTeX physically cannot break. A block taller than
that cannot be kept whole by any mechanism, so it is emitted as flowing text
preceded by ``\\needspace`` — it still starts with room for its opening lines
instead of orphaning one line at a page foot.
"""
from __future__ import annotations

import math
import os

from . import config
from .fonts import FontChoice, resolve_font
from .latexify import escape_text

MM_PER_PT = 25.4 / 72.27
A4_HEIGHT_MM = 297.0
A4_WIDTH_MM = 210.0


def _text_block_mm() -> tuple[float, float]:
    """(width, height) of the printable text block, in millimetres."""
    width = A4_WIDTH_MM - 2 * config.PAGE_MARGIN_MM
    height = A4_HEIGHT_MM - config.PAGE_TOP_MARGIN_MM - config.PAGE_BOTTOM_MARGIN_MM
    # The running header and footer live inside the margins, but reserve a little
    # so the estimator is conservative rather than optimistic.
    return width, height - 14.0


def answer_lines_for(marks: int) -> int:
    """Ruled lines a sub-part worth ``marks`` gets.

    ``ANSWER_LINES_PER_MARK`` lines per mark, clamped to [MIN, MAX]. At the
    shipped defaults (2 per mark, min 2, max 12) a 1-mark part gets 2 lines and a
    6-mark part gets 12 — generous enough for real working without a 1-mark
    question owning half a page.
    """
    raw = int(marks or 0) * config.ANSWER_LINES_PER_MARK
    return max(config.ANSWER_LINES_MIN, min(config.ANSWER_LINES_MAX, raw))


# --------------------------------------------------------------------------- #
# Height estimation (drives the atomic / flowing decision)
# --------------------------------------------------------------------------- #
def _chars_per_line(width_mm: float) -> float:
    """Rough characters per line for the body font at the configured size."""
    # Century Gothic is wide: ~0.55 em average advance. em = font size in pt.
    em_mm = config.BODY_FONT_PT * MM_PER_PT
    return max(20.0, width_mm / (0.55 * em_mm))


def _baseline_mm() -> float:
    return config.BODY_FONT_PT * 1.25 * MM_PER_PT


def estimate_height_mm(latex: str, width_mm: float, *, answer_lines: int = 0,
                       image_height_mm: float = 0.0) -> float:
    """Conservative height of one rendered block."""
    plain = (latex or "").replace("\\\\", " ")
    lines = max(1, math.ceil(len(plain) / _chars_per_line(width_mm)))
    # Each explicit line break and each display-maths block costs an extra line.
    lines += (latex or "").count("\\\\") + 2 * (latex or "").count("\\[")
    text = lines * _baseline_mm()
    answers = answer_lines * config.ANSWER_LINE_SKIP_MM
    if answer_lines:
        answers += config.ANSWER_SPACE_TOP_MM
    return text + answers + image_height_mm + 4.0


# --------------------------------------------------------------------------- #
# Preamble
# --------------------------------------------------------------------------- #
def _preamble(font: FontChoice, build_dir: str, *, landscape: bool = False) -> str:
    geo = (
        "\\usepackage[a4paper,"
        f"left={config.PAGE_MARGIN_MM}mm,right={config.PAGE_MARGIN_MM}mm,"
        f"top={config.PAGE_TOP_MARGIN_MM}mm,bottom={config.PAGE_BOTTOM_MARGIN_MM}mm,"
        "headsep=6mm,footskip=10mm]{geometry}"
    )
    # unicode-math supersedes amssymb (loading both makes them fight over the
    # same symbol names), so only one of the two is ever pulled in.
    symbols = "" if config.MATCH_MATH_TO_TEXT_FONT else "\\usepackage{amssymb}"
    return "\n".join([
        "\\documentclass[%gpt,a4paper]{article}" % config.BODY_FONT_PT,
        "\\usepackage{fontspec}",
        "\\usepackage{amsmath}",
        symbols,
        geo,
        "\\usepackage{graphicx}",
        "\\usepackage{enumitem}",
        "\\usepackage{needspace}",
        "\\usepackage{array}",
        "\\usepackage{longtable}",
        "\\usepackage{xcolor}",
        "\\usepackage{fancyhdr}",
        font.preamble(build_dir),
        "",
        "% --- layout lengths (all driven by utils/latex/config.py) ---",
        "\\newlength{\\gaLabelW}\\setlength{\\gaLabelW}{%gmm}" % config.SUBPART_LABEL_WIDTH_MM,
        "\\newlength{\\gaAnswerSkip}\\setlength{\\gaAnswerSkip}{%gmm}" % config.ANSWER_LINE_SKIP_MM,
        "\\newlength{\\gaAnswerTop}\\setlength{\\gaAnswerTop}{%gmm}" % config.ANSWER_SPACE_TOP_MM,
        "\\setlength{\\parindent}{0pt}",
        "\\setlength{\\parskip}{2pt}",
        "",
        "% --- Cambridge-style ruled answer lines -----------------------------",
        "% [s] alignment is what lets \\dotfill actually stretch to the full width;",
        "% the default (centred) form splits the stretch with \\makebox's own glue.",
        "\\newcommand{\\gaLine}[1]{\\par\\vspace{\\gaAnswerSkip}%",
        "  \\noindent\\makebox[#1][s]{\\dotfill}}",
        "\\newcommand{\\gaLineMarks}[2]{\\par\\vspace{\\gaAnswerSkip}%",
        "  \\noindent\\makebox[#1][s]{\\dotfill\\hspace{0.8em}\\textbf{[#2]}}}",
        "\\newcommand{\\gaMarksOnly}[2]{\\par\\vspace{1mm}%",
        "  \\noindent\\makebox[#1][s]{\\hfill\\textbf{[#2]}}}",
        "\\newcommand{\\gaBlank}[1]{\\par\\vspace{#1mm}}",
        "",
        "% --- question / sub-part blocks -------------------------------------",
        "% Args: #1 label, #2 left indent (mm), #3 label gutter width (mm).",
        "% The label is \\llap-ed into the gutter that \\leftskip opens, which is what",
        "% lets a question number and its first part label share one line",
        "% (\"3   (a)   Calculate ...\") exactly as Cambridge prints them.",
        "% Flowing variant: a body that must break across pages keeps its",
        "% indentation on the next page because \\leftskip is a paragraph property.",
        "\\newenvironment{gapartflow}[3]%",
        "  {\\par\\addvspace{2.5mm}\\begingroup",
        "   \\setlength{\\leftskip}{\\dimexpr#2mm+#3mm\\relax}%",
        "   \\noindent\\llap{\\makebox[#3mm][l]{#1}}\\ignorespaces}%",
        "  {\\par\\endgroup}",
        "% Atomic variant: identical geometry inside a minipage, which LaTeX",
        "% cannot split — the guarantee that text, diagram and answer space stay",
        "% on one page.",
        "\\newenvironment{gapartatomic}[3]%",
        "  {\\par\\addvspace{2.5mm}\\noindent\\begin{minipage}{\\linewidth}\\begingroup",
        "   \\setlength{\\leftskip}{\\dimexpr#2mm+#3mm\\relax}%",
        "   \\noindent\\llap{\\makebox[#3mm][l]{#1}}\\ignorespaces}%",
        "  {\\par\\endgroup\\end{minipage}\\par}",
        "",
        "% --- diagram: pre-computed left pad centres it without overflowing ---",
        "\\newcommand{\\gaFigure}[3]{\\par\\vspace{2mm}%",
        "  \\noindent\\hspace*{#2mm}\\includegraphics[width=#3mm]{#1}\\par\\vspace{2mm}}",
        "",
        "\\pagestyle{fancy}\\fancyhf{}",
        "\\renewcommand{\\headrulewidth}{0pt}",
        "\\renewcommand{\\footrulewidth}{0pt}",
    ])


def probe_preamble(build_dir: str, font: FontChoice | None = None) -> str:
    """The document preamble on its own, for compile-checking loose fragments.

    Uses exactly the packages and font setup the real templates use, so a
    fragment that passes the probe cannot then fail inside a real paper.
    Font files are staged into ``build_dir`` as a side effect.
    """
    return _preamble(font or resolve_font(), build_dir)


# --------------------------------------------------------------------------- #
# Emitter — tracks line numbers so compile errors can be attributed
# --------------------------------------------------------------------------- #
class _Doc:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.anchors: list[tuple[int, str]] = []
        self.assets: dict[str, str] = {}

    def add(self, *lines: str) -> None:
        for line in lines:
            self.lines.append(line)

    def anchor(self, key: str) -> None:
        """Mark the current position so a later compile error names this block."""
        self.lines.append("%%GA-ANCHOR:" + key)
        self.anchors.append((len(self.lines), key))

    def asset(self, path: str) -> str:
        """Register an image and return the basename to reference it by."""
        base = os.path.basename(path)
        # Two different sub-parts can own same-named crops from different papers;
        # de-duplicate by prefixing when the basename is already taken.
        if base in self.assets and os.path.abspath(self.assets[base]) != os.path.abspath(path):
            stem, ext = os.path.splitext(base)
            i = 2
            while f"{stem}_{i}{ext}" in self.assets:
                i += 1
            base = f"{stem}_{i}{ext}"
        self.assets[base] = path
        return base

    def source(self) -> str:
        return "\n".join(self.lines) + "\n"


# --------------------------------------------------------------------------- #
# Shared header pieces
# --------------------------------------------------------------------------- #
def _minutes(total_marks: int) -> int:
    raw = int(round(total_marks * config.MINUTES_PER_MARK / 15.0) * 15)
    return max(raw, 15)


def _format_time(minutes: int) -> str:
    hours, mins = divmod(int(minutes), 60)
    parts = []
    if hours:
        parts.append(f"{hours} hour" + ("s" if hours != 1 else ""))
    if mins:
        parts.append(f"{mins} minute" + ("s" if mins != 1 else ""))
    return " ".join(parts) or "0 minutes"


def _running_footer(paper: dict) -> list[str]:
    code = escape_text(paper.get("paperCode") or "")
    session = escape_text(paper.get("session") or "")
    left = "~".join(x for x in (code, session) if x)
    return [
        "\\fancyfoot[L]{\\footnotesize\\color{gray}" + left + "}",
        "\\fancyfoot[C]{\\footnotesize\\thepage}",
        "\\fancyfoot[R]{\\footnotesize\\color{gray}" +
        escape_text(paper.get("schoolName") or "") + "}",
    ]


def _title_block(doc: _Doc, paper: dict, subtitle: str) -> None:
    school = escape_text(paper.get("schoolName") or "")
    title = escape_text(paper.get("paperName") or paper.get("title") or
                        "Custom Practice Paper")
    subject = escape_text(paper.get("subjectLabel") or "Mathematics")
    code = escape_text(paper.get("paperCode") or "")
    session = escape_text(paper.get("session") or "")
    total = int(paper.get("totalMarks", 0) or 0)
    minutes = int(paper.get("timeMinutes") or _minutes(total))

    doc.add(r"\begin{center}")
    if school:
        doc.add(r"{\large\bfseries " + school + r"}\\[1mm]")
    doc.add(r"{\LARGE\bfseries " + title + r"}\\[1.5mm]")
    doc.add(r"{\large " + subject + r"}\\[1mm]")
    meta = "~~$\\cdot$~~".join(x for x in (code, session, subtitle) if x)
    if meta:
        doc.add(r"{\small\color{gray} " + meta + r"}\\[1mm]")
    doc.add(r"{\small " + f"{total} marks" + r"~~$\cdot$~~" +
            escape_text(_format_time(minutes)) + r"}")
    doc.add(r"\end{center}", r"\vspace{2mm}")


def _cover(doc: _Doc, paper: dict) -> None:
    """Candidate-details grid + instructions — the real-exam formalities."""
    width, _ = _text_block_mm()
    # Two p-columns plus their inter-column padding and three vertical rules must
    # add up to exactly the text width, or the box overflows into the margin.
    # tabcolsep is pinned so the arithmetic is exact rather than approximate.
    tabcolsep_mm = 4 * MM_PER_PT
    half = (width - 4 * tabcolsep_mm - 3 * 0.4 * MM_PER_PT) / 2
    fill = r"\dotfill"
    doc.add(
        r"\setlength{\tabcolsep}{4pt}",
        r"\noindent\begin{tabular}{|p{%gmm}|p{%gmm}|}" % (half, half),
        r"\hline",
        r"\rule{0pt}{4.5ex}\footnotesize Candidate name~%s & \rule{0pt}{4.5ex}\footnotesize Centre / candidate number~%s \\[2mm]" % (fill, fill),
        r"\hline",
        r"\rule{0pt}{4.5ex}\footnotesize Class~%s & \rule{0pt}{4.5ex}\footnotesize Date~%s \\[2mm]" % (fill, fill),
        r"\hline",
        r"\end{tabular}",
        r"\par\vspace{5mm}",   # \par first: the tabular is still in horizontal
                               # mode, where \vspace would be silently dropped.
    )
    total = int(paper.get("totalMarks", 0) or 0)
    calc = ("You may use a calculator." if paper.get("calculatorAllowed")
            else "You must NOT use a calculator.")
    instructions = paper.get("instructions") or [
        "Answer all questions.",
        "Write your answers in the spaces provided.",
        "Write in dark blue or black pen.",
        calc,
        "Show all necessary working clearly; marks may be awarded for correct method.",
        "Give non-exact answers correct to 3 significant figures unless told otherwise.",
        f"The total mark for this paper is {total}.",
    ]
    doc.add(r"{\bfseries Instructions to candidates}", r"\vspace{1mm}")
    doc.add(r"\begin{itemize}[leftmargin=6mm,itemsep=0.6mm,topsep=0.6mm,parsep=0pt]")
    for item in instructions:
        doc.add(r"  \item " + escape_text(item))
    doc.add(r"\end{itemize}")
    doc.add(r"\vspace{2mm}\noindent\rule{\linewidth}{0.4pt}\vspace{1mm}")


# --------------------------------------------------------------------------- #
# Question paper
# --------------------------------------------------------------------------- #
def _figure_lines(doc: _Doc, image: dict | None, body_width_mm: float) -> tuple[list[str], float]:
    """(latex lines, height in mm) for an anchored diagram, or ([], 0)."""
    if not image or not image.get("path") or not os.path.exists(image["path"]):
        return [], 0.0
    width_mm = float(image.get("widthMm") or 0)
    height_mm = float(image.get("heightMm") or 0)
    if width_mm <= 0 or height_mm <= 0:
        width_mm, height_mm = measure_image(image["path"], body_width_mm)
    base = doc.asset(image["path"])
    # Pre-computed pad centres the figure inside the body column; computing it
    # here rather than with \centering keeps it inside the \leftskip gutter and
    # makes overflow impossible.
    pad = max(0.0, (body_width_mm - width_mm) / 2.0)
    return ([r"\gaFigure{%s}{%.1f}{%.1f}" % (base, pad, width_mm)], height_mm + 4.0)


def measure_image(path: str, body_width_mm: float) -> tuple[float, float]:
    """Display size (mm) for an image: fit the body column, cap the height."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            px_w, px_h = im.size
    except Exception:
        return body_width_mm * config.DIAGRAM_WIDTH_FRACTION, config.DIAGRAM_MAX_HEIGHT_MM
    if px_w <= 0 or px_h <= 0:
        return body_width_mm * config.DIAGRAM_WIDTH_FRACTION, config.DIAGRAM_MAX_HEIGHT_MM
    width = body_width_mm * config.DIAGRAM_WIDTH_FRACTION
    height = width * px_h / px_w
    if height > config.DIAGRAM_MAX_HEIGHT_MM:
        height = config.DIAGRAM_MAX_HEIGHT_MM
        width = height * px_w / px_h
    width = max(config.DIAGRAM_MIN_WIDTH_MM, min(width, body_width_mm))
    return width, height


def _answer_space(body_width_mm: float, marks: int, style: str,
                  lines: int | None) -> list[str]:
    """Ruled / blank answer space, ending with the right-aligned mark total."""
    if style == "skip":
        # A group header ("(b)" above its own (i)/(ii)) owns no marks and no
        # writing space — printing "[0]" under it would be nonsense.
        return []
    n = int(lines) if lines is not None else answer_lines_for(marks)
    width = "%.1fmm" % body_width_mm
    out = [r"\vspace{\gaAnswerTop}"]
    if style == "none":
        out.append(r"\gaMarksOnly{%s}{%d}" % (width, marks))
        return out
    if style == "blank":
        out.append(r"\gaBlank{%.1f}" % (n * config.ANSWER_LINE_SKIP_MM))
        out.append(r"\gaMarksOnly{%s}{%d}" % (width, marks))
        return out
    for _ in range(max(0, n - 1)):
        out.append(r"\gaLine{%s}" % width)
    out.append(r"\gaLineMarks{%s}{%d}" % (width, marks))
    return out


def _emit_block(doc: _Doc, *, key: str, label: str, indent_mm: float,
                label_width_mm: float, body: list[str], height_mm: float) -> None:
    """Emit one label+body block, atomic when it can be kept whole."""
    _, page_h = _text_block_mm()
    atomic = height_mm <= config.ATOMIC_MAX_PAGE_FRACTION * page_h
    env = "gapartatomic" if atomic else "gapartflow"
    doc.anchor(key)
    if not atomic:
        doc.add(r"\needspace{%d\baselineskip}" % config.NEEDSPACE_FALLBACK_LINES)
    doc.add(r"\begin{%s}{%s}{%.1f}{%.1f}" % (env, label, indent_mm, label_width_mm))
    doc.add(*body)
    doc.add(r"\end{%s}" % env)


def question_paper_tex(paper: dict, build_dir: str,
                       font: FontChoice | None = None) -> tuple[str, dict[str, str], list[tuple[int, str]]]:
    """Render the question paper. Returns (tex source, assets, anchors)."""
    font = font or resolve_font()
    doc = _Doc()
    width_mm, _ = _text_block_mm()

    doc.add(_preamble(font, build_dir))
    doc.add(*_running_footer(paper))
    doc.add(r"\begin{document}")
    # \raggedright belongs inside the document body: issued in the preamble it is
    # undone by the class's own \normalsize setup at \begin{document}, and the
    # paper silently comes out justified with stretched inter-word spaces.
    doc.add(r"\raggedright")
    _title_block(doc, paper, "Question Paper")
    _cover(doc, paper)

    qlw = config.QUESTION_LABEL_WIDTH_MM
    slw = config.SUBPART_LABEL_WIDTH_MM

    for q_index, q in enumerate(paper.get("questions", [])):
        number = q.get("number")
        q_key = str(q.get("key") or f"Q{number}")
        num_label = r"\textbf{%s}" % escape_text(str(number))
        if q_index:
            doc.add(r"\par\addvspace{%gmm}" % config.QUESTION_GAP_MM)

        intro = q.get("intro") or {}
        intro_latex = (intro.get("latex") or "").strip()
        sub_parts = list(q.get("subParts") or [])

        # A bank question with no lettered parts arrives as one unlabelled
        # sub-part; collapse it so the body sits directly beside the question
        # number rather than being indented as if it were a part (a).
        if (len(sub_parts) == 1 and not (sub_parts[0].get("label") or "").strip()
                and not intro_latex and not intro.get("image")):
            only = sub_parts[0]
            body_w = width_mm - qlw
            fig, fig_h = _figure_lines(doc, only.get("image"), body_w)
            latex = (only.get("latex") or "").strip()
            marks = int(only.get("marks", q.get("marks", 0)) or 0)
            lines = only.get("answerLines")
            body = ([latex] if latex else []) + fig + _answer_space(
                body_w, marks, only.get("answerStyle", "dotted"), lines)
            height = estimate_height_mm(
                latex, body_w,
                answer_lines=(int(lines) if lines is not None else answer_lines_for(marks)),
                image_height_mm=fig_h)
            _emit_block(doc, key=str(only.get("key") or only.get("partId") or q_key),
                        label=num_label, indent_mm=0.0, label_width_mm=qlw,
                        body=body, height_mm=height)
            continue

        # A stem (shared context / diagram) sits on the question-number line.
        # Without one, the number instead shares a line with the first sub-part's
        # own label — "3   (a)   Calculate ..." — which is how Cambridge sets it.
        pending_number = num_label
        if intro_latex or intro.get("image"):
            body_w = width_mm - qlw
            fig, fig_h = _figure_lines(doc, intro.get("image"), body_w)
            height = estimate_height_mm(intro_latex, body_w, image_height_mm=fig_h)
            _emit_block(doc, key=q_key, label=num_label, indent_mm=0.0,
                        label_width_mm=qlw,
                        body=([intro_latex] if intro_latex else []) + fig,
                        height_mm=height)
            pending_number = ""

        pending_group = ""
        for sp in sub_parts:
            depth = int(sp.get("depth", 0) or 0)
            label = escape_text(sp.get("label") or "")
            nest = qlw + config.NEST_INDENT_MM * depth

            # A letter part that only groups its own roman children carries no
            # text of its own, so it is held back and printed in the same gutter
            # as the first child: "7  (a)  (i)  the median".
            if sp.get("isGroupHeader") and not (sp.get("latex") or "").strip() \
                    and not sp.get("image"):
                pending_group = label
                continue

            # Everything held back occupies its natural column in the gutter, so
            # the number stays at the margin and each label keeps its indent.
            prefixes: list[str] = []
            if pending_number:
                prefixes.append(r"\makebox[%gmm][l]{%s}" % (qlw, pending_number))
            if pending_group:
                prefixes.append(r"\makebox[%gmm][l]{%s}" % (nest - qlw, pending_group))
            if prefixes:
                indent = 0.0 if pending_number else qlw
                label = "".join(prefixes) + label
                label_w = nest + slw - indent
            else:
                indent = nest
                label_w = slw
            pending_number = pending_group = ""

            sp_body_w = width_mm - indent - label_w
            fig, fig_h = _figure_lines(doc, sp.get("image"), sp_body_w)
            latex = (sp.get("latex") or "").strip()
            marks = int(sp.get("marks", 0) or 0)
            lines = sp.get("answerLines")
            body = ([latex] if latex else []) + fig + _answer_space(
                sp_body_w, marks, sp.get("answerStyle", "dotted"), lines)
            height = estimate_height_mm(
                latex, sp_body_w,
                answer_lines=(int(lines) if lines is not None else answer_lines_for(marks)),
                image_height_mm=fig_h)
            _emit_block(doc,
                        key=str(sp.get("key") or sp.get("partId") or f"Q{number}{sp.get('label','')}"),
                        label=label, indent_mm=indent, label_width_mm=label_w,
                        body=body, height_mm=height)

        if pending_number:  # a question that turned out to have no sub-parts
            doc.anchor(q_key)
            doc.add(r"\par\addvspace{4mm}\noindent" + pending_number + r"\par")

    doc.add(r"\vfill", r"\begin{center}\footnotesize\color{gray}End of paper\end{center}")
    doc.add(r"\end{document}")
    return doc.source(), doc.assets, doc.anchors


# --------------------------------------------------------------------------- #
# Mark scheme (Part 4.1)
# --------------------------------------------------------------------------- #
def mark_scheme_tex(paper: dict, build_dir: str,
                    font: FontChoice | None = None) -> tuple[str, dict[str, str], list[tuple[int, str]]]:
    """Render the mark scheme in Cambridge's four-column layout."""
    font = font or resolve_font()
    doc = _Doc()
    width_mm, _ = _text_block_mm()
    # Question | Answer | Marks | Partial marks — Cambridge's own column set.
    col_q, col_marks = 18.0, 14.0
    col_answer = (width_mm - col_q - col_marks) * 0.42
    col_partial = (width_mm - col_q - col_marks) * 0.58 - 6.0

    doc.add(_preamble(font, build_dir))
    doc.add(*_running_footer(paper))
    doc.add(r"\begin{document}")
    doc.add(r"\raggedright")
    _title_block(doc, paper, "Mark Scheme")
    doc.add(
        r"{\small\color{gray}Mark types: \textbf{M} method \quad \textbf{A} accuracy "
        r"(depends on the corresponding M) \quad \textbf{B} independent \quad "
        r"\textit{ft} follow through \quad \textit{cao} correct answer only \quad "
        r"\textit{oe} or equivalent}",
        r"\vspace{3mm}",
    )

    doc.add(r"\renewcommand{\arraystretch}{1.25}")
    # >{\raggedright\arraybackslash} — a p-column justifies its own text no matter
    # what the surrounding document does, and justified mark-scheme cells come out
    # with stretched, hard-to-scan word spacing.
    col = r">{\raggedright\arraybackslash}p{%gmm}"
    doc.add(r"\begin{longtable}{|%s|%s|%s|%s|}" %
            (col % col_q, col % col_answer, col % col_marks, col % col_partial))
    header = (r"\hline \textbf{Question} & \textbf{Answer} & \textbf{Marks} & "
              r"\textbf{Partial marks} \\ \hline")
    doc.add(header, r"\endfirsthead", header, r"\endhead")

    for q in paper.get("questions", []):
        number = q.get("number")
        # Cambridge's own mark-scheme text for a question the LaTeX extraction has
        # not covered. Printed once, on that question's first row, so an
        # unconverted question still shows a real mark scheme instead of nothing.
        raw_scheme = (q.get("rawMarkScheme") or "").strip()
        for sp in q.get("subParts") or []:
            # A group header ("(a)" above its own romans) is a layout device on
            # the question paper; it owns no marks and has no place in the scheme.
            if sp.get("isGroupHeader"):
                continue
            # The scheme uses the FULL Cambridge reference — "7(a)(ii)", not the
            # question paper's indented "(ii)" — so a row is unambiguous on its own.
            raw_label = sp.get("msLabel") or sp.get("label") or ""
            # "(whole)" is the bank's marker for a question with no lettered
            # parts; the scheme just calls that row by its question number.
            label = "" if raw_label.strip() == "(whole)" else escape_text(raw_label)
            qref = f"{number}{label}" if label else str(number)
            # Never fall back to the QUESTION text here: printed in the Answer
            # column it reads as the answer, which is worse than an empty cell.
            answer = (sp.get("answerLatex") or "").strip() or "--"
            marks = int(sp.get("marks", 0) or 0)
            points = sp.get("markPoints") or []
            if points:
                partial = r" \newline ".join(
                    (r"\textbf{%s} " % escape_text(p.get("code", "")) if p.get("code") else "")
                    + (p.get("latex") or "").strip()
                    for p in points
                )
            else:
                partial = (sp.get("partialLatex") or "").strip()
            if not partial and raw_scheme:
                partial, raw_scheme = raw_scheme, ""
            doc.anchor(str(sp.get("key") or sp.get("partId") or qref))
            doc.add(r"%s & %s & %d & %s \\ \hline" % (qref, answer, marks, partial or ""))

    doc.add(r"\end{longtable}")
    doc.add(r"\end{document}")
    return doc.source(), doc.assets, doc.anchors
