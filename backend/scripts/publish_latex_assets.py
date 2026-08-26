"""
publish_latex_assets.py — Copy the LaTeX pipeline's build artefacts into static/.

The figure and stem crops are produced under ``scripts/`` by
``build_part_figures.py``. The running backend serves them from
``backend/static/question_figures`` — the same arrangement already used for
``question_snippets`` and ``question_diagrams`` (Firebase Storage is not
available on this project: it has no billing account, so no bucket can be
provisioned).

Run from backend/:
  python scripts/publish_latex_assets.py            # copy new/changed files
  python scripts/publish_latex_assets.py --prune    # also delete orphans
"""
from __future__ import annotations

import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)

# Only the diagram crops are published. The question-stem and letter-part-stem
# crops under scripts/question_stems/ are input to the offline extraction — the
# typesetter renders their text as LaTeX, never as a picture — so shipping them
# would add ~10 MB to the repo and the image for nothing.
PAIRS = [
    (os.path.join(HERE, "question_figures"),
     os.path.join(BACKEND, "static", "question_figures")),
]


def publish(src: str, dst: str, prune: bool) -> tuple[int, int]:
    if not os.path.isdir(src):
        return 0, 0
    os.makedirs(dst, exist_ok=True)
    copied = 0
    names = set()
    for name in os.listdir(src):
        if not name.lower().endswith(".png"):
            continue
        names.add(name)
        s, d = os.path.join(src, name), os.path.join(dst, name)
        if (not os.path.exists(d)
                or os.path.getmtime(s) > os.path.getmtime(d)
                or os.path.getsize(s) != os.path.getsize(d)):
            shutil.copyfile(s, d)
            copied += 1
    removed = 0
    if prune:
        for name in os.listdir(dst):
            if name.lower().endswith(".png") and name not in names:
                os.remove(os.path.join(dst, name))
                removed += 1
    return copied, removed


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    prune = "--prune" in sys.argv
    for src, dst in PAIRS:
        copied, removed = publish(src, dst, prune)
        print(f"{os.path.basename(dst):20s} copied {copied:4d}   removed {removed:4d}"
              f"   -> {os.path.relpath(dst, BACKEND)}")


if __name__ == "__main__":
    main()
