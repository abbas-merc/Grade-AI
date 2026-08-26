"""
tag_subparts.py — Part 3: automated part-level syllabus tagging.

For every sub-part in scripts/part_extraction/part_manifest.json, ask Claude to
assign the correct IGCSE 0580 syllabus code(s) from scripts/syllabus_codes.json,
using the MARK SCHEME method statements as the strongest signal (Part 3.1), plus
a confidence level (high/medium/low, Part 3.2) and a short reason.

Design:
  * Codes are constrained to the taxonomy — the tool schema + a post-validation
    step reject anything not in syllabus_codes.json (never invent a code).
  * One API call per QUESTION (all its sub-parts together, so the model sees the
    shared context). Structured output via tool-use so parsing can't drift.
  * Resumable + concurrent: results stream to part_tags.json keyed by partId;
    a re-run skips questions already tagged. Token usage is logged for cost.

Run from backend/:
  python scripts/tag_subparts.py --paper 058042_s24     # one paper (proof)
  python scripts/tag_subparts.py                         # whole bank (resumable)
  python scripts/tag_subparts.py --limit 20              # first N questions
"""
from __future__ import annotations

import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
load_dotenv(os.path.join(BACKEND, ".env"))

PART_MANIFEST = os.path.join(HERE, "part_extraction", "part_manifest.json")
SYLLABUS = os.path.join(HERE, "syllabus_codes.json")
OUT = os.path.join(HERE, "part_extraction", "part_tags.json")

MODEL = "claude-sonnet-4-6"
MAX_WORKERS = 6

_lock = threading.Lock()
_usage = {"in": 0, "out": 0, "calls": 0}


def load_taxonomy():
    data = json.load(open(SYLLABUS, encoding="utf-8"))
    valid = set()
    lines = []
    for sec in data["sections"]:
        lines.append(f"\n## Section {sec['number']} — {sec['name']}")
        for sub in sec["subsections"]:
            code = sub["extended_code"]
            valid.add(code)
            hint = (sub.get("content", "") or "").replace("\n", " ")
            # keep a short mapping hint (the objective line), not the whole block
            hint = hint[:120]
            tier = " [Extended only]" if sub["extended_only"] else ""
            lines.append(f"  {code}  {sub['name']}{tier} — {hint}")
    return "\n".join(lines), valid


TAXONOMY_TEXT, VALID_CODES = load_taxonomy()

SYSTEM = (
    "You are an expert Cambridge IGCSE Mathematics (0580) examiner classifying "
    "each sub-part of an exam question against the official syllabus taxonomy.\n\n"
    "Rules:\n"
    "1. Use ONLY codes from the taxonomy below. Never invent a code.\n"
    "2. The MARK SCHEME method statements are your STRONGEST signal for the skill "
    "being tested (e.g. 'use of sine rule' -> E6.5; 'factorise' -> E2.2; "
    "'P(A and B)' with a tree -> E8.3). Use the question text as secondary context.\n"
    "3. Assign the most SPECIFIC code(s). A sub-part usually has exactly one code; "
    "assign two or more only when it genuinely spans topics.\n"
    "4. Confidence: 'high' when the mark scheme language maps directly to a code; "
    "'medium' when you inferred it from context; 'low' when genuinely ambiguous.\n"
    "5. Prefer the Extended (E) codes — these are Extended-tier papers.\n\n"
    "TAXONOMY (code — name — objective hint):\n" + TAXONOMY_TEXT
)

TOOL = [{
    "name": "assign_codes",
    "description": "Return the syllabus code assignment for every sub-part provided.",
    "input_schema": {
        "type": "object",
        "properties": {
            "assignments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "partLabel": {"type": "string", "description": "the sub-part label exactly as given, e.g. '(a)' or '(b)(ii)' or '(whole)'"},
                        "codes": {"type": "array", "items": {"type": "string"}, "description": "1+ syllabus codes from the taxonomy"},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                        "reason": {"type": "string", "description": "one short sentence: which mark-scheme phrase drove the choice"},
                    },
                    "required": ["partLabel", "codes", "confidence", "reason"],
                },
            }
        },
        "required": ["assignments"],
    },
}]


def _part_label(sp):
    return sp["label"] if sp["label"] else "(whole)"


