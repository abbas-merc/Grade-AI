"""
utils/latex/engine.py — Run the XeLaTeX engine, bounded and attributable.

The engine is **Tectonic** (https://tectonic-typesetting.github.io): a single
self-contained binary wrapping the real XeTeX engine plus xdvipdfmx. It was
chosen over a TeX Live install because a TeX Live scheme large enough to provide
fontspec + unicode-math + the TeX Gyre fonts runs to several GB, whereas
Tectonic is one ~50 MB executable that pulls the individual .sty/.otf files it
needs from a signed bundle and caches them. Deployment therefore adds ~50 MB plus
a warmed cache instead of a multi-gigabyte apt layer — see backend/Dockerfile.

Two things this module guarantees, because LaTeX gives neither for free:

* **A timeout** (Part 3.2). TeX can loop forever on malformed input; the process
  is killed at ``config.ENGINE_TIMEOUT_S`` and the job fails cleanly rather than
  wedging the worker.
* **Attribution** (Part 3.1). The template emits ``%%GA-ANCHOR:<key>`` marker
  lines and hands us a line -> key map. When the compiler reports an error at a
  line, we walk back to the nearest anchor and name the sub-part whose LaTeX
  broke, instead of surfacing a raw TeX transcript.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

from . import config

# Locations searched for the engine, in order, before giving up.
_ENGINE_ENV = "TECTONIC_BIN"
_BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_VENDORED = os.path.join(_BACKEND, "tools", "tectonic.exe" if sys.platform == "win32" else "tectonic")

# "error: paper.tex:412: Undefined control sequence" and the transcript's "l.412"
_ERR_LINE_RE = re.compile(r"^error:\s+[^:]*?:(\d+):\s*(.*)$", re.M)
_TRANSCRIPT_LINE_RE = re.compile(r"^l\.(\d+)\s*(.*)$", re.M)
_ERR_ANY_RE = re.compile(r"^error:\s*(.+)$", re.M)
_MISSING_FONT_RE = re.compile(r"cannot find the font|font .* not found|Font .* not loadable", re.I)


class EngineUnavailable(RuntimeError):
    """The LaTeX engine is not installed in this environment."""


@dataclass
class CompileResult:
    ok: bool
    pdf: bytes = b""
    engine: str = ""
    seconds: float = 0.0
    # On failure: the sub-part (or section) whose LaTeX the compiler choked on.
    failed_anchor: str = ""
    message: str = ""
    log: str = ""
    warnings: list[str] = field(default_factory=list)
    timed_out: bool = False


def find_engine() -> str:
    """Absolute path to the tectonic binary, or "" when unavailable."""
    explicit = (os.getenv(_ENGINE_ENV) or "").strip()
    if explicit and os.path.exists(explicit):
        return explicit
    on_path = shutil.which("tectonic")
    if on_path:
        return on_path
    if os.path.exists(_VENDORED):
        return _VENDORED
    return ""


def engine_status() -> dict:
    """Serialisable engine availability, for /health-style reporting."""
    path = find_engine()
    version = ""
    if path:
        try:
            version = subprocess.run([path, "--version"], capture_output=True,
                                     text=True, timeout=20).stdout.strip()
        except Exception as exc:  # pragma: no cover - defensive
            version = "unreadable: " + str(exc)
    return {
        "available": bool(path),
        "path": path,
        "version": version,
        "timeoutSeconds": config.ENGINE_TIMEOUT_S,
        "cacheDir": os.getenv("TECTONIC_CACHE_DIR", ""),
    }


def _attribute(line_no: int, anchors: list[tuple[int, str]]) -> str:
    """Nearest ``%%GA-ANCHOR`` at or above ``line_no``."""
    best = ""
    for anchor_line, key in anchors:
        if anchor_line <= line_no:
            best = key
        else:
            break
    return best


def _summarise_failure(output: str, anchors: list[tuple[int, str]]) -> tuple[str, str]:
    """(anchor, human message) for a failed compile."""
    matches = _ERR_LINE_RE.findall(output) or [
        (ln, txt) for ln, txt in _TRANSCRIPT_LINE_RE.findall(output)
    ]
    if matches:
        line_no, detail = matches[0]
        anchor = _attribute(int(line_no), anchors)
        detail = (detail or "").strip()
        where = f" in {anchor}" if anchor else ""
        return anchor, f"LaTeX error{where}: {detail or 'see log'} (line {line_no})"

    generic = _ERR_ANY_RE.findall(output)
    if generic:
        first = generic[0].strip()
        if _MISSING_FONT_RE.search(output):
            return "", "Font could not be loaded by the LaTeX engine: " + first
        return "", "LaTeX error: " + first
    return "", "LaTeX compilation failed with no parsable error; see log."


def compile_tex(tex_source: str, *, build_dir: str | None = None,
                assets: dict[str, str] | None = None,
                anchors: list[tuple[int, str]] | None = None,
                job_name: str = "paper") -> CompileResult:
    """Compile ``tex_source`` to PDF bytes.

    ``assets`` maps the basename referenced from the .tex to the absolute path of
    the file on disk; each is copied into the build directory so the document is
    self-contained (and so no absolute path leaks into the source).
    ``anchors`` is the ``(line_number, key)`` list produced alongside the source
    by :mod:`utils.latex.templates`, used to attribute a compile error.

    Never raises for a document-level failure — a broken paper comes back as
    ``CompileResult(ok=False, ...)`` with a specific message. Only a genuinely
    missing engine raises :class:`EngineUnavailable`.
    """
    engine = find_engine()
    if not engine:
        raise EngineUnavailable(
            "No LaTeX engine found. Install Tectonic and expose it as `tectonic` on "
            "PATH, at backend/tools/tectonic, or via the TECTONIC_BIN environment "
            "variable. The deployed image installs it in backend/Dockerfile."
        )

    anchors = sorted(anchors or [])
    owns_dir = build_dir is None
    build_dir = build_dir or tempfile.mkdtemp(prefix="ga-latex-")
    try:
        os.makedirs(build_dir, exist_ok=True)
        tex_path = os.path.join(build_dir, job_name + ".tex")
        with open(tex_path, "w", encoding="utf-8") as fh:
            fh.write(tex_source)

        for basename, src in (assets or {}).items():
            dest = os.path.join(build_dir, basename)
            if os.path.abspath(src) != os.path.abspath(dest) and os.path.exists(src):
                shutil.copyfile(src, dest)

        env = dict(os.environ)
        # A deterministic timestamp keeps repeated builds of the same paper
        # byte-identical, which makes diffing generated output meaningful.
        env.setdefault("SOURCE_DATE_EPOCH", "1735689600")  # 2025-01-01T00:00:00Z

        cmd = [engine, "-X", "compile", tex_path, "--outdir", build_dir,
               "--keep-logs", "--print", "-r", str(config.ENGINE_RERUNS),
               "-Z", "paper-size=a4"]

        import time
        started = time.monotonic()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, env=env,
                                  timeout=config.ENGINE_TIMEOUT_S, cwd=build_dir)
        except subprocess.TimeoutExpired:
            return CompileResult(
                ok=False, engine=engine, seconds=config.ENGINE_TIMEOUT_S, timed_out=True,
                message=("LaTeX compilation exceeded the "
                         f"{config.ENGINE_TIMEOUT_S:g}s timeout and was cancelled. "
                         "This normally means a malformed LaTeX fragment put the engine "
                         "into a loop."),
            )
        elapsed = time.monotonic() - started
        output = (proc.stdout or "") + "\n" + (proc.stderr or "")

        log_path = os.path.join(build_dir, job_name + ".log")
        log_text = ""
        if os.path.exists(log_path):
            with open(log_path, encoding="utf-8", errors="replace") as fh:
                log_text = fh.read()

        pdf_path = os.path.join(build_dir, job_name + ".pdf")
        if proc.returncode == 0 and os.path.exists(pdf_path):
            with open(pdf_path, "rb") as fh:
                pdf = fh.read()
            warnings = [ln.strip() for ln in output.splitlines()
                        if ln.startswith("warning:") and "absolute path" not in ln]
            return CompileResult(ok=True, pdf=pdf, engine=engine, seconds=elapsed,
                                 log=log_text, warnings=warnings)

        anchor, message = _summarise_failure(output + "\n" + log_text, anchors)
        return CompileResult(ok=False, engine=engine, seconds=elapsed,
                             failed_anchor=anchor, message=message,
                             log=(output + "\n" + log_text)[-20000:])
    finally:
        if owns_dir and os.getenv("GA_LATEX_KEEP_BUILD", "").lower() not in ("1", "true", "yes"):
            shutil.rmtree(build_dir, ignore_errors=True)


def probe_fragments(fragments: list[tuple[str, str]], preamble: str,
                    *, build_dir: str, chunk: int = 60) -> dict[str, str]:
    """Compile-check many LaTeX fragments and report which ones fail (Part 1.3).

    ``fragments`` is ``[(key, latex), ...]``. Returns ``{key: error message}`` for
    every fragment that does not compile; keys absent from the result compiled
    cleanly. ``build_dir`` must be the directory ``preamble`` was generated for
    (font files are staged into it). Fragments are compiled in batches and any
    failing batch is bisected, so one broken fragment is attributed exactly
    instead of condemning its neighbours.
    """
    failures: dict[str, str] = {}
    for start in range(0, len(fragments), chunk):
        batch = fragments[start:start + chunk]
        failures.update(_probe_batch(batch, preamble, build_dir))
    return failures


def _probe_batch(batch: list[tuple[str, str]], preamble: str,
                 build_dir: str) -> dict[str, str]:
    lines: list[str] = [preamble, r"\begin{document}"]
    anchors: list[tuple[int, str]] = []
    for key, latex in batch:
        anchors.append((len(lines) + 1, key))
        lines.append("%%GA-ANCHOR:" + key)
        lines.append(r"\noindent " + latex)
        lines.append(r"\par\bigskip")
    lines.append(r"\end{document}")
    source = "\n".join(lines)

    result = compile_tex(source, build_dir=build_dir, anchors=anchors, job_name="probe")
    if result.ok:
        return {}
    if len(batch) == 1:
        return {batch[0][0]: result.message}
    # Bisect so a single poisonous fragment does not condemn its neighbours.
    mid = len(batch) // 2
    out = _probe_batch(batch[:mid], preamble, build_dir)
    out.update(_probe_batch(batch[mid:], preamble, build_dir))
    return out
