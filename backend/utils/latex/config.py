"""
utils/latex/config.py — Every tunable knob of the LaTeX typesetting pipeline.

Nothing in the template or the compiler hardcodes a magic number; each one lives
here as a named constant that can also be overridden from the environment, so a
school can retune answer-space generosity or margins without a code change.

Environment overrides use the ``GA_LATEX_`` prefix, e.g.::

    GA_LATEX_ANSWER_LINES_PER_MARK=3
    GA_LATEX_ENGINE_TIMEOUT_S=90
"""
from __future__ import annotations

import os


def _f(name: str, default: float) -> float:
    raw = (os.getenv(f"GA_LATEX_{name}") or "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _i(name: str, default: int) -> int:
    return int(_f(name, default))


def _s(name: str, default: str) -> str:
    return (os.getenv(f"GA_LATEX_{name}") or "").strip() or default


# --------------------------------------------------------------------------- #
# Answer space (Part 2.1)
# --------------------------------------------------------------------------- #
# How many ruled answer lines a sub-part gets, per mark. Calibrated against real
# 0580 papers: a 3-mark part is normally given ~6 writing lines plus the final
# answer line, i.e. two lines per mark. Clamped by MIN/MAX so a 1-mark part still
# gets somewhere to write and an 8-mark part does not consume a whole page.
ANSWER_LINES_PER_MARK = _i("ANSWER_LINES_PER_MARK", 2)
ANSWER_LINES_MIN = _i("ANSWER_LINES_MIN", 2)
ANSWER_LINES_MAX = _i("ANSWER_LINES_MAX", 12)
# Vertical pitch of one ruled answer line. Cambridge writing lines sit ~8.5 mm
# apart, which is what a 14–17 year old's handwriting needs.
ANSWER_LINE_SKIP_MM = _f("ANSWER_LINE_SKIP_MM", 8.5)
# Blank space above the first answer line (separates it from the question text).
ANSWER_SPACE_TOP_MM = _f("ANSWER_SPACE_TOP_MM", 3.0)

# --------------------------------------------------------------------------- #
# Page geometry
# --------------------------------------------------------------------------- #
PAGE_MARGIN_MM = _f("PAGE_MARGIN_MM", 20.0)
PAGE_TOP_MARGIN_MM = _f("PAGE_TOP_MARGIN_MM", 20.0)
PAGE_BOTTOM_MARGIN_MM = _f("PAGE_BOTTOM_MARGIN_MM", 20.0)
BODY_FONT_PT = _f("BODY_FONT_PT", 11.0)
# Width of the gutter holding the question number / sub-part label. Cambridge
# hangs "(a)" and "(ii)" in a left gutter with the body text aligned beyond it.
QUESTION_LABEL_WIDTH_MM = _f("QUESTION_LABEL_WIDTH_MM", 10.0)
SUBPART_LABEL_WIDTH_MM = _f("SUBPART_LABEL_WIDTH_MM", 10.0)
# Indent applied per nesting level: "(a)" sits at level 0, "(a)(ii)" at level 1.
NEST_INDENT_MM = _f("NEST_INDENT_MM", 10.0)
# Vertical separation between consecutive questions, so a new question never
# looks like a continuation of the previous one's answer space.
QUESTION_GAP_MM = _f("QUESTION_GAP_MM", 7.0)

# --------------------------------------------------------------------------- #
# Diagrams
# --------------------------------------------------------------------------- #
# Diagram images are scaled to this fraction of the body column width, then
# capped in height so a tall figure cannot eat a whole page.
DIAGRAM_WIDTH_FRACTION = _f("DIAGRAM_WIDTH_FRACTION", 0.86)
DIAGRAM_MAX_HEIGHT_MM = _f("DIAGRAM_MAX_HEIGHT_MM", 95.0)
DIAGRAM_MIN_WIDTH_MM = _f("DIAGRAM_MIN_WIDTH_MM", 25.0)

# --------------------------------------------------------------------------- #
# Page-break safety (Part 2.1, last bullet)
# --------------------------------------------------------------------------- #
# A sub-part whose estimated height is at or below this fraction of the text
# block is emitted inside a minipage, which LaTeX cannot break — so its text,
# diagram and answer space are guaranteed to travel together. Anything taller is
# emitted as flowing text (a block taller than a page cannot be kept whole) with
# a \needspace guard so it at least starts with room for its opening lines.
ATOMIC_MAX_PAGE_FRACTION = _f("ATOMIC_MAX_PAGE_FRACTION", 0.82)
NEEDSPACE_FALLBACK_LINES = _i("NEEDSPACE_FALLBACK_LINES", 6)

# --------------------------------------------------------------------------- #
# Compilation (Part 3.2)
# --------------------------------------------------------------------------- #
# Wall-clock cap on one xelatex run. LaTeX can spin forever on malformed input,
# so the compile is killed and reported as a clean failure — mirroring the
# bounded-timeout discipline the AI marking pipeline already uses.
ENGINE_TIMEOUT_S = _f("ENGINE_TIMEOUT_S", 120.0)
# Extra passes after the first (page refs / running headers settle in 1 rerun).
ENGINE_RERUNS = _i("ENGINE_RERUNS", 1)

# --------------------------------------------------------------------------- #
# Fonts (Part 0.2)
# --------------------------------------------------------------------------- #
# The font the school requires. Overridable so another school can point the same
# pipeline at their own house font.
PRIMARY_FONT_FAMILY = _s("PRIMARY_FONT_FAMILY", "Century Gothic")
# The free, geometric-sans stand-in used when the licensed font files are not
# present. TeX Gyre Adventor is the GUST/URW Gothic revival — the standard open
# substitute for Century Gothic — and ships inside the TeX bundle, so it always
# resolves without a system font install.
FALLBACK_FONT_FILES = {
    "regular": _s("FALLBACK_FONT_REGULAR", "texgyreadventor-regular.otf"),
    "bold": _s("FALLBACK_FONT_BOLD", "texgyreadventor-bold.otf"),
    "italic": _s("FALLBACK_FONT_ITALIC", "texgyreadventor-italic.otf"),
    "bolditalic": _s("FALLBACK_FONT_BOLDITALIC", "texgyreadventor-bolditalic.otf"),
}
FALLBACK_FONT_NAME = _s("FALLBACK_FONT_NAME", "TeX Gyre Adventor")
# Math letters/digits are drawn from the document font so a formula does not
# visibly switch typeface mid-line; symbol glyphs (√ ∑ ⩽ ∩) come from Latin
# Modern Math, which Century Gothic has no equivalent for.
MATH_SYMBOL_FONT = _s("MATH_SYMBOL_FONT", "latinmodern-math.otf")
MATCH_MATH_TO_TEXT_FONT = _s("MATCH_MATH_TO_TEXT_FONT", "true").lower() not in (
    "false", "0", "no", "off",
)

# --------------------------------------------------------------------------- #
# Timing heuristic (shared with the reportlab generator's convention)
# --------------------------------------------------------------------------- #
MINUTES_PER_MARK = _f("MINUTES_PER_MARK", 1.5)
