"""
utils/latex/latexify.py — Turn strings into safe, valid LaTeX.

Three jobs:

1. **escape_text** — literal text (a school name, a teacher's paper title, a raw
   mark-scheme line) into LaTeX with every special character neutralised.
2. **unicode_to_latex** — the maths characters Cambridge PDFs actually contain,
   including the Adobe Symbol-font Private-Use-Area code points PyMuPDF hands
   back (U+F0xx, which are *not* real Unicode and no font can render), mapped to
   their proper LaTeX commands.
3. **sanitize_fragment / validate_fragment** — vet a LaTeX fragment produced by
   the extraction agent before it is ever handed to the compiler: strip
   preamble-only and filesystem-touching commands, and catch the structural
   breakages (unbalanced braces, stray ``$``, unclosed environments) that account
   for nearly every "it compiled fine in isolation" surprise.
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------- #
# 1. Literal text -> LaTeX
# --------------------------------------------------------------------------- #
_ESCAPES = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "$": r"\$",
    "&": r"\&",
    "#": r"\#",
    "^": r"\textasciicircum{}",
    "_": r"\_",
    "~": r"\textasciitilde{}",
    "%": r"\%",
}

# --------------------------------------------------------------------------- #
# 2. Unicode / Symbol-font maths -> LaTeX
# --------------------------------------------------------------------------- #
# Cambridge PDFs embed maths via the Adobe "Symbol" font; PyMuPDF extracts those
# glyphs as U+F0xx Private-Use code points. The low range is plain ASCII shifted
# by U+F000; these high bytes carry the real meaning.
_SYMBOL_HIGH_TO_UNICODE = {
    0xB4: "\u00d7", 0xB1: "\u00b1", 0xB8: "\u00f7", 0xA3: "\u2a7d",
    0xB3: "\u2a7e", 0xB9: "\u2260", 0xD6: "\u221a", 0xA5: "\u221e",
    0xE6: "(", 0xE7: "(", 0xE8: "(", 0xF6: ")", 0xF7: ")", 0xF8: ")",
    0x70: "\u03c0", 0x71: "\u03b8", 0x61: "\u03b1", 0x62: "\u03b2",
    0x44: "\u0394",
}

# Real Unicode maths characters -> the LaTeX that renders them. Values are math
# mode fragments; ``unicode_to_latex`` wraps runs of them in ``$...$``.
_MATH_UNICODE = {
    "\u00d7": r"\times", "\u00f7": r"\div", "\u00b1": r"\pm", "\u2213": r"\mp",
    "\u2264": r"\leqslant", "\u2265": r"\geqslant", "\u2a7d": r"\leqslant",
    "\u2a7e": r"\geqslant", "\u2260": r"\neq", "\u2248": r"\approx",
    "\u2261": r"\equiv", "\u221d": r"\propto", "\u221e": r"\infty",
    "\u221a": r"\surd", "\u2211": r"\sum", "\u220f": r"\prod",
    "\u2208": r"\in", "\u2209": r"\notin", "\u2282": r"\subset",
    "\u2286": r"\subseteq", "\u222a": r"\cup", "\u2229": r"\cap",
    "\u2205": r"\emptyset", "\u2032": r"'", "\u00b0": r"^\circ",
    "\u03c0": r"\pi", "\u03b8": r"\theta", "\u03b1": r"\alpha",
    "\u03b2": r"\beta", "\u03b3": r"\gamma", "\u0394": r"\Delta",
    "\u00b2": r"^{2}", "\u00b3": r"^{3}", "\u00b9": r"^{1}",
    "\u2070": r"^{0}", "\u2074": r"^{4}", "\u2075": r"^{5}",
    "\u2212": r"-", "\u2192": r"\rightarrow", "\u21d2": r"\Rightarrow",
    "\u00bd": r"\tfrac{1}{2}", "\u00bc": r"\tfrac{1}{4}", "\u00be": r"\tfrac{3}{4}",
    "\u2154": r"\tfrac{2}{3}", "\u2153": r"\tfrac{1}{3}",
    "\u2220": r"\angle", "\u22a5": r"\perp", "\u2225": r"\parallel",
    "\u2235": r"\because", "\u2234": r"\therefore",
}

# Typographic characters that belong in text mode, not maths.
_TEXT_UNICODE = {
    "\u2013": "--", "\u2014": "---", "\u2018": "`", "\u2019": "'",
    "\u201c": "``", "\u201d": "''", "\u2026": r"\ldots{}", "\u00a0": "~",
    "\u2022": r"\textbullet{}", "\u00a3": r"\pounds{}",
    "\u20ac": r"\texteuro{}", "\ufb01": "fi", "\ufb02": "fl",
}


def depua(text: str) -> str:
    """Resolve Adobe Symbol-font PUA code points (U+F0xx) to real Unicode.

    Unresolvable private-use code points are dropped rather than rendered as a
    missing-glyph box.
    """
    out: list[str] = []
    for ch in text:
        code = ord(ch)
        if 0xF000 <= code <= 0xF0FF:
            base = code - 0xF000
            if 0x20 <= base <= 0x7E and base not in _SYMBOL_HIGH_TO_UNICODE:
                out.append(chr(base))
            else:
                out.append(_SYMBOL_HIGH_TO_UNICODE.get(base, ""))
        else:
            out.append(ch)
    return "".join(out)


def escape_text(text: str) -> str:
    """Escape literal text for LaTeX text mode (no maths interpretation)."""
    out: list[str] = []
    for ch in depua(text or ""):
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ch in _TEXT_UNICODE:
            out.append(_TEXT_UNICODE[ch])
        elif ch in _MATH_UNICODE:
            out.append("$" + _MATH_UNICODE[ch] + "$")
        else:
            out.append(ch)
    return "".join(out)


def unicode_to_latex(text: str) -> str:
    """Escape literal text but coalesce adjacent maths symbols into one ``$...$``.

    Used for source that was never routed through the extraction agent — most
    importantly raw mark-scheme lines, which are full of ``×``, ``⩽`` and
    Symbol-font residue but are otherwise plain prose.
    """
    src = depua(text or "")
    out: list[str] = []
    math_run: list[str] = []

    def flush() -> None:
        if math_run:
            out.append("$" + " ".join(math_run) + "$")
            math_run.clear()

    for ch in src:
        if ch in _MATH_UNICODE:
            math_run.append(_MATH_UNICODE[ch])
            continue
        flush()
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ch in _TEXT_UNICODE:
            out.append(_TEXT_UNICODE[ch])
        else:
            out.append(ch)
    flush()
    return "".join(out)


# --------------------------------------------------------------------------- #
# 3. Vetting an extracted fragment
# --------------------------------------------------------------------------- #
# Commands a question fragment has no business containing. Two groups: preamble
# commands that would blow up mid-document, and anything that reads or writes the
# filesystem or reprograms the parser. Tectonic runs without shell-escape so
# \write18 is already inert, but \input would still splice an arbitrary file into
# the printed paper.
_FORBIDDEN = (
    r"\input", r"\include", r"\includeonly", r"\write", r"\openout", r"\openin",
    r"\read", r"\catcode", r"\csname", r"\expandafter", r"\documentclass",
    r"\usepackage", r"\begin{document}", r"\end{document}", r"\newcommand",
    r"\renewcommand", r"\def", r"\let", r"\loop", r"\repeat", r"\immediate",
    r"\special", r"\pdfliteral", r"\directlua", r"\ShellEscape",
    r"\includegraphics", r"\newpage", r"\clearpage", r"\pagebreak",
)

# Environments the template's geometry supports. Anything else is stripped to its
# body so a hallucinated environment cannot break the compile.
_ALLOWED_ENVS = {
    "array", "matrix", "pmatrix", "bmatrix", "vmatrix", "Bmatrix", "cases",
    "aligned", "gathered", "split", "tabular", "center", "itemize", "enumerate",
    "smallmatrix", "subarray",
}

_ENV_RE = re.compile(r"\\(begin|end)\s*\{([^}]*)\}")
_CMD_RE = re.compile(r"\\[A-Za-z@]+")


# A "\\" line break followed by a literal "[" — TeX would read the bracket as the
# break's optional length. Whitespace and newlines between them are skipped by
# TeX, so they must be matched here too.
#
# But "\\[6pt]" IS that optional length and is exactly what the model emits to
# space a formula off the line above, so only a bracket whose content is NOT a
# length may be protected. Getting this backwards turns every deliberate bit of
# vertical spacing into a literal "[6pt]" printed on the page.
_TEX_LENGTH = re.compile(
    r"^\s*-?[\d.]*\s*(?:pt|mm|cm|in|ex|em|bp|pc|dd|cc|sp|"
    r"\\baselineskip|\\smallskipamount|\\medskipamount|\\bigskipamount)\s*$")
_BREAK_THEN_BRACKET = re.compile(r"\\\\\s*\[([^]\n]*)\]")
# Undo the over-eager form of the protection above, so a store written by an
# earlier version is repaired in place rather than left printing "[6pt]".
_OVERPROTECTED = re.compile(r"\\\\\{\}\[([^]\n]*)\]")


def _protect_brackets(text: str) -> tuple[str, int]:
    """Insert {} between a line break and a following non-length bracket."""
    def undo(match: re.Match) -> str:
        inner = match.group(1)
        return ("\\\\[" + inner + "]") if _TEX_LENGTH.match(inner) else match.group(0)

    text = _OVERPROTECTED.sub(undo, text)

    count = 0

    def protect(match: re.Match) -> str:
        nonlocal count
        inner = match.group(1)
        if _TEX_LENGTH.match(inner):
            return match.group(0)
        count += 1
        return "\\\\{}[" + inner + "]"

    return _BREAK_THEN_BRACKET.sub(protect, text), count


def sanitize_fragment(latex: str) -> tuple[str, list[str]]:
    """Strip anything unsafe or structural from a fragment.

    Returns ``(cleaned, notes)`` where ``notes`` records every removal, so the
    build script can flag heavy-handed cleanups for review rather than shipping
    them silently.
    """
    notes: list[str] = []
    text = (latex or "").strip()
    if not text:
        return "", notes

    # Models occasionally wrap output in a markdown fence despite the schema.
    fence = re.match(r"^```(?:latex|tex)?\s*(.*?)\s*```$", text, re.S)
    if fence:
        text = fence.group(1).strip()
        notes.append("stripped markdown code fence")

    for cmd in _FORBIDDEN:
        if cmd in text:
            # Remove the command and any single braced argument that follows.
            pattern = re.escape(cmd) + r"(\s*\{[^{}]*\})?"
            text = re.sub(pattern, "", text)
            notes.append("removed forbidden command " + cmd)

    def _env_guard(match: re.Match) -> str:
        which, name = match.group(1), match.group(2).strip().rstrip("*")
        if name in _ALLOWED_ENVS:
            return match.group(0)
        notes.append("unwrapped unsupported environment " + name)
        return ""

    text = _ENV_RE.sub(_env_guard, text)
    # Collapse the blank lines an unwrapped environment leaves behind; a blank
    # line inside a question body would start a new paragraph mid-sentence.
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    # Cambridge prints the formula a question supplies in square brackets, on its
    # own line: "[The curved surface area, A, of a cone ... is A = pi r l.]".
    # After a "\\" line break TeX skips whitespace and reads a following "[...]"
    # as the break's optional vertical-space argument, so the sentence becomes a
    # length and the compile dies with "Missing number, treated as zero". An
    # empty group between them makes the bracket ordinary text again.
    text, n = _protect_brackets(text)
    if n:
        notes.append("protected %d formula bracket(s) after a line break" % n)
    return text, notes


# Commands / characters that only mean anything inside maths mode.
_MATH_ONLY = re.compile(
    r"\\frac|\\dfrac|\\tfrac|\\sqrt|\\times|\\div|\\pm|\\cdot|\\pi\b|\\le\b|\\ge\b"
    r"|\\leqslant|\\geqslant|\\neq|\\begin\{p?matrix\}|\\overrightarrow|\\mathbf"
    r"|\\mathrm|\\cap|\\cup|\\in\b|\\circ\b|(?<!\\)[\^_]"
)
# What is left of a fragment once every command and \text{...} payload is gone.
_STRIP_TEXT = re.compile(r"\\text(?:rm|bf|it)?\s*\{[^{}]*\}")
_STRIP_CMD = re.compile(r"\\[A-Za-z@]+|\\[,;:!]")
_WORD_RUN = re.compile(r"[A-Za-z]{3,}")


def ensure_math_wrapped(latex: str) -> str:
    """Wrap a bare maths expression in ``$...$`` when it clearly needs it.

    Models reliably return ``$w=158$, $x=76$`` for a prose-ish answer but just as
    reliably return ``3x^{3}+5x^{2}-34x-24`` for a pure expression — which is
    correct maths and a hard compile error in text mode ("Missing $ inserted").
    Rather than depending on the prompt to be obeyed every time, repair it here:
    wrap only when the fragment has no maths delimiter of its own, does contain
    maths-only notation, and carries no prose outside ``\\text{}``.
    """
    text = (latex or "").strip()
    if not text or "$" in text or "\\[" in text or "\\(" in text:
        return text
    if not _MATH_ONLY.search(text):
        return text
    residue = _STRIP_CMD.sub("", _STRIP_TEXT.sub("", text))
    if _WORD_RUN.search(residue):
        return text  # real prose is mixed in; wrapping it would be wrong
    return "$" + text + "$"


def validate_fragment(latex: str) -> list[str]:
    """Structural problems that would fail (or silently mangle) the compile.

    Cheap and local — a real compile check still runs in
    :func:`utils.latex.engine.probe_fragments`, but catching these here means the
    obvious breakages never reach the engine at all.
    """
    problems: list[str] = []
    text = latex or ""
    if not text.strip():
        return ["empty fragment"]

    depth = 0
    escaped = False
    dollars = 0
    display = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if escaped:
            escaped = False
            i += 1
            continue
        if ch == "\\":
            escaped = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                problems.append("closing brace with no matching open brace")
                depth = 0
        elif ch == "$":
            if text[i:i + 2] == "$$":
                display += 1
                i += 1
            else:
                dollars += 1
        i += 1

    if depth != 0:
        problems.append(f"unbalanced braces ({depth:+d})")
    if dollars % 2:
        problems.append("odd number of $ delimiters — unclosed inline maths")
    if display % 2:
        problems.append("unclosed $$ display maths")

    opened: list[str] = []
    for which, name in _ENV_RE.findall(text):
        name = name.strip()
        if which == "begin":
            opened.append(name)
        elif not opened:
            problems.append("\\end{" + name + "} with no matching \\begin")
        elif opened[-1] != name:
            problems.append("environment mismatch: \\begin{" + opened[-1] +
                            "} closed by \\end{" + name + "}")
            opened.pop()
        else:
            opened.pop()
    for name in opened:
        problems.append("unclosed environment " + name)

    for cmd in _FORBIDDEN:
        if cmd in text:
            problems.append("forbidden command present: " + cmd)

    # A lone backslash-newline or trailing backslash outside a matrix breaks rows.
    if re.search(r"\\\\\s*$", text) and not any(
            e in text for e in ("matrix", "array", "cases", "aligned")):
        problems.append("trailing \\\\ outside a matrix/array environment")

    # Bare ^ or _ with no maths delimiter anywhere is the classic
    # "Missing $ inserted" — catch it before the engine does.
    if "$" not in text and "\\[" not in text and re.search(r"(?<!\\)[\^_]", text):
        problems.append("^ or _ used outside maths mode (missing $ delimiters)")

    return problems


def looks_like_plain_text(latex: str) -> bool:
    """True when a fragment contains no LaTeX markup at all.

    A sub-part that genuinely has no maths ("Write down the order of rotational
    symmetry.") is legitimately plain — this is a signal for the review list, not
    an error, and is only worth flagging when the *source* text clearly had maths
    in it.
    """
    text = latex or ""
    return not _CMD_RE.search(text) and not any(d in text for d in ("$", "\\[", "\\("))


# --------------------------------------------------------------------------- #
# 4. Offline fallback for a sub-part with no AI extraction
# --------------------------------------------------------------------------- #
_LINE_NOISE = re.compile(r"\.{4,}|\[\d{1,2}\]|^Answer\b", re.M)
_RUN_OF_SPACES = re.compile(r"[ \t]{2,}")
# The raw PDF text of a sub-part still carries the labels Cambridge printed in
# the margin — the original question number ("5") and the sub-part path
# ("(a) (i)"). The template prints those itself from the bank record, so leaving
# them in the body renders them twice: "(b)   (b) On the grid, ...".
_LEADING_LABELS = re.compile(
    r"^\s*(?:\d{1,2}\s*(?=\())?"                    # question number, only before a label
    r"(?:\(\s*(?:[a-h]|[ivx]{1,4})\s*\)\s*)+",      # (a), (b) (ii), (iii) ...
    re.I,
)


def strip_leading_labels(text: str) -> str:
    """Drop the question-number / sub-part labels the template re-prints itself."""
    return _LEADING_LABELS.sub("", text or "", count=1).lstrip()


def latex_from_raw_text(text: str) -> str:
    """Best-effort LaTeX for a sub-part the extraction has not covered.

    Strips the answer rules, the duplicated margin labels and the mark indicators
    the template re-adds itself, then maps the Unicode / Symbol-font maths
    characters to LaTeX. This is honest prose with correct symbols — it is NOT a
    claim that the notation (fractions, surds, vectors) was reconstructed, so
    anything routed through it is counted as a fallback and reported to the
    caller.
    """
    cleaned = _RUN_OF_SPACES.sub(" ", _LINE_NOISE.sub(" ", text or ""))
    lines = (line.strip() for line in cleaned.splitlines())
    joined = strip_leading_labels(" ".join(line for line in lines if line))
    return unicode_to_latex(joined).strip()
