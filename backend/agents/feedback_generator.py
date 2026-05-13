"""
feedback_generator.py — Student-facing feedback agent (call 2 of 2).

Responsibility:
    Take the grading result from vision_extractor.extract_and_grade and
    produce short, encouraging, jargon-free feedback for an IGCSE student
    aged 14-17. This is text-only (no image) to keep cost minimal.

    Tone is independent of grading logic, so this lives in its own agent
    and can be tuned without touching grading accuracy.
"""

from __future__ import annotations

import json
import os
from typing import Any

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 300
EXTRACTED_TEXT_LIMIT = 300


def _safe_fallback(reason: str, output_tokens: int = 0) -> dict[str, Any]:
    """Fallback dict when the API call or response handling fails."""
    return {
        "feedback": (
            "We couldn't generate detailed feedback this time, but your "
            "marks and mark-by-mark breakdown above are still accurate. "
            "Review each point you missed and try the question again."
        ),
        "output_tokens": output_tokens,
        "error": reason,
    }


def generate_feedback(
    question_text: str,
    extracted_text: str,
    marks_awarded: int,
    marks_available: int,
    mark_breakdown: list[dict],
) -> dict:
    """
    Generate one short, encouraging feedback paragraph for a student.

    Args:
        question_text:    The original question wording.
        extracted_text:   The student's transcribed work (truncated to
                          EXTRACTED_TEXT_LIMIT chars before sending).
        marks_awarded:    Marks the student earned.
        marks_available:  Total marks the question is worth.
        mark_breakdown:   The list of {point_number, criterion, awarded,
                          reason} dicts from extract_and_grade.

    Returns:
        {
            "feedback":      str,   # one short paragraph for the student
            "output_tokens": int,
        }

        On API or parsing failure, returns a safe fallback dict with the
        same shape and an "error" key. Never raises.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return _safe_fallback("ANTHROPIC_API_KEY not set")

    truncated_work = (extracted_text or "")[:EXTRACTED_TEXT_LIMIT]
    breakdown_json = json.dumps(mark_breakdown, indent=2)

    system_prompt = (
        "You are a warm, encouraging IGCSE maths tutor giving feedback "
        "to a student aged 14-17. Be specific, motivating, and concise. "
        "No jargon, no markdown headings, no lists — just a single short "
        "paragraph (3-5 sentences) the student can read in 15 seconds."
    )

    user_prompt = (
        f"Question: {question_text}\n\n"
        f"Student's work (transcribed): {truncated_work}\n\n"
        f"Score: {marks_awarded} / {marks_available}\n\n"
        f"Mark-by-mark breakdown:\n{breakdown_json}\n\n"
        "Write the feedback paragraph now. Mention one thing they did "
        "well (if any), the most important thing to fix next time, and "
        "end on an encouraging note. Plain text only."
    )

    client = anthropic.Anthropic(api_key=api_key)

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as exc:
        return _safe_fallback(f"Anthropic API error: {exc}")

    output_tokens = getattr(message.usage, "output_tokens", 0) or 0

    try:
        feedback_text = message.content[0].text.strip()
    except (IndexError, AttributeError) as exc:
        return _safe_fallback(f"empty response: {exc}", output_tokens)

    if not feedback_text:
        return _safe_fallback("empty feedback text", output_tokens)

    return {
        "feedback": feedback_text,
        "output_tokens": output_tokens,
    }
