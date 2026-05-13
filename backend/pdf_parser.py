"""
pdf_parser.py — PDF text extraction and IGCSE 0580 question/mark-scheme parsing.

Public API:
  extract_text_from_pdf(pdf_path)                -> str
  parse_questions_from_solved_paper(text)        -> list[dict]
  parse_markscheme(text)                         -> list[dict]
  print_parsing_preview(questions, markscheme)   -> None

Source PDF notes:
  - Solved paper PDFs may be image-only scans — PyMuPDF will return empty
    text. parse_questions_from_solved_paper returns [] in that case and
    seed.py falls back to driving questions from the mark scheme.
  - Mark scheme PDFs use a "Question / Answer / Marks / Partial Marks" table.
    Sub-parts like 1(a), 3(b)(ii) are normalised to "1a", "3b(ii)".
  - The mark scheme parser does two passes: header detection (sequential
    top-level integers and parenthesised sub-parts), then per-block analysis
    (locating partial-mark lines beginning with B1/M1/A1/FT/SC markers).
"""

from __future__ import annotations

import re
import fitz  # PyMuPDF


# ---------------------------------------------------------------------------
# 1. Raw text extraction
# ---------------------------------------------------------------------------

def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Open the PDF at pdf_path and return all page text joined with newlines.

    Args:
        pdf_path: Path to the PDF file, relative to the backend/ directory.

    Returns:
        Full text of all pages concatenated. Empty string if the PDF is
        image-only or cannot be read.
    """
    doc = fitz.open(pdf_path)
    try:
        return "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# 2. Solved paper parsing
# ---------------------------------------------------------------------------

# Matches a question header at the start of a line:
#   "1 "  "3 (a) "  "12 (b)(ii) "
_SOLVED_HEADER_RE = re.compile(
    r"^\s*(\d{1,2})\s*(?:\(([a-z])\))?\s*(?:\(([ivx]+)\))?\s+(?=\S)",
    re.MULTILINE,
)
# Marks shown as [2], [3 marks], [1 mark]
_MARKS_BRACKET_RE = re.compile(r"\[(\d{1,2})\s*marks?\s*\]|\[(\d{1,2})\]")


def parse_questions_from_solved_paper(text: str) -> list[dict]:
    """
    Parse the solved paper text into a list of question dicts.

    Each dict has keys:
        question_number  (str)  — e.g. "1", "2a", "3b(ii)"
        question_text    (str)  — full question wording
        marks_available  (int)  — from [N] bracket notation
        solved_working   (str)  — worked solution shown in the solved paper

    Returns [] if the text is empty or has no extractable structure
    (e.g. the PDF is image-only).
    """
    if not text or not text.strip():
        return []

    headers = list(_SOLVED_HEADER_RE.finditer(text))
    if not headers:
        return []

    questions: list[dict] = []
    for i, m in enumerate(headers):
        start = m.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        block = text[start:end].strip()

        qnum = _normalize_qnum(m.group(1), m.group(2), m.group(3))
        marks = _extract_marks_from_block(block)
        question_text, solved_working = _split_question_and_solution(block)

        questions.append({
            "question_number": qnum,
            "question_text": question_text,
            "marks_available": marks,
            "solved_working": solved_working,
        })

    return questions


def _normalize_qnum(num: str, letter: str | None, roman: str | None) -> str:
    """Build a canonical question number string from regex capture groups."""
    out = num
    if letter:
        out += letter
    if roman:
        out += f"({roman})"
    return out


def _extract_marks_from_block(block: str) -> int:
    """Extract the marks value from [N] or [N marks] notation in a block."""
    matches = _MARKS_BRACKET_RE.findall(block)
    if not matches:
        return 1
    last = matches[-1]
    digit = last[0] or last[1]
    try:
        return int(digit)
    except (ValueError, TypeError):
        return 1


def _split_question_and_solution(block: str) -> tuple[str, str]:
    """Split a question block into (question_text, solution_text)."""
    for marker in ("Solution:", "Solution", "Answer:", "Worked solution"):
        idx = block.find(marker)
        if idx != -1:
            return (
                block[:idx].strip(),
                block[idx + len(marker):].strip().lstrip(":").strip(),
            )
    # Fallback: split on first blank line
    parts = re.split(r"\n\s*\n", block, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return block.strip(), ""


# ---------------------------------------------------------------------------
# 3. Mark scheme parsing
# ---------------------------------------------------------------------------

# Sub-part header: number followed by one or more parenthesised groups.
# E.g. "1(a)", "13(a)(i)", "3(b)(ii)(a) answer text here"
_MS_HEADER_SUB_RE = re.compile(
    r"^\s*(\d{1,2})((?:\([a-z]+\)|\([ivx]+\))+)\s*(.*?)\s*$"
)

# A line containing only a small integer — top-level question or marks count.
# Disambiguated by sequential numbering in the block splitter.
_DIGIT_ALONE_RE = re.compile(r"^\s*(\d{1,2})\s*$")

# Partial-mark token: B1, M2, A1, FT, SC1, cao, nfww etc.
_MARK_POINT_START_RE = re.compile(
    r"(?:^|\s)(?:or\s+|OR\s+|and\s+)?"
    r"(?:[BMA][1-9]|FT\b|SC[1-9]|cao\b|nfww\b)"
)

# A "marker line" — a line whose first meaningful token is a partial-mark token.
_MARKER_LINE_RE = re.compile(
    r"^\s*(?:(\d{1,2})\s+)?"
    r"(?:or\s+|OR\s+|and\s+)?"
    r"(?:[BMA][1-9]|FT\b|SC[1-9]|cao\b|nfww\b)"
)

# Lines that are page headers / table column headers — discard these.
_NOISE_PATTERNS = [
    re.compile(r"^\s*Cambridge\s+IGCSE.*$"),
    re.compile(r"^\s*0580/\d+\s*$"),
    re.compile(r"^\s*PUBLISHED\s*$"),
    re.compile(r"^\s*May/June\s+\d{4}\s*$"),
    re.compile(r"^\s*©\s+Cambridge.*$"),
    re.compile(r"^\s*Page\s+\d+\s+of\s+\d+\s*$"),
    re.compile(r"^\s*Question\s*$"),
    re.compile(r"^\s*Answer\s*$"),
    re.compile(r"^\s*Marks\s*$"),
    re.compile(r"^\s*Partial\s+Marks\s*$"),
]


def parse_markscheme(text: str) -> list[dict]:
    """
    Parse a Cambridge mark-scheme PDF text dump into structured entries.

    Each returned dict has keys:
        question_number         (str)        — e.g. "1a", "3b(ii)"
        mark_points             (list[str])  — one entry per marking criterion
        total_marks             (int)        — total marks for this question part
        acceptable_alternatives (str)        — answer text / accepted forms

    Cambridge notation preserved in mark_points:
        M1 = method mark, A1 = accuracy mark (dep on M), B1/B2 = independent,
        ft = follow through, cao = correct answer only, oe = or equivalent,
        SC = special case, nfww = not from wrong working.
    """
    if not text:
        return []

    # Skip front matter — start at the actual marking table.
    table_start = text.find("Partial Marks")
    if table_start != -1:
        line_start = text.rfind("\n", 0, table_start) + 1
        text = text[line_start:]

    raw_lines = text.splitlines()
    lines = [ln for ln in raw_lines if not _is_noise(ln)]

    blocks = _split_into_question_blocks(lines)

    entries: list[dict] = []
    for qnum, block_lines in blocks:
        answer_text, total_marks, partial_text = _analyze_block(block_lines)
        mark_points = _build_mark_points(answer_text, partial_text, total_marks)
        entries.append({
            "question_number": qnum,
            "mark_points": mark_points,
            "total_marks": total_marks,
            "acceptable_alternatives": answer_text,
        })

    return _dedupe_entries(entries)


def _is_noise(line: str) -> bool:
    return any(p.match(line) for p in _NOISE_PATTERNS)


def _split_into_question_blocks(lines: list[str]) -> list[tuple[str, list[str]]]:
    """
    Walk the lines and group them into (question_number, body_lines) pairs.

    Header detection:
      - Sub-part headers like "1(a)" or "3(b)(ii)" are matched first.
      - Lines consisting only of a digit that is exactly one more than the
        current top-level counter are treated as top-level question headers.
      - Everything else is body content for the current block.
    """
    blocks: list[tuple[str, list[str]]] = []
    current_qnum: str | None = None
    current_lines: list[str] = []
    current_top_level = 0

    for line in lines:
        sub_match = _MS_HEADER_SUB_RE.match(line)
        alone_match = _DIGIT_ALONE_RE.match(line) if not sub_match else None

        new_qnum: str | None = None
        new_top_level: int | None = None
        same_line_tail: str = ""

        if sub_match:
            new_top_level = int(sub_match.group(1))
            new_qnum = _normalize_sub_qnum(sub_match.group(1), sub_match.group(2))
            same_line_tail = sub_match.group(3) or ""
        elif alone_match:
            n = int(alone_match.group(1))
            if n == current_top_level + 1:
                new_top_level = n
                new_qnum = str(n)

        if new_qnum is not None:
            if current_qnum is not None:
                blocks.append((current_qnum, current_lines))
            current_qnum = new_qnum
            current_lines = []
            if same_line_tail.strip():
                current_lines.append(same_line_tail.strip())
            current_top_level = max(current_top_level, new_top_level or 0)
            continue

        if current_qnum is None:
            continue
        if line.strip():
            current_lines.append(line.strip())

    if current_qnum is not None:
        blocks.append((current_qnum, current_lines))

    return blocks


def _normalize_sub_qnum(num: str, parens: str) -> str:
    """
    Convert "13", "(b)(ii)(a)" → "13b(ii)(a)".
    The first sub-level letter is appended bare; subsequent levels keep parens.
    """
    out = num
    parts = re.findall(r"\(([a-z]+|[ivx]+)\)", parens)
    if not parts:
        return out
    out += parts[0]
    for p in parts[1:]:
        out += f"({p})"
    return out


def _analyze_block(block_lines: list[str]) -> tuple[str, int, str]:
    """
    Given the body lines of one question block, extract:
        (answer_text, total_marks, partial_marks_text)

    Strategy: find the first line that begins with a partial-mark token
    (B1/M1/A1/FT/SC/cao/nfww), optionally preceded by an integer which
    is the total marks. Lines before it are the answer; that line plus
    everything after is the partial-marks breakdown.

    If no marker line exists (simple 1-mark questions), the last bare-
    digit line is the total marks count.
    """
    if not block_lines:
        return "", 0, ""

    marker_idx: int | None = None
    leading_int: int | None = None

    for i, line in enumerate(block_lines):
        m = _MARKER_LINE_RE.match(line)
        if m:
            marker_idx = i
            if m.group(1):
                leading_int = int(m.group(1))
            break

    if marker_idx is not None:
        if leading_int is not None:
            total_marks = leading_int
            line0_no_int = re.sub(r"^\s*\d{1,2}\s+", "", block_lines[marker_idx], count=1)
            answer_lines = block_lines[:marker_idx]
            partial_lines = [line0_no_int] + block_lines[marker_idx + 1:]
        else:
            # Total marks is the nearest preceding bare-digit line.
            total_marks = 0
            answer_end = marker_idx
            for j in range(marker_idx - 1, -1, -1):
                dm = _DIGIT_ALONE_RE.match(block_lines[j])
                if dm:
                    total_marks = int(dm.group(1))
                    answer_end = j
                    break
            answer_lines = block_lines[:answer_end]
            partial_lines = block_lines[marker_idx:]
    else:
        # No marker: use last bare-digit line as total marks.
        total_marks = 0
        answer_end = len(block_lines)
        for j in range(len(block_lines) - 1, -1, -1):
            dm = _DIGIT_ALONE_RE.match(block_lines[j])
            if dm:
                total_marks = int(dm.group(1))
                answer_end = j
                break
        answer_lines = block_lines[:answer_end]
        partial_lines = []

    # Sanity cap: no IGCSE question part is ever worth more than 20 marks.
    # Values above this are page numbers or other PDF artifacts, not mark counts.
    if total_marks > 20:
        total_marks = 0

    answer_text = _collapse_ws("\n".join(answer_lines))
    partial_text = "\n".join(ln for ln in partial_lines if ln.strip()).strip()
    return answer_text, total_marks, partial_text


def _build_mark_points(answer_text: str, partial_text: str, total_marks: int) -> list[str]:
    """
    Convert the partial-marks text into a list of individual mark-point strings.
    If there is no partial breakdown, wraps the answer text as a single point.
    """
    if not partial_text and answer_text:
        m = total_marks if total_marks > 0 else 1
        return [f"Answer: {answer_text} [{m} mark{'s' if m != 1 else ''}]"]

    if not partial_text:
        return []

    flat = re.sub(r"\s+", " ", partial_text).strip()
    matches = list(_MARK_POINT_START_RE.finditer(flat))
    if not matches:
        return [flat] if flat else []

    points: list[str] = []
    lead_in = flat[:matches[0].start()].strip()
    for i, m in enumerate(matches):
        pt_start = m.start()
        pt_end = matches[i + 1].start() if i + 1 < len(matches) else len(flat)
        chunk = flat[pt_start:pt_end].strip()
        if not chunk:
            continue
        chunk = re.sub(r"^(?:or|OR|and)\s+", "", chunk)
        if i == 0 and lead_in:
            chunk = f"{lead_in} {chunk}".strip()
        points.append(chunk)

    return points


def _collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _dedupe_entries(entries: list[dict]) -> list[dict]:
    """When a question number appears twice, keep the entry with more mark points."""
    by_qnum: dict[str, dict] = {}
    for e in entries:
        existing = by_qnum.get(e["question_number"])
        if existing is None or len(e["mark_points"]) > len(existing["mark_points"]):
            by_qnum[e["question_number"]] = e
    seen: set[str] = set()
    out: list[dict] = []
    for e in entries:
        q = e["question_number"]
        if q in seen:
            continue
        seen.add(q)
        out.append(by_qnum[q])
    return out


# ---------------------------------------------------------------------------
# 4. Diagnostic preview
# ---------------------------------------------------------------------------

def print_parsing_preview(questions: list[dict], markscheme: list[dict]) -> None:
    """
    Print a structured summary of parsed data to the terminal.

    Outputs:
      - Total questions and mark scheme entries parsed
      - Per-question: number, marks, first 80 chars of question text
      - Per-mark scheme entry: number, total marks, mark point count
      - Any question_numbers present in one list but missing from the other
    """
    q_nums = {q["question_number"] for q in questions}
    ms_nums = {m["question_number"] for m in markscheme}

    print()
    print("=" * 60)
    print("  PARSING PREVIEW")
    print("=" * 60)
    print(f"  Questions parsed from solved paper : {len(questions)}")
    print(f"  Mark scheme entries parsed         : {len(markscheme)}")
    print()

    if questions:
        print("  QUESTIONS:")
        for q in questions:
            preview = q["question_text"][:80].replace("\n", " ")
            print(f"    Q{q['question_number']:6s}  [{q['marks_available']}m]  {preview}")
    else:
        print("  QUESTIONS: (none — solved paper is image-only or unparseable)")

    print()
    print("  MARK SCHEME ENTRIES:")
    for m in markscheme:
        print(
            f"    Q{m['question_number']:6s}  [{m['total_marks']}m]  "
            f"{len(m['mark_points'])} mark point(s)"
        )

    in_q_not_ms = sorted(q_nums - ms_nums)
    in_ms_not_q = sorted(ms_nums - q_nums)

    if in_q_not_ms:
        print()
        print("  MISMATCH — in solved paper but NOT in mark scheme:")
        for n in in_q_not_ms:
            print(f"    {n}")

    if in_ms_not_q:
        print()
        print("  MISMATCH — in mark scheme but NOT in solved paper:")
        for n in in_ms_not_q:
            print(f"    {n}")

    if not in_q_not_ms and not in_ms_not_q and questions:
        print()
        print("  No mismatches — every question has a matching mark scheme entry.")

    print("=" * 60)
    print()
