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
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    Image as RLImage,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from PIL import Image as PILImage

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

# Question-snippet embedding. Every question now IS a cropped image stored at
# "/question_snippets/<id>.png" and served from backend static; resolve by
# basename to the file on disk (no network). The image is scaled to the usable
# page width. A question that spans multiple original pages (every Paper-4
# question) yields a tall image; since a reportlab Image flowable cannot split
# across pages, such an image is sliced into page-height tiles that flow over
# consecutive pages. Legacy "/diagrams/<id>.png" paths still resolve too.
_SNIPPET_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "static", "question_snippets"
)
_DIAGRAM_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "static", "question_diagrams"
)
# Max height (pt) of one image slice, leaving room below the question header on
# the first slice within the A4 content frame (~740pt after margins).
_MAX_SLICE_H = 690.0


def _resolve_snippet(image_url: str) -> str | None:
    """Map a question image path ("/question_snippets/<id>.png" or legacy
    "/diagrams/<id>.png") to a local file under backend/static."""
    if not image_url:
        return None
    base = os.path.basename(image_url)
    for directory in (_SNIPPET_DIR, _DIAGRAM_DIR):
        path = os.path.join(directory, base)
        if os.path.exists(path):
            return path
    return None


def _find_white_row(gray, target: int, lo: int) -> int:
    """Scan up from `target` to `lo` for a fully-white pixel row, so an image
    slice breaks in the whitespace between lines/figures rather than through
    them. Returns `target` if no clean gap is found in the window."""
    h = gray.height
    target = min(target, h - 1)
    yy = target
    while yy > lo:
        if gray.crop((0, yy, gray.width, yy + 1)).getextrema()[0] >= 248:
            return yy
        yy -= 2
    return target


