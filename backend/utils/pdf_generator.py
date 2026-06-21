"""
utils/pdf_generator.py — Render a generated custom paper (and its mark scheme)
to PDF bytes with reportlab.

Both functions accept the same ``paper_data`` dict — the JSON returned by
POST /api/generate-paper — and return the finished PDF as ``bytes`` so the
caller can stream it as a file download.

The layout mimics a Cambridge IGCSE paper: a title block (subject, total marks,
time allowance), then one numbered section per question, with sub-parts
("(a)", "(b)", "(i)") indented, and a page number centred at the foot of every
page.
"""
from __future__ import annotations

import io
import os
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image as RLImage,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Bundle the DejaVu Sans family (committed under backend/fonts/) so the full
# Unicode maths range renders as real glyphs. The path resolves from this file so
# it is independent of the process CWD, and the fonts travel in the repo so they
# are present on Railway at deploy time.
_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fonts")
_FONT_NORMAL = "DejaVuSans"
_FONT_BOLD = "DejaVuSans-Bold"
pdfmetrics.registerFont(TTFont(_FONT_NORMAL, os.path.join(_FONT_DIR, "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont(_FONT_BOLD, os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf")))
# Register the family so the inline <b> tag resolves to DejaVuSans-Bold.
pdfmetrics.registerFontFamily(
    _FONT_NORMAL, normal=_FONT_NORMAL, bold=_FONT_BOLD,
    italic=_FONT_NORMAL, boldItalic=_FONT_BOLD,
)

# Page geometry. Usable width = page width minus both margins; the question
# header table is split into a wide left cell and a fixed marks cell.
_MARGIN = 18 * mm
_USABLE_W = A4[0] - 2 * _MARGIN
_MARKS_COL_W = 24 * mm
_LEFT_COL_W = _USABLE_W - _MARKS_COL_W

# Roman-numeral tokens used to spot the deepest sub-parts, e.g. "(i)", "(ii)".
_ROMAN = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii"}
_PART_RE = re.compile(r"^\(([a-z]{1,4})\)")

# Diagram embedding. Figures live under backend/static/question_diagrams and the
# question's imageUrl is "/diagrams/<id>.png"; resolve by basename to the file on
# disk (no network). They were rasterised at this zoom, so pixels / zoom = points
# at the figure's true on-page size. Display is clamped to the usable width and a
# max height so a tall multi-figure stack still fits within the page margins.
_DIAGRAM_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "static", "question_diagrams"
)
_DIAGRAM_RENDER_ZOOM = 3.0
_MAX_IMG_H = 200 * mm


def _resolve_image(image_url: str) -> str | None:
    """Map a question's imageUrl ("/diagrams/<id>.png") to a local file path."""
    if not image_url:
        return None
    local = os.path.join(_DIAGRAM_DIR, os.path.basename(image_url))
    return local if os.path.exists(local) else None


def _image_flowable(path: str):
    """A center-aligned reportlab Image sized to the figure's true scale, clamped
    to the usable width and a max height, preserving aspect ratio."""
    iw, ih = ImageReader(path).getSize()
    if iw <= 0 or ih <= 0:
        return None
    aspect = ih / float(iw)
    disp_w = min(iw / _DIAGRAM_RENDER_ZOOM, _USABLE_W)
    disp_h = disp_w * aspect
    if disp_h > _MAX_IMG_H:
        disp_h = _MAX_IMG_H
        disp_w = disp_h / aspect
    img = RLImage(path, width=disp_w, height=disp_h)
    img.hAlign = "CENTER"
    return img


# --------------------------------------------------------------------------- #
# Time / text helpers
# --------------------------------------------------------------------------- #
def _time_minutes(total_marks: int) -> int:
    """(total_marks * 1.5) minutes, rounded to the nearest 15 (min 15)."""
    rounded = int(round((total_marks * 1.5) / 15.0) * 15)
    return max(rounded, 15)


def _format_time(minutes: int) -> str:
    """Render minutes as e.g. '1 hour 30 minutes' / '45 minutes'."""
    hours, mins = divmod(minutes, 60)
    parts = []
    if hours:
        parts.append(f"{hours} hour" + ("s" if hours != 1 else ""))
    if mins:
        parts.append(f"{mins} minute" + ("s" if mins != 1 else ""))
    return " ".join(parts) if parts else "0 minutes"


