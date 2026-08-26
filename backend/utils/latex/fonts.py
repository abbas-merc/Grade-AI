"""
utils/latex/fonts.py — Resolve the document font, honestly.

Century Gothic is a **commercial Monotype typeface**. It is not free, it is not
redistributable, and it is not present in any TeX distribution. Shipping the
font files inside a server image so the server can embed them in every generated
PDF is a licensing act, not a technical one — so this module never pretends the
font is available when it is not.

Resolution order (first hit wins):

1. ``GA_CENTURY_GOTHIC_DIR`` — a directory of licensed font files supplied by
   the school.  ``mode = "licensed"``
2. ``backend/fonts/century_gothic/`` — the in-repo drop point for those files
   (git-ignored; empty by default).  ``mode = "licensed"``
3. An OS font directory that happens to contain Century Gothic (true on a
   Windows dev box with Microsoft Office installed).  ``mode = "system"`` — fine
   for local development and **flagged**, because a Windows/Office font licence
   does not permit copying the file into a Linux server image.
4. TeX Gyre Adventor, the GUST/URW Gothic revival that ships inside the TeX
   bundle. This is the free, geometrically-similar sans normally substituted for
   Century Gothic.  ``mode = "fallback"``

Every :class:`FontChoice` carries ``needs_licence_action`` and a human-readable
``notice`` so the report, the API response and the test harness all state which
font actually went into the PDF rather than assuming.
"""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field

from . import config

_BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO_FONT_DIR = os.path.join(_BACKEND, "fonts", "century_gothic")

# Style -> the filenames Century Gothic ships under, across platforms. Monotype's
# Windows/Office distribution uses the terse 8.3 names; other packagings use the
# spelled-out family name.
_CENTURY_GOTHIC_FILES: dict[str, tuple[str, ...]] = {
    "regular": ("GOTHIC.TTF", "CenturyGothic.ttf", "Century Gothic.ttf",
                "CenturyGothic-Regular.ttf", "CenturyGothic.otf"),
    "bold": ("GOTHICB.TTF", "CenturyGothic-Bold.ttf",
             "Century Gothic Bold.ttf", "CenturyGothicBold.ttf"),
    "italic": ("GOTHICI.TTF", "CenturyGothic-Italic.ttf",
               "Century Gothic Italic.ttf"),
    "bolditalic": ("GOTHICBI.TTF", "CenturyGothic-BoldItalic.ttf",
                   "Century Gothic Bold Italic.ttf"),
}

# The PostScript name fragments XeTeX writes into the PDF for each mode. The
# verifier (Part 5.2) checks the produced PDF against these, so a silent fontspec
# substitution is caught instead of being reported as success.
EXPECTED_PDF_FONT_TOKENS = {
    "licensed": ("centurygothic",),
    "system": ("centurygothic",),
    "fallback": ("texgyreadventor", "urwgothic"),
}


@dataclass
class FontChoice:
    """The font the document will actually be typeset in."""

    mode: str                       # "licensed" | "system" | "fallback"
    family: str                     # human name, for the report
    files: dict[str, str] = field(default_factory=dict)          # style -> absolute path
    bundle_files: dict[str, str] = field(default_factory=dict)   # style -> TeX bundle filename
    needs_licence_action: bool = False
    notice: str = ""

    @property
    def expected_pdf_tokens(self) -> tuple[str, ...]:
        return EXPECTED_PDF_FONT_TOKENS[self.mode]

    def stage(self, build_dir: str) -> dict[str, str]:
        """Copy licensed / system font files into ``build_dir``.

        Referencing fonts by a relative name inside the build directory keeps the
        compile hermetic — no absolute paths baked into the .tex, and no
        dependence on the machine's font database.
        Returns style -> the basename to use in the .tex.
        """
        staged: dict[str, str] = {}
        for style, path in self.files.items():
            base = os.path.basename(path)
            dest = os.path.join(build_dir, base)
            if os.path.abspath(path) != os.path.abspath(dest):
                shutil.copyfile(path, dest)
            staged[style] = base
        return staged

    def preamble(self, build_dir: str) -> str:
        """The fontspec (+ unicode-math) block for this choice."""
        names = dict(self.bundle_files) if self.mode == "fallback" else self.stage(build_dir)
        reg = names.get("regular", "")

        opts = []
        if names.get("bold"):
            opts.append("BoldFont=" + names["bold"])
        if names.get("italic"):
            opts.append("ItalicFont=" + names["italic"])
        if names.get("bolditalic"):
            opts.append("BoldItalicFont=" + names["bolditalic"])
        if self.mode != "fallback":
            # Fonts are staged next to the .tex; Path must end in a separator.
            opts.append("Path=./")
        opt_str = ("[" + ", ".join(opts) + "]") if opts else ""

        lines = [
            "\\setmainfont{" + reg + "}" + opt_str,
            "\\setsansfont{" + reg + "}" + opt_str,
        ]

        if config.MATCH_MATH_TO_TEXT_FONT:
            path_opt = ", Path=./" if self.mode != "fallback" else ""
            italic = names.get("italic", reg)
            bold = names.get("bold", reg)
            bolditalic = names.get("bolditalic", bold)
            lines += [
                "\\usepackage{unicode-math}",
                "\\setmathfont{" + config.MATH_SYMBOL_FONT + "}",
                # Latin letters and digits are pulled back to the document font so
                # a formula reads as one typeface; the symbol glyphs Century Gothic
                # simply does not contain stay with Latin Modern Math.
                '\\setmathfont{' + reg + '}[range={up,"0030-"0039}' + path_opt + "]",
                "\\setmathfont{" + italic + "}[range={it}" + path_opt + "]",
                "\\setmathfont{" + bold + "}[range={bfup}" + path_opt + "]",
                "\\setmathfont{" + bolditalic + "}[range={bfit}" + path_opt + "]",
            ]
        return "\n".join(lines)


