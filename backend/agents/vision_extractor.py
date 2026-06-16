"""
vision_extractor.py — Combined vision + grading agent (1 of 2 calls).

Responsibility:
    Take a student's handwritten answer (base64-encoded image) plus the
    question text and mark scheme, and in a SINGLE Anthropic API call:
      1. Transcribe what the student wrote.
      2. Grade it against the mark scheme using Cambridge conventions
         (M / A / B marks, ft, cao, oe).

    Combining vision + grading into one call halves API cost vs. two
    separate calls and preserves full context (image + transcript) when
    making award decisions.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import anthropic
from dotenv import load_dotenv

from agents.image_preprocess import enhance_image_base64

load_dotenv()

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 800


def _strip_data_uri(image_base64: str) -> str:
    """Remove a data: URI prefix from a base64 string if present."""
    if "base64," in image_base64:
        return image_base64.split("base64,", 1)[1]
    return image_base64


def _detect_media_type(image_base64: str) -> str:
    """Detect media type from a data URI; default to image/jpeg."""
    match = re.match(r"data:(image/[a-zA-Z0-9.+-]+);base64,", image_base64)
    if match:
        return match.group(1)
    return "image/jpeg"


def _safe_fallback(reason: str) -> dict[str, Any]:
    """Return a never-crash fallback dict when the API or JSON parse fails."""
    return {
        "extracted_text": "",
        "marks_awarded": 0,
        "mark_breakdown": [],
        "input_tokens": 0,
        "output_tokens": 0,
        "error": reason,
    }


def _extract_json(raw: str) -> dict[str, Any]:
    """Pull a JSON object out of model output that may be wrapped in fences."""
    text = raw.strip()
    if text.startswith("```"):
        # Strip ```json / ``` fences
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # Find the first '{' and last '}' in case there is preamble/trailing text
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and last > first:
        text = text[first : last + 1]
    return json.loads(text)


def extract_and_grade(
    image_base64: str,
    question_text: str,
    marks_available: int,
    mark_scheme_points: list[dict],
) -> dict:
    """
    Single-call vision extraction + grading against a mark scheme.

    Args:
        image_base64:        Base64-encoded student answer image. Any
                             "data:image/...;base64," prefix is stripped.
        question_text:       The full question wording.
        marks_available:     Total marks the question is worth.
        mark_scheme_points:  List of dicts describing each mark scheme
                             criterion. Each dict should carry at minimum
                             a description; keys like point_number,
                             marks_for_point, mark_type, acceptable
                             alternatives are forwarded if present.

    Returns:
        {
            "extracted_text": str,        # what the student wrote
            "marks_awarded":  int,        # total marks awarded (0..marks_available)
            "mark_breakdown": list[dict], # per-point: point_number, criterion,
                                          # awarded (bool), reason (str)
            "input_tokens":   int,
            "output_tokens":  int,
        }

        On API error or JSON parse failure, returns a safe fallback dict
        with the same shape, marks_awarded=0, empty breakdown, and an
        "error" key explaining what went wrong. Never raises.
    """
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        return _safe_fallback("ANTHROPIC_API_KEY not set")

    # Enhance the image for handwriting legibility before sending it to the
    # model. enhance_image_base64 always returns high-quality JPEG bytes.
    clean_b64 = enhance_image_base64(_strip_data_uri(image_base64))
    media_type = "image/jpeg"

    scheme_json = json.dumps(mark_scheme_points, indent=2)

    system_prompt = (
        "You are an expert IGCSE Cambridge mathematics examiner. "
        "Follow Cambridge mark scheme conventions strictly. "
        "M marks are for method — award if correct method is shown even if the final answer is wrong. "
        "A marks are for accuracy — only award an A mark if the corresponding M mark was also awarded. "
        "B marks are independent — award regardless of method. "
        "ft means follow through — award if the student correctly followed through from an earlier wrong answer. "
        "cao means correct answer only — do not award for follow through answers. "
        "oe means or equivalent — accept any mathematically equivalent form. "
        "You will (1) transcribe the student's handwritten work exactly, "
        "preserving algebra/fractions/indices, then (2) grade it strictly "
        "point-by-point against the mark scheme provided. "
        "If you cannot read the student's handwriting for a question with "
        "high confidence, do not attempt to interpret it. Instead set the "
        "awarded marks to 0 for that question and set the feedback to say "
        "'handwriting unclear, please resubmit this page'. Never award or "
        "deduct marks based on a guess. "
        "You must only evaluate what is physically written on the paper. "
        "Do not infer, assume, or construct an answer. If the student wrote "
        "'anti-clockwise', mark that as the answer. Do not replace it with "
        "your own interpretation of what the answer should be."
    )

    user_text = (
        f"QUESTION ({marks_available} marks):\n{question_text}\n\n"
        f"MARK SCHEME (each item is one award point):\n{scheme_json}\n\n"
        "You must base your marking decision entirely on what the student has "
        "written. Do not perform independent verification of the answer. Do not "
        "recalculate. If you calculated something yourself and it differs from "
        "what the student wrote, ignore your calculation entirely and mark only "
        "what the student wrote against the mark scheme criteria. "
        "If you are unsure whether an answer satisfies a criterion, award the "
        "mark. Uncertainty defaults to awarding, not withholding.\n\n"
        "The image contains handwritten student answers. Handwriting quality "
        "may vary significantly between students. Some handwriting may be messy, "
        "rushed, or unconventional. Read every written character as carefully as "
        "possible. If a word or number is genuinely impossible to interpret "
        "after careful analysis, write the token [illegible] in place of that "
        "word. Do not skip any written content and do not guess randomly. Apply "
        "extra attention to numbers, units, and technical scientific terms as "
        "these are the most critical parts of student answers.\n\n"
        "Transcribe the image first, then decide for EACH mark scheme point "
        "whether the student earned it. Return ONLY valid JSON, no markdown, "
        "in exactly this shape:\n"
        "{\n"
        '  "extracted_text": "<faithful transcript of student work>",\n'
        '  "marks_awarded": <integer total, 0..' + str(marks_available) + ">,\n"
        '  "mark_breakdown": [\n'
        "    {\n"
        '      "point_number": <int, 1-indexed>,\n'
        '      "criterion": "<short description of what was being marked>",\n'
        '      "awarded": <true|false>,\n'
        '      "reason": "<one-sentence justification>"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "Do not include any text before or after the JSON."
    )

    # max_retries=5 absorbs transient 5xx / 429 errors with backoff.
    client = anthropic.Anthropic(api_key=api_key, max_retries=5, timeout=90.0)

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            temperature=0,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": clean_b64,
                            },
                        },
                        {"type": "text", "text": user_text},
                    ],
                }
            ],
        )
    except Exception as exc:
        return _safe_fallback(f"Anthropic API error: {exc}")

    input_tokens = getattr(message.usage, "input_tokens", 0) or 0
    output_tokens = getattr(message.usage, "output_tokens", 0) or 0

    try:
        raw_text = message.content[0].text
        parsed = _extract_json(raw_text)
    except (json.JSONDecodeError, IndexError, AttributeError, KeyError) as exc:
        fallback = _safe_fallback(f"JSON parse failure: {exc}")
        fallback["input_tokens"] = input_tokens
        fallback["output_tokens"] = output_tokens
        return fallback

    # Clamp marks_awarded to a sane range and coerce to int
    try:
        marks_awarded = int(parsed.get("marks_awarded", 0))
    except (TypeError, ValueError):
        marks_awarded = 0
    marks_awarded = max(0, min(marks_awarded, marks_available))

    breakdown_raw = parsed.get("mark_breakdown", [])
    if not isinstance(breakdown_raw, list):
        breakdown_raw = []

    return {
        "extracted_text": str(parsed.get("extracted_text", "")),
        "marks_awarded": marks_awarded,
        "mark_breakdown": breakdown_raw,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