def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "GA_Title", parent=base["Title"], fontName=_FONT_BOLD, fontSize=18,
            spaceAfter=4, alignment=TA_CENTER,
        ),
        "subtitle": ParagraphStyle(
            "GA_Subtitle", parent=base["Normal"], fontName=_FONT_NORMAL, fontSize=11,
            alignment=TA_CENTER, textColor=colors.HexColor("#444444"),
            spaceAfter=2,
        ),
        "qnum": ParagraphStyle(
            "GA_QNum", parent=base["Normal"], fontName=_FONT_NORMAL, fontSize=11,
            leading=14,
        ),
        "marks": ParagraphStyle(
            "GA_Marks", parent=base["Normal"], fontName=_FONT_NORMAL, fontSize=11,
            leading=14, alignment=TA_RIGHT,
        ),
        "body": ParagraphStyle(
            "GA_Body", parent=base["Normal"], fontName=_FONT_NORMAL, fontSize=10.5,
            leading=14, leftIndent=6,
        ),
        "part1": ParagraphStyle(
            "GA_Part1", parent=base["Normal"], fontName=_FONT_NORMAL, fontSize=10.5,
            leading=14, leftIndent=16,
        ),
        "part2": ParagraphStyle(
            "GA_Part2", parent=base["Normal"], fontName=_FONT_NORMAL, fontSize=10.5,
            leading=14, leftIndent=30,
        ),
    }


# --------------------------------------------------------------------------- #
# Character sanitization
# --------------------------------------------------------------------------- #
# Cambridge PDFs embed maths via the Adobe "Symbol" font; PyMuPDF extracts those
# glyphs as Private-Use-Area code points (U+F0xx) which are NOT real Unicode, so
# no font can render them directly. We resolve those PUA code points to their true
# Unicode characters (e.g. U+F0B4 -> ×, U+F0D6 -> √, U+F028 -> "("). Genuine
# Unicode maths symbols are then left untouched: the bundled DejaVu Sans font
# renders the full range as real glyphs, so nothing is transliterated to ASCII.

# High Symbol-font codes (the byte left after stripping the U+F000 PUA offset)
# that are not plain ASCII -> their real Unicode meaning.
_SYMBOL_HIGH_TO_UNICODE = {
    0xB4: "×",  # multiply ×
    0xB1: "±",  # ±
    0xB8: "÷",  # ÷
    0xA3: "≤",  # ≤
    0xB3: "≥",  # ≥
    0xB9: "≠",  # ≠
    0xD6: "√",  # √
    0xA5: "∞",  # ∞
    0xE6: "(", 0xE7: "(", 0xE8: "(",  # left bracket pieces (tall brackets / vectors)
    0xF6: ")", 0xF7: ")", 0xF8: ")",  # right bracket pieces
}


def _depua(ch: str) -> str:
    """Resolve a Symbol-font PUA character (U+F0xx) to its real Unicode meaning."""
    o = ord(ch)
    if 0xF000 <= o <= 0xF0FF:
        base = o - 0xF000
        if 0x20 <= base <= 0x7E:
            return chr(base)  # plain ASCII operator / paren / digit / letter
        return _SYMBOL_HIGH_TO_UNICODE.get(base, "")
    return ch


def _markup(text: str) -> str:
    """Escape `text` for a reportlab Paragraph, resolving Symbol-font PUA code
    points to their real Unicode characters. The bundled DejaVu Sans font renders
    the full Unicode maths range, so genuine symbols (π, √, ≤, ², ×, ÷, …) pass
    through unchanged — no transliteration. Unresolvable PUA code points (private
    use, not real Unicode) are dropped rather than rendered as a tofu box."""
    out: list[str] = []
    for raw in text:
        ch = _depua(raw)
        if not ch:
            continue
        out.append(escape(ch))
    return "".join(out)


def _body_flowables(text: str, styles: dict) -> list:
    """Turn a multi-line question / mark-scheme body into indented Paragraphs.

    Lines opening with a part marker get indented: "(a)".."(z)" one level,
    roman numerals "(i)".."(xii)" two levels. Blank lines become small spacers.
    """
    flow = []
    for raw in (text or "").split("\n"):
        line = raw.rstrip()
        if not line.strip():
            flow.append(Spacer(1, 3))
            continue
        style = styles["body"]
        m = _PART_RE.match(line.strip())
        if m:
            style = styles["part2"] if m.group(1) in _ROMAN else styles["part1"]
        flow.append(Paragraph(_markup(line), style))
    return flow


def _split_body(text: str, styles: dict) -> tuple[list, list]:
    """Split a question body into (intro_flowables, parts_flowables): everything
    before the first "(a)"-style sub-part marker, and the sub-parts after it.
    Lets a diagram sit directly below the intro and above the sub-parts."""
    intro: list = []
    parts: list = []
    seen_part = False
    for raw in (text or "").split("\n"):
        line = raw.rstrip()
        target = parts if seen_part else intro
        if not line.strip():
            target.append(Spacer(1, 3))
            continue
        m = _PART_RE.match(line.strip())
        if m:
            seen_part = True
            target = parts
            style = styles["part2"] if m.group(1) in _ROMAN else styles["part1"]
        else:
            style = styles["part1"] if seen_part else styles["body"]
        target.append(Paragraph(_markup(line), style))
    return intro, parts


