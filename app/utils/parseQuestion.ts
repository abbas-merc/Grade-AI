/**
 * utils/parseQuestion.ts — Split a question's text into an intro and its
 * lettered/roman sub-parts, pulling each part's mark allocation.
 *
 * The PDF-extracted `questionText` puts each sub-part on its own line, e.g.
 *
 *   A bag contains 5 red balls...
 *   (a) Find the probability...        [3]
 *   (b) Calculate the expected...      [4]
 *
 * We anchor sub-part markers to the start of a line so we don't mistake
 * bracketed tokens inside an expression (e.g. "(x)") for a part. Per-part marks
 * are read from a trailing "[3]" / "[3 marks]" token and stripped from the
 * displayed text. This is a heuristic — messy maths extraction can still defeat
 * it — so callers should treat `marks: null` as "unknown", not zero.
 */

export interface ParsedPart {
  /** The marker letter/numeral, e.g. "a", "b", "i". */
  label: string;
  /** Part body with the trailing marks token removed. */
  text: string;
  /** Marks for this part, or null if none could be parsed. */
  marks: number | null;
}

export interface ParsedQuestion {
  /** Text before the first sub-part (the whole question when there are none). */
  intro: string;
  parts: ParsedPart[];
}

// A trailing "[3]" or "[3 marks]" anywhere in a segment; we take the last one.
const MARKS_RE = /\[(\d+)\s*(?:marks?)?\]/gi;
// A sub-part marker at the start of a line: "(a)".."(zzzz)" / roman numerals.
const MARKER_RE = /(^|\n)[ \t]*\(([a-z]{1,4})\)/g;

function extractMarks(segment: string): { text: string; marks: number | null } {
  let last: RegExpExecArray | null = null;
  let match: RegExpExecArray | null;
  MARKS_RE.lastIndex = 0;
  while ((match = MARKS_RE.exec(segment)) !== null) last = match;

  if (!last) return { text: segment.trim(), marks: null };
  const start = last.index;
  const end = start + last[0].length;
  const text = (segment.slice(0, start) + segment.slice(end)).trim();
  return { text, marks: parseInt(last[1], 10) };
}

export function parseQuestionParts(questionText: string): ParsedQuestion {
  const text = (questionText ?? "").replace(/\r/g, "");

  // Locate every sub-part marker, recording where its "(" sits and where its
  // body begins (just after the ")").
  const markers: { markerStart: number; contentStart: number; label: string }[] = [];
  let m: RegExpExecArray | null;
  MARKER_RE.lastIndex = 0;
  while ((m = MARKER_RE.exec(text)) !== null) {
    const label = m[2];
    const markerStart = m.index + m[0].length - (label.length + 2); // index of "("
    markers.push({ markerStart, contentStart: m.index + m[0].length, label });
  }

  if (markers.length === 0) {
    return { intro: text.trim(), parts: [] };
  }

  const intro = text.slice(0, markers[0].markerStart).trim();
  const parts: ParsedPart[] = markers.map((mk, i) => {
    const segEnd = i + 1 < markers.length ? markers[i + 1].markerStart : text.length;
    const segment = text.slice(mk.contentStart, segEnd);
    const { text: partText, marks } = extractMarks(segment);
    return { label: mk.label, text: partText, marks };
  });

  return { intro, parts };
}
