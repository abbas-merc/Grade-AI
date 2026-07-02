"""
_feedback_samples.py — Show 5 sample feedback outputs produced by the NEW
feedback instructions (Part 8), so the tone can be judged before sign-off.

It reuses the exact maths examiner system prompt and the new FEEDBACK guidance
block from the grading pipeline, and asks the same model the pipeline uses to
produce feedback for 5 representative student scenarios (text-only, cheap).

Run:  venv/Scripts/python.exe scripts/_feedback_samples.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The Windows console defaults to cp1252, which can't encode arrows/maths glyphs
# in model output; force UTF-8 so sample feedback prints verbatim.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import anthropic  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from prompts import get_maths_prompt  # noqa: E402
from pipeline import MODEL  # noqa: E402

load_dotenv()

SYSTEM, _ = get_maths_prompt()

# The exact FEEDBACK guidance now embedded in run_full_paper_grading.
FEEDBACK_RULES = (
    "Write the feedback as an experienced subject teacher marking the script by "
    "hand, NOT as a chatbot or customer-service assistant:\n"
    "- Be specific to what THIS student actually did in their working — refer to "
    "their real method and values. Never generic praise or generic criticism.\n"
    "- When marks are lost, name the specific error type, e.g. 'correct method "
    "but an arithmetic slip expanding the bracket in line 2', 'right formula, "
    "wrong rearrangement', or 'units missing from the final answer' — never a "
    "vague phrase like 'partially correct'.\n"
    "- Keep it to 1-3 short sentences. Direct and plain: no filler, no "
    "exclamation-mark cheerleading, no 'great job!' padding.\n"
    "- When full marks are earned, still be substantive if there is something "
    "worth noting (an efficient or elegant method); otherwise a short honest line "
    "is fine. Do not manufacture praise.\n"
    "- If the answer could not be read, say so plainly and ask for a clearer photo."
)

SCENARIOS = [
    {
        "title": "Full marks, elegant method",
        "question": "Solve 3(2x - 4) = 18.",
        "mark_scheme": "2x - 4 = 6 (M1) oe; x = 5 (A1)",
        "working": "3(2x-4)=18  ->  divided both sides by 3 first: 2x-4=6, 2x=10, x=5",
        "marks": "2 / 2",
    },
    {
        "title": "Right method, arithmetic slip",
        "question": "Expand and simplify (x + 3)(x - 5).",
        "mark_scheme": "x^2 - 5x + 3x - 15 (M1) for correct expansion; x^2 - 2x - 15 (A1)",
        "working": "(x+3)(x-5) = x^2 -5x +3x -15 = x^2 -2x -20",
        "marks": "1 / 2",
    },
    {
        "title": "Wrong approach entirely",
        "question": "Find the gradient of the line joining (1, 2) and (4, 11).",
        "mark_scheme": "(11 - 2)/(4 - 1) (M1); 3 (A1)",
        "working": "gradient = 4 - 1 = 3 ... used the x values only",
        "marks": "0 / 2",
    },
    {
        "title": "Correct value, units/accuracy issue",
        "question": "A car travels 150 km in 2.5 hours. Find its average speed.",
        "mark_scheme": "150 / 2.5 (M1); 60 km/h (A1, unit required)",
        "working": "150 / 2.5 = 60",
        "marks": "1 / 2",
    },
    {
        "title": "Answer unreadable / illegible",
        "question": "Work out 17% of 250.",
        "mark_scheme": "0.17 x 250 (M1); 42.5 (A1)",
        "working": "0.17 x 250 = [illegible] (final number can't be read)",
        "marks": "1 / 2",
    },
]


def main() -> None:
    key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        print("ANTHROPIC_API_KEY not set — cannot generate live samples.")
        return
    client = anthropic.Anthropic(api_key=key, max_retries=3, timeout=60.0)

    print(f"Model: {MODEL}\n" + "=" * 72)
    for i, s in enumerate(SCENARIOS, 1):
        user = (
            f"Question: {s['question']}\n"
            f"Mark scheme: {s['mark_scheme']}\n"
            f"Student's transcribed working: {s['working']}\n"
            f"Marks awarded: {s['marks']}\n\n"
            f"{FEEDBACK_RULES}\n\n"
            "Return ONLY the feedback text (1-3 sentences), nothing else."
        )
        msg = client.messages.create(
            model=MODEL,
            max_tokens=160,
            temperature=0,
            system=SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        fb = msg.content[0].text.strip()
        print(f"\n[{i}] {s['title']}  ({s['marks']})")
        print(f"    Q: {s['question']}")
        print(f"    Student: {s['working']}")
        print(f"    -> FEEDBACK: {fb}")
    print("\n" + "=" * 72)


if __name__ == "__main__":
    main()
