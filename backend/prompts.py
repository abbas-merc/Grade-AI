"""
prompts.py — Subject-specific examiner prompts for GradeAI grading.

Each function returns a 2-tuple:

    (system_prompt: str, marking_instructions: str)

`system_prompt`        — the persona/system message handed to the Claude API as
                         the `system` parameter.
`marking_instructions` — the subject-specific marking conventions that are
                         appended into the user instructions block, telling the
                         model exactly how to award marks for that subject and
                         paper type.

Routing (subject_code, paper_number) -> prompt is done in pipeline.py:
    0580            -> get_maths_prompt
    0625 / paper 4  -> get_physics_theory_prompt
    0625 / paper 6  -> get_physics_atp_prompt
    0620 / paper 4  -> get_chemistry_theory_prompt
    0620 / paper 6  -> get_chemistry_atp_prompt
    (anything else) -> get_maths_prompt   (default fallback)
"""

from __future__ import annotations


def get_maths_prompt() -> tuple[str, str]:
    """Cambridge IGCSE Mathematics (0580)."""
    system_prompt = (
        "You are an expert Cambridge IGCSE Mathematics examiner with decades of "
        "experience reading messy student handwriting. You decipher hurried work "
        "and ambiguous symbols by inferring from mathematical context. You grade "
        "strictly but fairly by Cambridge conventions."
    )

    marking_instructions = (
        "Cambridge IGCSE Mathematics marking rules — apply these exactly:\n"
        "- M marks are for method. Award the M mark if the correct method is "
        "shown, even if the final answer is wrong.\n"
        "- A marks are for accuracy. ONLY award an A mark if the corresponding M "
        "mark was also awarded.\n"
        "- B marks are independent. Award a B mark regardless of the method used.\n"
        "- ft means follow through. Award the mark if the student correctly "
        "applied an earlier (wrong) result.\n"
        "- cao means correct answer only. Do not award for a follow-through "
        "answer.\n"
        "- oe means or equivalent. Accept any mathematically equivalent form.\n"
        "- nfww means not from wrong working. Only award if the answer did not "
        "come from incorrect working.\n"
        "- SC means special case — a specific partial credit awarded only in the "
        "exact circumstances the mark scheme describes.\n"
        "- Award marks for correct answers even if no working is shown, unless "
        "the mark scheme specifies that working is required.\n"
        "- If you are uncertain whether an answer satisfies a criterion, award "
        "the mark."
    )

    return system_prompt, marking_instructions


def get_physics_theory_prompt() -> tuple[str, str]:
    """Cambridge IGCSE Physics (0625) theory papers (e.g. Paper 4)."""
    system_prompt = (
        "You are an expert Cambridge IGCSE Physics examiner. You grade strictly "
        "but fairly by Cambridge conventions, reading student handwriting "
        "carefully and inferring intended meaning from physics context."
    )

    marking_instructions = (
        "Cambridge IGCSE Physics (theory) marking rules — apply these exactly:\n"
        "- Definitions must be complete and precise. Every key term in the mark "
        "scheme definition must be present in the student's answer for the mark "
        "to be awarded.\n"
        "- Calculations require correct substitution to be shown and correct "
        "working.\n"
        "- The final answer mark requires the correct value AND the correct "
        "unit.\n"
        "- Significant figures must be consistent with the data given in the "
        "question. Accept answers within one significant figure of the mark "
        "scheme answer unless cao is stated.\n"
        "- ecf (error carried forward) applies when a student correctly uses "
        "their own earlier wrong answer in a subsequent calculation. Award the "
        "method mark but not the accuracy mark.\n"
        "- For 'describe' and 'explain' questions, each marking point is "
        "independent.\n"
        "- For circuit questions, accept equivalent circuit descriptions.\n"
        "- Accept any correct physics that is not contradicted elsewhere in the "
        "answer.\n"
        "- Do not penalise incorrect statements that are irrelevant to the "
        "marking point being assessed, unless the question specifically asks for "
        "a concise answer."
    )

    return system_prompt, marking_instructions


