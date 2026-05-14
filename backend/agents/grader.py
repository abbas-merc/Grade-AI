"""
grader.py — Agent 3 of 4

Responsibility:
  Takes the transcribed student work (from vision_extractor) and the parsed
  mark scheme criteria (from markscheme_parser) and decides which marks the
  student has earned.  Returns a numeric score and a per-criterion breakdown.

Why a separate agent:
  Grading requires careful logical reasoning against specific criteria.
  Isolating this step means we can prompt-engineer it independently of
  vision or feedback concerns, and test it with synthetic transcripts.
"""

import anthropic
import json
import os


def grade_student_work(
    student_transcript: str,
    parsed_criteria: list[dict],
    question_text: str,
    max_marks: int,
) -> dict:
    """
    Grade a student's work against the parsed mark scheme.

    Args:
        student_transcript: Plain-text transcript from vision_extractor.
        parsed_criteria:    List of criterion dicts from markscheme_parser.
        question_text:      The original question wording (for context).
        max_marks:          Maximum marks available for this question.

    Returns:
        {
          "marks_awarded": 3,
          "max_marks": 4,
          "breakdown": [
            {
              "criterion": "...",
              "awarded": true,
              "reason": "Student clearly showed..."
            },
            ...
          ]
        }
    """
    client = anthropic.Anthropic(
        api_key=(os.getenv("ANTHROPIC_API_KEY") or "").strip(),
        max_retries=5,
        timeout=60.0,
    )

    criteria_json = json.dumps(parsed_criteria, indent=2)

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        temperature=0,
        messages=[
            {
                "role": "user",
                "content": (
                    "You are a strict but fair Cambridge IGCSE examiner. "
                    "Grade the student's work below against each criterion in the mark scheme. "
                    "Be precise: award a mark only if the student's work clearly satisfies the criterion. "
                    "Return ONLY valid JSON — no markdown, no explanation.\n\n"
                    f"QUESTION:\n{question_text}\n\n"
                    f"MARK SCHEME CRITERIA (JSON):\n{criteria_json}\n\n"
                    f"STUDENT'S WORK:\n{student_transcript}\n\n"
                    "Return JSON in this exact shape:\n"
                    "{\n"
                    '  "marks_awarded": <integer>,\n'
                    '  "max_marks": ' + str(max_marks) + ",\n"
                    '  "breakdown": [\n'
                    "    {\n"
                    '      "criterion": "<criterion text>",\n'
                    '      "awarded": <true|false>,\n'
                    '      "reason": "<one sentence explanation>"\n'
                    "    }\n"
                    "  ]\n"
                    "}"
                ),
            }
        ],
    )

    raw_response = message.content[0].text.strip()

    if raw_response.startswith("```"):
        raw_response = raw_response.split("```")[1]
        if raw_response.startswith("json"):
            raw_response = raw_response[4:]

    return json.loads(raw_response)