def _question_header(number: int, marks: int, meta: str, styles: dict) -> Table:
    """A two-column heading row: bold question number (+ meta) | marks, right."""
    left = f"<b>{number}</b>"
    if meta:
        left += f"&nbsp;&nbsp;<font size=8 color='#777777'>{_markup(meta)}</font>"
    tbl = Table(
        [[Paragraph(left, styles["qnum"]),
          Paragraph(f"<b>[{marks}]</b>", styles["marks"])]],
        colWidths=[_LEFT_COL_W, _MARKS_COL_W],
    )
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return tbl


def _header_story(title: str, subtitle: str, paper_data: dict, styles: dict) -> list:
    subject = paper_data.get("subject", "")
    subject_label = "Mathematics" if subject == "math" else str(subject).title()
    total_marks = int(paper_data.get("totalMarks", 0) or 0)
    num_q = int(paper_data.get("numQuestions", 0) or 0)
    minutes = _time_minutes(total_marks)

    story = [
        Paragraph(escape(title), styles["title"]),
        Paragraph(escape(subtitle), styles["subtitle"]),
        Paragraph(f"Subject: {escape(subject_label)}", styles["subtitle"]),
        Paragraph(f"Total Marks: {total_marks}", styles["subtitle"]),
        Paragraph(f"Number of Questions: {num_q}", styles["subtitle"]),
        Paragraph(f"Time: {_format_time(minutes)}", styles["subtitle"]),
        Spacer(1, 10),
    ]
    return story


def _make_page_decorator(header_line: str):
    """Return a canvas callback that draws a running header (paper title, subject,
    total marks and time) on EVERY page plus a centred page number at the foot."""
    def _decorate(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(_FONT_NORMAL, 8)
        canvas.setFillColor(colors.HexColor("#999999"))
        canvas.drawCentredString(A4[0] / 2.0, A4[1] - 12 * mm, header_line)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawCentredString(A4[0] / 2.0, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()
    return _decorate


def _running_header_line(subtitle: str, paper_data: dict) -> str:
    """Compact one-line running header carrying the key paper metadata so every
    page (not just page 1) shows title, subject, total marks and time allowed."""
    subject = paper_data.get("subject", "")
    subject_label = "Mathematics" if subject == "math" else str(subject).title()
    total_marks = int(paper_data.get("totalMarks", 0) or 0)
    time_str = _format_time(_time_minutes(total_marks))
    return (
        f"Grade AI Custom Practice Paper · {subtitle} · "
        f"{subject_label} · {total_marks} marks · {time_str}"
    )


def _build(title: str, subtitle: str, paper_data: dict, blocks: list) -> bytes:
    """Assemble a PDF from a header plus a list of
    (number, marks, meta, body, image_path) blocks (image_path may be None)."""
    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=_MARGIN, rightMargin=_MARGIN,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=title,
    )
    story = _header_story(title, subtitle, paper_data, styles)
    for number, marks, meta, body, image_path in blocks:
        header = _question_header(number, marks, meta, styles)
        img = _image_flowable(image_path) if image_path else None
        if img is not None:
            # Diagram question: keep header + intro + figure together (so the
            # figure can never be orphaned from its question across a page
            # break), then let the sub-parts flow after it.
            intro, parts = _split_body(body, styles)
            keep = [header, *intro, Spacer(1, 5), img, Spacer(1, 3)]
            story.append(KeepTogether(keep))
            story.extend(parts)
        else:
            # Text-only question: keep header + whole body together (reportlab
            # still splits a question genuinely taller than one page).
            block = [header, *_body_flowables(body, styles)]
            story.append(KeepTogether(block))
        story.append(Spacer(1, 12))
    decorate = _make_page_decorator(_running_header_line(subtitle, paper_data))
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def generate_question_paper_pdf(paper_data: dict) -> bytes:
    """Render the question paper (questions only) to PDF bytes."""
    blocks = []
    for q in paper_data.get("questions", []):
        meta = ", ".join(
            str(v) for v in (q.get("topic"), q.get("difficulty")) if v
        )
        image_path = _resolve_image(q.get("imageUrl", "")) if q.get("hasImage") else None
        blocks.append((
            q.get("assignedNumber"),
            q.get("marks", 0),
            meta,
            q.get("questionText", ""),
            image_path,
        ))
    return _build(
        "Grade AI Custom Practice Paper", "Question Paper", paper_data, blocks,
    )


def generate_mark_scheme_pdf(paper_data: dict) -> bytes:
    """Render the mark scheme to PDF bytes."""
    blocks = []
    for item in paper_data.get("markScheme", []):
        blocks.append((
            item.get("questionNumber"),
            item.get("marks", 0),
            "",
            item.get("markSchemeText", ""),
            None,  # mark scheme never embeds the figure
        ))
    return _build(
        "Grade AI Custom Practice Paper", "Mark Scheme", paper_data, blocks,
    )
