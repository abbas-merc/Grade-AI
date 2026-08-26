"""
utils.latex — LaTeX (XeLaTeX) typesetting pipeline for generated papers.

Replaces the two lossy paths the paper generator had before:
  * plain PDF-extracted text, which mangles maths notation and loses layout, and
  * whole-question screenshots, which are unfixable images in the wrong font.

Modules
-------
config      every tunable constant (answer space, margins, timeouts, fonts)
fonts       resolve the document font and report its licence status honestly
latexify    sanitise / validate the LaTeX fragments produced by extraction
templates   turn an assembled-paper dict into a .tex source (paper + mark scheme)
engine      run the XeLaTeX engine with a timeout and attribute failures
assemble    build that dict from the existing generate-paper responses
"""
from __future__ import annotations

from . import config  # noqa: F401
