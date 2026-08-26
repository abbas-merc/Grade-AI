# Licensed Century Gothic goes here

Century Gothic is a **commercial Monotype typeface**. It is not redistributable,
so no font file is committed to this repository.

To typeset generated papers in the school's real font, drop the licensed files
into this directory (or set `GA_CENTURY_GOTHIC_DIR` to wherever they live):

    GOTHIC.TTF      regular
    GOTHICB.TTF     bold
    GOTHICI.TTF     italic
    GOTHICBI.TTF    bold italic

`CenturyGothic.ttf` / `CenturyGothic-Bold.ttf` style names are recognised too —
see `_CENTURY_GOTHIC_FILES` in `backend/utils/latex/fonts.py`.

Without them the pipeline falls back to **TeX Gyre Adventor** (GUST Font
Licence, the URW Gothic revival), which is the standard free stand-in for
Century Gothic. Every generated PDF reports which one was used, via the
`X-GradeAI-Paper-Font` response header and `GET /api/generate-paper/typesetting-status`.

**A Windows or Microsoft Office licence does not permit copying these files into
a Linux server image.** Confirm the school's licence covers server-side
embedding before shipping them to production.