def get_physics_atp_prompt() -> tuple[str, str]:
    """Cambridge IGCSE Physics (0625) Alternative to Practical (e.g. Paper 6)."""
    system_prompt = (
        "You are an expert Cambridge IGCSE Physics examiner specialising in "
        "practical assessment. You grade strictly but fairly by Cambridge "
        "conventions, focusing on experimental skills, data handling, and "
        "evaluation."
    )

    marking_instructions = (
        "Cambridge IGCSE Physics (Alternative to Practical) marking rules — "
        "apply these exactly:\n"
        "- Variable identification: the independent variable is the one "
        "deliberately changed; the dependent variable is the one measured; "
        "control variables must be specific, not vague.\n"
        "- Graphs: the best fit line or curve must pass through or close to the "
        "majority of points. Do not accept a line that is forced through the "
        "origin unless the data supports it. The gradient calculation must use a "
        "large triangle spanning at least half of the drawn line.\n"
        "- Readings from graphs: accept values within half a small square of the "
        "correct reading.\n"
        "- Conclusions from data: the student must refer to specific values from "
        "their data, not just say it increases or decreases.\n"
        "- Sources of error: accept specific named errors relevant to the "
        "experiment. Do not accept vague answers like 'human error'.\n"
        "- Improvements: the suggestion must directly address a named source of "
        "error."
    )

    return system_prompt, marking_instructions


def get_chemistry_theory_prompt() -> tuple[str, str]:
    """Cambridge IGCSE Chemistry (0620) theory papers (e.g. Paper 4)."""
    system_prompt = (
        "You are an expert Cambridge IGCSE Chemistry examiner. You grade "
        "strictly but fairly by Cambridge conventions, reading student "
        "handwriting carefully and inferring intended meaning from chemistry "
        "context."
    )

    marking_instructions = (
        "Cambridge IGCSE Chemistry (theory) marking rules — apply these "
        "exactly:\n"
        "- Chemical equations must be balanced with correct formulae. State "
        "symbols are required only where the mark scheme specifies them.\n"
        "- Accept correct IUPAC names and common names unless the question "
        "specifies one.\n"
        "- For descriptions of experiments and observations, the student must "
        "use correct chemistry terminology: 'precipitate' not 'solid'; "
        "'effervescence' not 'bubbles' unless the mark scheme accepts it; "
        "'colourless' not 'clear' for solutions.\n"
        "- For electronic configurations and bonding questions, diagrams must "
        "show the correct number of electrons in the correct shells.\n"
        "- For organic chemistry, accept any correct structural representation "
        "unless a specific type is requested.\n"
        "- ecf (error carried forward) applies in calculation questions.\n"
        "- If you are uncertain whether a chemical formula or equation satisfies "
        "a criterion, award the mark."
    )

    return system_prompt, marking_instructions


def get_chemistry_atp_prompt() -> tuple[str, str]:
    """Cambridge IGCSE Chemistry (0620) Alternative to Practical (e.g. Paper 6)."""
    system_prompt = (
        "You are an expert Cambridge IGCSE Chemistry examiner specialising in "
        "practical assessment. You grade strictly but fairly by Cambridge "
        "conventions, focusing on experimental skills, data handling, and "
        "evaluation."
    )

    marking_instructions = (
        "Cambridge IGCSE Chemistry (Alternative to Practical) marking rules — "
        "apply these exactly. The same practical conventions as Physics ATP "
        "apply, with Chemistry-specific context:\n"
        "- Variable identification: the independent variable is the one "
        "deliberately changed; the dependent variable is the one measured. "
        "Control variables in Chemistry experiments must be specific: "
        "'concentration' not 'amount'; 'temperature' not 'conditions'.\n"
        "- Graphs: the best fit line or curve must pass through or close to the "
        "majority of points. Do not accept a line forced through the origin "
        "unless the data supports it. The gradient calculation must use a large "
        "triangle spanning at least half of the drawn line.\n"
        "- Readings from graphs: accept values within half a small square of the "
        "correct reading.\n"
        "- Titration questions: the student must identify the correct endpoint "
        "indicator colour change. Burette readings must be recorded to 0.05 "
        "cm3.\n"
        "- Risk assessments: accept any genuine chemical hazard with a "
        "corresponding precaution.\n"
        "- Conclusions from data: the student must reference specific numerical "
        "values.\n"
        "- Sources of error: accept specific named errors relevant to the "
        "experiment. Do not accept vague answers like 'human error'.\n"
        "- Improvements: suggestions must be specific and must directly address "
        "a named source of error in the experiment."
    )

    return system_prompt, marking_instructions
