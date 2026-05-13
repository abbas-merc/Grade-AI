"""
markscheme_parser.py — Agent 2 of 4

Responsibility:
  Takes the raw text of an official IGCSE mark scheme and parses it into a
  structured JSON list of mark-awarding criteria.  This structured form is
  what the grader agent uses to decide which marks the student has earned.

Why a separate agent:
  Mark schemes use dense, abbreviated Cambridge notation.  Parsing them once
  and caching the result (stored in mark_schemes.parsed_json) means the
  grader always receives clean, consistent criteria regardless of the
  original formatting.
"""

import anthropic
import json
import os


def parse_mark_scheme(raw_mark_scheme: str) -> list[dict]:
    """
    Parse a raw IGCSE mark scheme into structured criteria.

    Args:
        raw_mark_scheme: The official mark scheme text verbatim.

    Returns:
        A list of dicts, each representing one mark-awarding point:
        [
          {
            "criterion": "Correct expansion: x^2 + 5x + 6",
            "marks": 1,
            "allow": ["accept equivalent forms"],
            "reject": ["wrong signs"]
          },
          ...
        ]
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": (
                    "You are an expert Cambridge IGCSE examiner. "
                    "Parse the following mark scheme into a JSON array. "
                    "Each element must have keys: "
                    "  'criterion' (string – what the student must show), "
                    "  'marks' (integer – marks awarded for this point), "
                    "  'allow' (list of strings – acceptable alternatives), "
                    "  'reject' (list of strings – common errors that do NOT earn the mark). "
                    "Return ONLY valid JSON — no markdown, no explanation.\n\n"
                    f"MARK SCHEME:\n{raw_mark_scheme}"
                ),
            }
        ],
    )

    raw_response = message.content[0].text.strip()

    # Strip markdown code fences if the model wrapped the JSON
    if raw_response.startswith("```"):
        raw_response = raw_response.split("```")[1]
        if raw_response.startswith("json"):
            raw_response = raw_response[4:]

    return json.loads(raw_response)