def _question_image_flowables(path: str) -> list:
    """Render a question snippet scaled to the usable page width, preserving
    aspect ratio. If the scaled height exceeds one page's content area, slice it
    into page-height tiles (an Image flowable can't itself paginate) so a tall
    multi-page question flows across consecutive pages — breaking each slice at a
    whitespace gap so no line of text/figure is split. Returns the flowables."""
    iw, ih = ImageReader(path).getSize()
    if iw <= 0 or ih <= 0:
        return []
    scale = _USABLE_W / float(iw)
    if ih * scale <= _MAX_SLICE_H:
        img = RLImage(path, width=_USABLE_W, height=ih * scale)
        img.hAlign = "LEFT"
        return [img]

    pil = PILImage.open(path).convert("RGB")
    gray = pil.convert("L")
    tile_px = max(1, int(_MAX_SLICE_H / scale))
    # Compute slice boundaries, snapping each to nearby whitespace (no closer
    # than 55% of a full tile, so slices never get pathologically thin).
    cuts = [0]
    while cuts[-1] + tile_px < ih:
        target = cuts[-1] + tile_px
        cut = _find_white_row(gray, target, cuts[-1] + int(tile_px * 0.55))
        cuts.append(cut)
    cuts.append(ih)

    flows: list = []
    for top, bot in zip(cuts, cuts[1:]):
        tile = pil.crop((0, top, iw, bot))
        bio = io.BytesIO()
        tile.save(bio, format="PNG")
        bio.seek(0)
        # Pass the BytesIO itself (reportlab keys off hasattr(fp, "read") and
        # reads it immediately); the tile's display height preserves aspect.
        img = RLImage(bio, width=_USABLE_W, height=tile.height * scale)
        img.hAlign = "LEFT"
        flows.append(img)
    return flows


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
    (number, marks, meta, flows, keep_all) blocks, where `flows` is the question
    body's flowables. keep_all=True keeps the header + whole body together (mark
    scheme); keep_all=False keeps the header with only the first flowable and
    lets the rest flow across pages (sliced question images)."""
    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=_MARGIN, rightMargin=_MARGIN,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=title,
    )
    story = _header_story(title, subtitle, paper_data, styles)
    for number, marks, meta, flows, keep_all in blocks:
        header = _question_header(number, marks, meta, styles)
        if not flows:
            story.append(header)
        elif keep_all:
            # Mark scheme: keep header + whole body together (reportlab still
            # splits a body genuinely taller than one page).
            story.append(KeepTogether([header, *flows]))
        else:
            # Question image: keep the header with the first slice; any further
            # slices (a multi-page question) flow onto the following pages.
            story.append(KeepTogether([header, Spacer(1, 4), flows[0]]))
            story.extend(flows[1:])
        story.append(Spacer(1, 14))
    decorate = _make_page_decorator(_running_header_line(subtitle, paper_data))
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def generate_question_paper_pdf(paper_data: dict) -> bytes:
    """Render the question paper (question images only) to PDF bytes.

    Each question is embedded as its cropped Cambridge image (preserving the
    original maths formatting and diagrams), with the question number + marks
    printed above it. No question text is rendered — it already lives in the
    image."""
    styles = _styles()
    blocks = []
    for q in paper_data.get("questions", []):
        meta = ", ".join(
            str(v) for v in (q.get("topic"), q.get("difficulty")) if v
        )
        path = _resolve_snippet(q.get("questionImageUrl", ""))
        if path:
            flows = _question_image_flowables(path)
        else:
            flows = [Paragraph("[question image unavailable]", styles["body"])]
        blocks.append((
            q.get("assignedNumber"),
            q.get("marks", 0),
            meta,
            flows,
            False,
        ))
    return _build(
        "Grade AI Custom Practice Paper", "Question Paper", paper_data, blocks,
    )


def generate_mark_scheme_pdf(paper_data: dict) -> bytes:
    """Render the mark scheme to PDF bytes (still text-based)."""
    styles = _styles()
    blocks = []
    for item in paper_data.get("markScheme", []):
        flows = _body_flowables(item.get("markSchemeText", ""), styles)
        blocks.append((
            item.get("questionNumber"),
            item.get("marks", 0),
            "",
            flows,
            True,
        ))
    return _build(
        "Grade AI Custom Practice Paper", "Mark Scheme", paper_data, blocks,
    )


# --------------------------------------------------------------------------- #
# Marked results PDF
# --------------------------------------------------------------------------- #
# A teacher-shareable report of a completed marking (the Firestore marking
# document). It reuses the established document family — DejaVu Sans, A4, the
# same margins, a centred running header and a footed page number — and adds a
# brand-blue summary block plus per-question cards.
#
# Colour is used constructively, never as a pass/fail verdict: each question
# carries a thin left-border accent and a faint background tint keyed to how the
# student did (full / partial / none) in calm tones, so the report can go home to
# a student or parent without reading like a red-ink report card.

_BRAND = "#1B4DFF"          # app brand blue (matches COLORS.primary)
_BRAND_TINT = "#EEF2FF"     # faint brand wash for the summary card
_INK = "#1A1A1A"            # primary text
_MUTED = "#6B6B68"          # secondary text
_FAINT = "#9B9B97"          # tertiary text / labels
_HAIRLINE = "#E8E8E4"       # card borders
_BAR_TRACK = "#DCE3F5"      # performance-bar track

# Per-question accent + background tint, keyed to performance tier. Deliberately
# soft: green reads "complete", amber "in progress", slate "not yet" — none of
# them alarmist.
_TIER = {
    "full":    {"accent": "#2BA767", "bg": "#F1F8F4", "marks": "#1E7A49"},
    "partial": {"accent": "#E0900F", "bg": "#FBF4E8", "marks": "#9A640A"},
    "zero":    {"accent": "#9AA1AC", "bg": "#F4F5F7", "marks": "#6B6B68"},
}


def _perf_tier(awarded: int, available: int) -> str:
    """Classify a question result as full / partial / zero marks."""
    if available <= 0 or awarded <= 0:
        return "zero"
    if awarded >= available:
        return "full"
    return "partial"


class _PerformanceBar(Flowable):
    """A slim rounded progress bar: a light track with a brand-blue fill whose
    width is the score fraction. Drawn with reportlab primitives (no image)."""

    def __init__(self, fraction: float, width: float, height: float = 9.0):
        super().__init__()
        self.fraction = max(0.0, min(1.0, fraction))
        self.width = width
        self.height = height

    def wrap(self, *_args):
        return (self.width, self.height)

    def draw(self):
        c = self.canv
        r = self.height / 2.0
        c.setFillColor(colors.HexColor(_BAR_TRACK))
        c.roundRect(0, 0, self.width, self.height, r, fill=1, stroke=0)
        fill_w = self.width * self.fraction
        if fill_w > 0:
            # Keep the rounded cap from collapsing on tiny scores.
            fill_w = max(fill_w, self.height)
            c.setFillColor(colors.HexColor(_BRAND))
            c.roundRect(0, 0, fill_w, self.height, r, fill=1, stroke=0)


def format_marked_date(result_data: dict) -> str:
    """Human-readable 'date marked', e.g. '20 June 2026'.

    Prefers the client-written `graded_at` ISO string, falls back to the
    Firestore `created_at` timestamp, then to today. Always returns a value so
    the header and filename never break on missing/odd data.
    """
    raw = (result_data or {}).get("graded_at")
    dt: datetime | None = None
    if isinstance(raw, str) and raw.strip():
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            dt = None
    if dt is None:
        created = (result_data or {}).get("created_at")
        if isinstance(created, datetime):
            dt = created
        elif hasattr(created, "isoformat"):  # Firestore DatetimeWithNanoseconds
            try:
                dt = datetime.fromisoformat(created.isoformat())
            except (ValueError, TypeError):
                dt = None
    if dt is None:
        dt = datetime.now(timezone.utc)
    # %-d is non-portable on Windows, so strip a leading zero by hand.
    return f"{dt.day} {dt.strftime('%B %Y')}"


def _result_styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "brand": ParagraphStyle(
            "R_Brand", parent=base["Normal"], fontName=_FONT_BOLD, fontSize=12,
            textColor=colors.HexColor(_BRAND), alignment=TA_CENTER, spaceAfter=3,
        ),
        "title": ParagraphStyle(
            "R_Title", parent=base["Title"], fontName=_FONT_BOLD, fontSize=20,
            textColor=colors.HexColor(_INK), alignment=TA_CENTER, spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "R_Subtitle", parent=base["Normal"], fontName=_FONT_NORMAL,
            fontSize=10.5, textColor=colors.HexColor(_MUTED), alignment=TA_CENTER,
            spaceAfter=1,
        ),
        "student": ParagraphStyle(
            "R_Student", parent=base["Normal"], fontName=_FONT_NORMAL, fontSize=11,
            textColor=colors.HexColor(_INK), alignment=TA_LEFT,
        ),
        "sumLabel": ParagraphStyle(
            "R_SumLabel", parent=base["Normal"], fontName=_FONT_BOLD, fontSize=9,
            textColor=colors.HexColor(_MUTED), alignment=TA_CENTER, spaceAfter=3,
        ),
        "sumScore": ParagraphStyle(
            "R_SumScore", parent=base["Normal"], fontName=_FONT_BOLD, fontSize=30,
            leading=34, textColor=colors.HexColor(_BRAND), alignment=TA_CENTER,
        ),
        "sumPct": ParagraphStyle(
            "R_SumPct", parent=base["Normal"], fontName=_FONT_NORMAL, fontSize=12,
            textColor=colors.HexColor(_MUTED), alignment=TA_CENTER, spaceAfter=2,
        ),
        "sumNote": ParagraphStyle(
            "R_SumNote", parent=base["Normal"], fontName=_FONT_NORMAL, fontSize=9,
            leading=12, textColor=colors.HexColor("#9A640A"), alignment=TA_CENTER,
        ),
        "section": ParagraphStyle(
            "R_Section", parent=base["Normal"], fontName=_FONT_BOLD, fontSize=14,
            textColor=colors.HexColor(_INK), alignment=TA_LEFT, spaceBefore=2,
        ),
        "qTitle": ParagraphStyle(
            "R_QTitle", parent=base["Normal"], fontName=_FONT_BOLD, fontSize=12,
            textColor=colors.HexColor(_INK), leading=15,
        ),
        "qMarks": ParagraphStyle(
            "R_QMarks", parent=base["Normal"], fontName=_FONT_BOLD, fontSize=12,
            alignment=TA_RIGHT, leading=15,
        ),
        "criterion": ParagraphStyle(
            "R_Criterion", parent=base["Normal"], fontName=_FONT_NORMAL,
            fontSize=10, leading=14, textColor=colors.HexColor(_INK),
            leftIndent=2, spaceAfter=2,
        ),
        "noAnswer": ParagraphStyle(
            "R_NoAnswer", parent=base["Normal"], fontName=_FONT_NORMAL,
            fontSize=10, leading=14, textColor=colors.HexColor(_MUTED),
        ),
        "fbLabel": ParagraphStyle(
            "R_FbLabel", parent=base["Normal"], fontName=_FONT_BOLD, fontSize=7.5,
            textColor=colors.HexColor(_FAINT), spaceBefore=2, spaceAfter=2,
        ),
        "feedback": ParagraphStyle(
            "R_Feedback", parent=base["Normal"], fontName=_FONT_NORMAL,
            fontSize=10.5, leading=15, textColor=colors.HexColor(_INK),
        ),
    }


# Inner widths once the card / summary padding is removed, so any fixed-width
# child table (the header row, the bar) fits exactly within its container.
_SUMMARY_PAD = 16
_SUMMARY_INNER_W = _USABLE_W - 2 * _SUMMARY_PAD
_CARD_PAD = 14
_CARD_INNER_W = _USABLE_W - 2 * _CARD_PAD
_CARD_MARKS_W = 28 * mm
_CARD_TITLE_W = _CARD_INNER_W - _CARD_MARKS_W


def _summary_block(awarded: int, available: int, pct: int,
                   mismatch: bool, styles: dict) -> Table:
    """The prominent score card near the top: big total, percentage, a brand
    performance bar, and (if flagged) a marks-mismatch note."""
    inner: list = [
        Paragraph("TOTAL SCORE", styles["sumLabel"]),
        Paragraph(f"{awarded} / {available}", styles["sumScore"]),
        Paragraph(f"{pct}%", styles["sumPct"]),
        Spacer(1, 8),
        _PerformanceBar(pct / 100.0, _SUMMARY_INNER_W),
    ]
    if mismatch:
        inner.append(Spacer(1, 8))
        inner.append(Paragraph(
            "Note: total marks may not reflect final allocation, please review.",
            styles["sumNote"],
        ))
    tbl = Table([[inner]], colWidths=[_USABLE_W])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(_BRAND_TINT)),
        ("LINEBEFORE", (0, 0), (0, -1), 4, colors.HexColor(_BRAND)),
        ("LEFTPADDING", (0, 0), (-1, -1), _SUMMARY_PAD),
        ("RIGHTPADDING", (0, 0), (-1, -1), _SUMMARY_PAD),
        ("TOPPADDING", (0, 0), (-1, -1), _SUMMARY_PAD),
        ("BOTTOMPADDING", (0, 0), (-1, -1), _SUMMARY_PAD),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return tbl


def _question_card(q: dict, styles: dict) -> Table:
    """One question's result rendered as a tinted card with a coloured left
    accent: header (number + marks), the point-by-point mark breakdown, and the
    feedback. Robust to missing/empty fields and no-answer questions."""
    qnum = str(q.get("question_number") or "").strip()
    try:
        awarded = int(q.get("marks_awarded") or 0)
    except (TypeError, ValueError):
        awarded = 0
    try:
        available = int(q.get("marks_available") or 0)
    except (TypeError, ValueError):
        available = 0
    feedback = str(q.get("feedback") or "").strip()
    extracted = str(q.get("extracted_answer") or "").strip()
    breakdown = q.get("mark_breakdown") or []

    tier = _TIER[_perf_tier(awarded, available)]

    header = Table(
        [[
            Paragraph(f"Question {_markup(qnum)}" if qnum else "Question", styles["qTitle"]),
            Paragraph(
                f"<font color='{tier['marks']}'>{awarded} / {available}</font>",
                styles["qMarks"],
            ),
        ]],
        colWidths=[_CARD_TITLE_W, _CARD_MARKS_W],
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    cell: list = [header]

    # Point-by-point breakdown (the criteria the student hit / missed). Renders
    # whether there are many sub-points or none — an empty list just falls
    # through to the feedback.
    rendered_points = 0
    if isinstance(breakdown, list):
        for pt in breakdown:
            if not isinstance(pt, dict):
                continue
            criterion = str(pt.get("criterion") or "").strip()
            reason = str(pt.get("reason") or "").strip()
            if not criterion and not reason:
                continue
            got = bool(pt.get("awarded"))
            sym = "✓" if got else "✗"
            sym_color = "#2BA767" if got else "#9AA1AC"
            parts = [f"<font name='{_FONT_BOLD}' color='{sym_color}'>{sym}</font>&nbsp;&nbsp;"]
            if criterion:
                parts.append(f"<b>{_markup(criterion)}</b>")
            if reason:
                parts.append((" — " if criterion else "") + _markup(reason))
            if rendered_points == 0:
                cell.append(Spacer(1, 6))
            cell.append(Paragraph("".join(parts), styles["criterion"]))
            rendered_points += 1

    # No-answer questions: make the empty state explicit rather than blank.
    if awarded == 0 and not extracted and rendered_points == 0:
        cell.append(Spacer(1, 6))
        cell.append(Paragraph(
            "No answer was found for this question on the submitted pages.",
            styles["noAnswer"],
        ))

    if feedback:
        cell.append(Paragraph("FEEDBACK", styles["fbLabel"]))
        cell.append(Paragraph(_markup(feedback), styles["feedback"]))

    card = Table([[cell]], colWidths=[_USABLE_W])
    card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(tier["bg"])),
        ("LINEBEFORE", (0, 0), (0, -1), 3, colors.HexColor(tier["accent"])),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(_HAIRLINE)),
        ("LEFTPADDING", (0, 0), (-1, -1), _CARD_PAD),
        ("RIGHTPADDING", (0, 0), (-1, -1), _CARD_PAD),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return card


def _make_results_page_decorator(running_header: str, footer_left: str):
    """Running header on every page (so multi-page reports stay branded) plus a
    foot carrying 'Generated by Grade AI · <date>' and the page number."""
    def _decorate(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(_FONT_NORMAL, 8)
        canvas.setFillColor(colors.HexColor("#9AA1AC"))
        canvas.drawCentredString(A4[0] / 2.0, A4[1] - 12 * mm, running_header)
        canvas.drawString(_MARGIN, 10 * mm, footer_left)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawRightString(A4[0] - _MARGIN, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()
    return _decorate


def generate_results_pdf(result_data: dict) -> bytes:
    """Render a completed marking (the Firestore marking document) to a clean,
    shareable PDF and return the bytes.

    Expected `result_data` shape (extra keys are ignored):
        paper_name: str
        graded_at / created_at: date marked (optional)
        student_name: str (optional — left as a fill-in blank if absent)
        total_marks_awarded / total_marks_available: int
        marks_total_mismatch: bool (optional)
        results: [
            {question_number, marks_awarded, marks_available,
             mark_breakdown: [{criterion, awarded, reason}], feedback,
             extracted_answer}
        ]
    """
    data = result_data or {}
    paper_name = str(data.get("paper_name") or "Practice Paper").strip() or "Practice Paper"
    student_name = str(data.get("student_name") or "").strip()
    date_str = format_marked_date(data)

    try:
        total_awarded = int(data.get("total_marks_awarded") or 0)
    except (TypeError, ValueError):
        total_awarded = 0
    try:
        total_available = int(data.get("total_marks_available") or 0)
    except (TypeError, ValueError):
        total_available = 0
    pct = round((total_awarded / total_available) * 100) if total_available > 0 else 0
    mismatch = bool(data.get("marks_total_mismatch"))
    results = data.get("results") or []

    styles = _result_styles()
    story: list = [
        Paragraph("Grade AI", styles["brand"]),
        Paragraph("Marked Results", styles["title"]),
        Paragraph(_markup(paper_name), styles["subtitle"]),
        Paragraph(f"Marked {escape(date_str)}", styles["subtitle"]),
        Spacer(1, 10),
    ]
    if student_name:
        story.append(Paragraph(f"<b>Student:</b> {_markup(student_name)}", styles["student"]))
    else:
        # No student field is captured by the app, so leave a writable blank the
        # teacher can fill in after printing.
        story.append(Paragraph("Student Name: " + "_" * 36, styles["student"]))
    story.append(Spacer(1, 14))

    story.append(KeepTogether(_summary_block(total_awarded, total_available, pct, mismatch, styles)))
    story.append(Spacer(1, 18))
    story.append(Paragraph("Question Breakdown", styles["section"]))
    story.append(Spacer(1, 8))

    if results:
        for q in results:
            if not isinstance(q, dict):
                continue
            # KeepTogether ensures a question's marks + feedback never split
            # across a page break (reportlab still splits one taller than a page).
            story.append(KeepTogether(_question_card(q, styles)))
            story.append(Spacer(1, 10))
    else:
        story.append(Paragraph("No question results are available for this paper.", styles["noAnswer"]))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=_MARGIN, rightMargin=_MARGIN,
        topMargin=20 * mm, bottomMargin=18 * mm,
        title=f"Marked Results — {paper_name}",
    )
    decorate = _make_results_page_decorator(
        f"Grade AI · Marked Results · {paper_name}",
        f"Generated by Grade AI · {date_str}",
    )
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()