def build_user_prompt(rec):
    ms_by = rec.get("markSchemeByPart", {})
    blocks = [f"Question {rec['id']} (paper {rec['paperType']}, {rec.get('bankMarks','?')} marks total). "
              f"Classify each sub-part below.\n"]
    for sp in rec["subParts"]:
        key = "".join(sp["path"]) if sp["path"] != ["_"] else "_"
        ms = ms_by.get(key, "") or ms_by.get("".join(sp["path"]), "")
        qt = (sp.get("questionText", "") or "")[:600]
        blocks.append(
            f"--- Sub-part {_part_label(sp)}  ({sp['marks']} marks) ---\n"
            f"QUESTION TEXT:\n{qt.strip() or '[image-only / diagram]'}\n"
            f"MARK SCHEME:\n{ms.strip() or '[none]'}\n"
        )
    return "\n".join(blocks)


def tag_question(client, rec, valid):
    prompt = build_user_prompt(rec)
    resp = client.messages.create(
        model=MODEL, max_tokens=1024,
        # The taxonomy system prompt is identical on every call — cache it so
        # only the per-question text is billed at full input rate.
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        tools=TOOL, tool_choice={"type": "tool", "name": "assign_codes"},
        messages=[{"role": "user", "content": prompt}],
    )
    with _lock:
        _usage["in"] += resp.usage.input_tokens
        _usage["out"] += resp.usage.output_tokens
        _usage["cache_read"] = _usage.get("cache_read", 0) + getattr(resp.usage, "cache_read_input_tokens", 0)
        _usage["cache_write"] = _usage.get("cache_write", 0) + getattr(resp.usage, "cache_creation_input_tokens", 0)
        _usage["calls"] += 1
    assignments = []
    for block in resp.content:
        if block.type == "tool_use":
            assignments = block.input.get("assignments", [])
            break
    # map assignments back to parts by label
    by_label = { (a.get("partLabel") or "").strip(): a for a in assignments }
    out = {}
    for sp in rec["subParts"]:
        lbl = _part_label(sp)
        a = by_label.get(lbl) or by_label.get(sp["label"]) or {}
        codes = [c for c in (a.get("codes") or []) if c in valid]
        invalid = [c for c in (a.get("codes") or []) if c not in valid]
        part_id = rec["id"] + "_" + "_".join(sp["path"])
        out[part_id] = {
            "questionId": rec["id"],
            "label": sp["label"],
            "path": sp["path"],
            "marks": sp["marks"],
            "syllabusCodes": codes,
            "codeConfidence": a.get("confidence", "low") if codes else "low",
            "codeReason": a.get("reason", ""),
            "invalidCodesDropped": invalid,
            "untagged": not codes,
        }
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    only = None
    limit = None
    if "--paper" in sys.argv:
        only = sys.argv[sys.argv.index("--paper") + 1]
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    manifest = json.load(open(PART_MANIFEST, encoding="utf-8"))
    if only:
        manifest = [r for r in manifest if r["code"] == only]
    if limit:
        manifest = manifest[:limit]

    existing = {}
    if os.path.exists(OUT):
        existing = json.load(open(OUT, encoding="utf-8"))
    done_qids = {v["questionId"] for v in existing.values()}
    todo = [r for r in manifest if r["id"] not in done_qids]
    print(f"tagging {len(todo)} questions ({len(manifest)-len(todo)} already done)")

    key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        raise SystemExit("ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=key, max_retries=5, timeout=90.0)

    results = dict(existing)
    errors = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(tag_question, client, r, VALID_CODES): r for r in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            r = futs[fut]
            try:
                part_map = fut.result()
                with _lock:
                    results.update(part_map)
                    if i % 20 == 0 or i == len(todo):
                        json.dump(results, open(OUT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
                        print(f"  {i}/{len(todo)}  (saved {len(results)} sub-parts)")
            except Exception as e:
                errors.append((r["id"], str(e)))
                print(f"  ERROR {r['id']}: {e}")

    json.dump(results, open(OUT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    # cost (sonnet-4-6 pricing: $3/Mtok in, $15/Mtok out)
    cost = _usage["in"] / 1e6 * 3 + _usage["out"] / 1e6 * 15
    conf = {"high": 0, "medium": 0, "low": 0}
    untagged = 0
    for v in results.values():
        conf[v["codeConfidence"]] = conf.get(v["codeConfidence"], 0) + 1
        untagged += bool(v.get("untagged"))
    print(f"\nDONE. sub-parts tagged: {len(results)}   errors: {len(errors)}")
    print(f"confidence: {conf}   untagged: {untagged}")
    print(f"API: {_usage['calls']} calls, {_usage['in']} in + {_usage['out']} out tokens, ~${cost:.2f}")
    print(f"-> {os.path.relpath(OUT)}")


if __name__ == "__main__":
    main()