def _system_font_dirs() -> list[str]:
    dirs: list[str] = []
    if sys.platform == "win32":
        win = os.environ.get("WINDIR", "C:\\Windows")
        dirs.append(os.path.join(win, "Fonts"))
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))
    else:
        dirs += ["/usr/share/fonts", "/usr/local/share/fonts",
                 os.path.expanduser("~/.fonts"),
                 os.path.expanduser("~/.local/share/fonts"),
                 "/Library/Fonts", os.path.expanduser("~/Library/Fonts")]
    return [d for d in dirs if os.path.isdir(d)]


def _verify_family(path: str, expect: str = "century gothic") -> bool:
    """Confirm the file really is the family we think it is.

    Guards against grabbing an unrelated "gothic" face (MS Gothic, Yu Gothic)
    whose filename merely collides. Trusts the filename only if no font-reading
    library is importable.
    """
    try:
        from PIL import ImageFont  # Pillow is already a hard dependency
        family, _style = ImageFont.truetype(path, 12).getname()
        return expect in (family or "").lower()
    except Exception:
        return True


def _scan(directory: str, recurse: bool = False) -> dict[str, str]:
    """style -> path for every Century Gothic face found in ``directory``."""
    found: dict[str, str] = {}
    if not os.path.isdir(directory):
        return found
    present: dict[str, str] = {}
    if recurse:
        for root, _dirs, files in os.walk(directory):
            for f in files:
                present.setdefault(f.lower(), os.path.join(root, f))
    else:
        try:
            present = {f.lower(): os.path.join(directory, f) for f in os.listdir(directory)}
        except OSError:
            return found
    for style, names in _CENTURY_GOTHIC_FILES.items():
        for candidate in names:
            hit = present.get(candidate.lower())
            if hit and _verify_family(hit):
                found[style] = hit
                break
    return found


def resolve_font() -> FontChoice:
    """Pick the document font and say plainly where it came from."""
    env_dir = (os.getenv("GA_CENTURY_GOTHIC_DIR") or "").strip()
    for directory in (env_dir, REPO_FONT_DIR):
        if not directory:
            continue
        files = _scan(directory)
        if files.get("regular"):
            return FontChoice(
                mode="licensed", family=config.PRIMARY_FONT_FAMILY, files=files,
                needs_licence_action=False,
                notice=("Using licensed Century Gothic files supplied in " + directory +
                        ". Confirm the school's licence permits embedding in "
                        "server-generated PDFs."),
            )

    for directory in _system_font_dirs():
        files = _scan(directory, recurse=(sys.platform != "win32"))
        if files.get("regular"):
            return FontChoice(
                mode="system", family=config.PRIMARY_FONT_FAMILY, files=files,
                needs_licence_action=True,
                notice=("Century Gothic was found in the OS font directory (" + directory +
                        ") and is being embedded. Fine for local development, but a "
                        "Windows/Office font licence does NOT permit copying the file into "
                        "a Linux server image — the school must supply a licensed copy at "
                        "GA_CENTURY_GOTHIC_DIR before this is used in production."),
            )

    return FontChoice(
        mode="fallback", family=config.FALLBACK_FONT_NAME,
        bundle_files=dict(config.FALLBACK_FONT_FILES),
        needs_licence_action=True,
        notice=("Century Gothic is a commercial Monotype font and no licensed copy was "
                "found, so the open substitute " + config.FALLBACK_FONT_NAME +
                " (GUST Font Licence, the URW Gothic revival) is being used instead. "
                "Drop the school's licensed Century Gothic files into " + REPO_FONT_DIR +
                " (or set GA_CENTURY_GOTHIC_DIR) to switch."),
    )


def describe() -> dict:
    """Serialisable summary for API responses and the final report."""
    choice = resolve_font()
    return {
        "mode": choice.mode,
        "family": choice.family,
        "needsLicenceAction": choice.needs_licence_action,
        "notice": choice.notice,
        "files": {k: os.path.basename(v) for k, v in choice.files.items()},
        "expectedPdfFontTokens": list(choice.expected_pdf_tokens),
    }
