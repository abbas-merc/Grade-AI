"""
utils/latex/service.py — The one call the routers make.

Takes a paper-generator response, assembles it, typesets it and returns PDF
bytes — with every failure mode turned into a precise, actionable result rather
than an exception escaping into the request handler (Part 3.1).

Failure taxonomy:

* engine missing        -> ``PaperBuildError(status=503)`` naming the install step
* compile error         -> ``PaperBuildError(status=422)`` naming the sub-part
                           whose LaTeX broke, recovered from the compiler's own
                           line number via the template's anchors
* compile timeout       -> ``PaperBuildError(status=504)``
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field

from . import assemble, engine, templates
from .fonts import resolve_font
from .latexify import validate_fragment


class PaperBuildError(Exception):
    """A paper that could not be produced, with the reason a caller can show."""

    def __init__(self, message: str, *, status: int, part: str = "", log: str = ""):
        super().__init__(message)
        self.message = message
        self.status = status
        self.part = part
        self.log = log


@dataclass
class BuiltPaper:
    pdf: bytes
    seconds: float
    pages_hint: int = 0
    font_mode: str = ""
    font_family: str = ""
    # Sub-parts whose LaTeX came from the raw-text fallback rather than the
    # notation-aware extraction. Surfaced so a caller never has to guess.
    fallbacks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _preflight(paper: dict) -> None:
    """Validate every fragment before the engine sees it.

    The compiler is a poor witness for the most common breakage: an unbalanced
    brace makes TeX swallow the rest of the file and report "File ended while
    scanning", with no line number to attribute. Checking structure here means the
    failure names the exact sub-part every time, and the compiler stays as the
    backstop for everything structural analysis cannot catch.
    """
    for question in paper.get("questions", []):
        fragments = [(question.get("key") or f"Q{question.get('number')}",
                      (question.get("intro") or {}).get("latex", ""))]
        for sp in question.get("subParts") or []:
            key = sp.get("key") or sp.get("partId") or ""
            fragments.append((key, sp.get("latex", "")))
            fragments.append((key, sp.get("answerLatex", "")))
            for point in sp.get("markPoints") or []:
                fragments.append((key, point.get("latex", "")))
        for key, latex in fragments:
            if not (latex or "").strip():
                continue
            problems = validate_fragment(latex)
            if problems:
                raise PaperBuildError(
                    "Malformed LaTeX in the extracted question content: "
                    + "; ".join(problems),
                    status=422, part=key)


def _build(paper: dict, render, job_name: str) -> BuiltPaper:
    _preflight(paper)
    font = resolve_font()
    keep = os.getenv("GA_LATEX_KEEP_BUILD", "").lower() in ("1", "true", "yes")
    build_dir = tempfile.mkdtemp(prefix="ga-latex-")
    try:
        source, assets, anchors = render(paper, build_dir, font)
        try:
            result = engine.compile_tex(source, build_dir=build_dir, assets=assets,
                                        anchors=anchors, job_name=job_name)
        except engine.EngineUnavailable as exc:
            raise PaperBuildError(str(exc), status=503) from exc

        if result.timed_out:
            raise PaperBuildError(result.message, status=504, log=result.log)
        if not result.ok:
            raise PaperBuildError(result.message, status=422,
                                  part=result.failed_anchor, log=result.log)
        return BuiltPaper(
            pdf=result.pdf, seconds=result.seconds,
            font_mode=font.mode, font_family=font.family,
            fallbacks=list(paper.get("fallbacks") or []),
            warnings=result.warnings,
        )
    finally:
        if not keep:
            import shutil
            shutil.rmtree(build_dir, ignore_errors=True)


def question_paper(paper_data: dict, *, partlevel: bool = False) -> BuiltPaper:
    """Typeset the question paper for a generate-paper response."""
    paper = (assemble.from_partlevel_paper(paper_data) if partlevel
             else assemble.from_generated_paper(paper_data))
    if not paper.get("questions"):
        raise PaperBuildError("The generated paper contains no questions.", status=422)
    return _build(paper, templates.question_paper_tex, "question_paper")


def mark_scheme(paper_data: dict, *, partlevel: bool = False) -> BuiltPaper:
    """Typeset the mark scheme for the same response."""
    paper = (assemble.from_partlevel_paper(paper_data) if partlevel
             else assemble.from_generated_paper(paper_data))
    if not paper.get("questions"):
        raise PaperBuildError("The generated paper contains no questions.", status=422)
    return _build(paper, templates.mark_scheme_tex, "mark_scheme")


def status() -> dict:
    """Engine + font readiness, for diagnostics."""
    from .fonts import describe
    return {"engine": engine.engine_status(), "font": describe(),
            "extractedQuestions": len(assemble.latex_store())}
