"""
install_tectonic.py — Put the LaTeX engine where the backend can find it.

Downloads the pinned Tectonic release for this platform into ``backend/tools/``
(git-ignored) and warms its resource cache with a throwaway compile, so the first
real paper generation does no network I/O.

Tectonic is used instead of a TeX Live install because a TeX Live scheme large
enough for fontspec + unicode-math + the TeX Gyre fonts is several GB, while
Tectonic is a single ~50 MB binary that fetches the individual support files it
needs from a signed bundle and caches them (~40 MB for this document class).

Run from backend/:
    python scripts/install_tectonic.py           # install + warm the cache
    python scripts/install_tectonic.py --check   # report status only
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

TECTONIC_VERSION = "0.17.0"
_BASE = ("https://github.com/tectonic-typesetting/tectonic/releases/download/"
         "tectonic%40" + TECTONIC_VERSION + "/")

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
TOOLS = os.path.join(BACKEND, "tools")

# (asset suffix, archive kind) per platform.
_ASSETS = {
    ("Windows", "AMD64"): (f"tectonic-{TECTONIC_VERSION}-x86_64-pc-windows-msvc.zip", "zip"),
    ("Linux", "x86_64"): (f"tectonic-{TECTONIC_VERSION}-x86_64-unknown-linux-musl.tar.gz", "tar"),
    ("Linux", "aarch64"): (f"tectonic-{TECTONIC_VERSION}-aarch64-unknown-linux-musl.tar.gz", "tar"),
    ("Darwin", "arm64"): (f"tectonic-{TECTONIC_VERSION}-aarch64-apple-darwin.tar.gz", "tar"),
    ("Darwin", "x86_64"): (f"tectonic-{TECTONIC_VERSION}-x86_64-apple-darwin.tar.gz", "tar"),
}

_WARMUP = r"""\documentclass[11pt,a4paper]{article}
\usepackage{fontspec}\usepackage{amsmath}\usepackage{geometry}
\usepackage{graphicx}\usepackage{enumitem}\usepackage{needspace}
\usepackage{array}\usepackage{longtable}\usepackage{xcolor}\usepackage{fancyhdr}
\setmainfont{texgyreadventor-regular.otf}[BoldFont=texgyreadventor-bold.otf,
  ItalicFont=texgyreadventor-italic.otf, BoldItalicFont=texgyreadventor-bolditalic.otf]
\usepackage{unicode-math}
\setmathfont{latinmodern-math.otf}
\setmathfont{texgyreadventor-regular.otf}[range={up,"0030-"0039}]
\setmathfont{texgyreadventor-italic.otf}[range={it}]
\begin{document}
Warm-up $\frac{3}{4}\sqrt[3]{27}\ x^{2}\ \begin{pmatrix}3\\-2\end{pmatrix}
A\cap B\neq\emptyset\ x\leqslant 5\ 47^\circ\ 1.5\times10^{-3}$
\begin{longtable}{|p{20mm}|p{40mm}|}\hline a & b \\ \hline\end{longtable}
\end{document}
"""


def binary_path() -> str:
    return os.path.join(TOOLS, "tectonic.exe" if os.name == "nt" else "tectonic")


def _asset() -> tuple[str, str]:
    key = (platform.system(), platform.machine())
    if key not in _ASSETS:
        # x86_64 reports as AMD64 on Windows, x86_64 elsewhere; normalise once.
        alt = (key[0], {"AMD64": "x86_64", "arm64": "aarch64"}.get(key[1], key[1]))
        if alt in _ASSETS:
            return _ASSETS[alt]
        raise SystemExit(f"No pinned Tectonic build for {key}. "
                         "Install tectonic manually and set TECTONIC_BIN.")
    return _ASSETS[key]


def install() -> str:
    dest = binary_path()
    if os.path.exists(dest):
        print("already installed:", dest)
        return dest
    os.makedirs(TOOLS, exist_ok=True)
    name, kind = _asset()
    url = _BASE + name
    print("downloading", url)
    with tempfile.TemporaryDirectory() as tmp:
        archive = os.path.join(tmp, name)
        urllib.request.urlopen(url, timeout=300)  # fail fast on a bad URL
        urllib.request.urlretrieve(url, archive)
        if kind == "zip":
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(tmp)
        else:
            import tarfile
            with tarfile.open(archive) as tf:
                tf.extractall(tmp)
        src = None
        for root, _dirs, files in os.walk(tmp):
            for f in files:
                if f in ("tectonic", "tectonic.exe"):
                    src = os.path.join(root, f)
        if not src:
            raise SystemExit("archive did not contain a tectonic binary")
        shutil.copyfile(src, dest)
    if os.name != "nt":
        os.chmod(dest, 0o755)
    print("installed:", dest)
    return dest


def warm(binary: str) -> None:
    """Compile a document using every package the templates need, so the bundle
    cache holds them and production compiles need no network."""
    with tempfile.TemporaryDirectory() as tmp:
        tex = os.path.join(tmp, "warmup.tex")
        with open(tex, "w", encoding="utf-8") as fh:
            fh.write(_WARMUP)
        proc = subprocess.run([binary, "-X", "compile", tex, "--outdir", tmp],
                              capture_output=True, text=True, timeout=900)
        ok = proc.returncode == 0 and os.path.exists(os.path.join(tmp, "warmup.pdf"))
        print("cache warm-up:", "ok" if ok else "FAILED")
        if not ok:
            print(proc.stdout[-3000:])
            print(proc.stderr[-3000:])
            raise SystemExit(1)


def main() -> None:
    if "--check" in sys.argv:
        sys.path.insert(0, BACKEND)
        from utils.latex.engine import engine_status
        import json
        print(json.dumps(engine_status(), indent=2))
        return
    binary = install()
    warm(binary)
    print("\nTECTONIC_BIN is not required — the backend also looks in backend/tools/.")


if __name__ == "__main__":
    main()
