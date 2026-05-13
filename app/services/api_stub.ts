/**
 * services/api_stub.ts — Mock implementations of the api.ts contract.
 *
 * Used by screens while app/services/api.ts is being built by Agent 4.
 * To switch to the real backend, change each screen's import from
 *   '../services/api_stub'  →  '../services/api'
 *
 * All functions match the exact signatures defined in services/CLAUDE.md.
 */

import type { Paper, Question, GradingResult } from "../types";

const FAKE_DELAY_MS = 600;

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

const MOCK_PAPERS: Paper[] = [
  {
    id: 1,
    subject_code: "0580",
    year: 2023,
    session: "May/June",
    paper_number: 2,
    tier: "Extended",
    total_marks: 70,
  },
  {
    id: 2,
    subject_code: "0580",
    year: 2022,
    session: "October/November",
    paper_number: 2,
    tier: "Extended",
    total_marks: 70,
  },
];

const MOCK_QUESTIONS: Record<number, Question[]> = {
  1: [
    {
      id: 1,
      question_number: "1",
      question_text:
        "Expand and simplify.\n(x + 3)(x − 2)",
      marks_available: 2,
    },
    {
      id: 2,
      question_number: "2",
      question_text:
        "Solve the equation.\n2x + 5 = 13",
      marks_available: 2,
    },
    {
      id: 3,
      question_number: "3",
      question_text:
        "A rectangle has length (2x + 1) cm and width (x − 1) cm.\nWrite an expression, in terms of x, for the perimeter of the rectangle.\nGive your answer in its simplest form.",
      marks_available: 3,
    },
  ],
  2: [
    {
      id: 4,
      question_number: "1",
      question_text:
        "Find the value of 5³ − 3 × (7 + 4).",
      marks_available: 2,
    },
    {
      id: 5,
      question_number: "2",
      question_text:
        "Write 0.000 047 in standard form.",
      marks_available: 1,
    },
  ],
};

const MOCK_GRADING_RESULT: GradingResult = {
  session_id: 42,
  question_id: 1,
  question_text: "Expand and simplify.\n(x + 3)(x − 2)",
  marks_awarded: 3,
  marks_available: 4,
  mark_breakdown: [
    {
      point_number: 1,
      criterion: "Correct x² term",
      awarded: true,
      reason: "Student wrote x² correctly from expanding the brackets.",
    },
    {
      point_number: 2,
      criterion: "Correct x term (−2x + 3x = x)",
      awarded: true,
      reason: "The middle terms were collected correctly to give +x.",
    },
    {
      point_number: 3,
      criterion: "Correct constant −6",
      awarded: true,
      reason: "3 × (−2) = −6 was correct.",
    },
    {
      point_number: 4,
      criterion: "Final simplified answer x² + x − 6",
      awarded: false,
      reason:
        "Student left the answer un-simplified — like terms were not collected into a single expression.",
    },
  ],
  feedback:
    "Well done — you correctly multiplied out all four terms and got the x² and constant right! The only thing to fix is remembering to collect like terms into a single, simplified expression at the end. One more step and you'd have full marks. Keep going — you're nearly there!",
  extracted_text: "x^2 - 2x + 3x - 6",
  cost_usd: 0.0021,
};

// ---------------------------------------------------------------------------
// Stub functions (match Agent 4 api.ts contract exactly)
// ---------------------------------------------------------------------------

/** Fetch all exam papers. */
export async function getPapers(): Promise<Paper[]> {
  await delay(FAKE_DELAY_MS);
  return MOCK_PAPERS;
}

/** Fetch questions for a paper. */
export async function getQuestions(paperId: number): Promise<Question[]> {
  await delay(FAKE_DELAY_MS);
  const questions = MOCK_QUESTIONS[paperId];
  if (!questions) {
    throw new Error("Failed to load questions");
  }
  return questions;
}

/** Fetch a single question by ID. */
export async function getQuestion(questionId: number): Promise<Question> {
  await delay(FAKE_DELAY_MS);
  for (const list of Object.values(MOCK_QUESTIONS)) {
    const found = list.find((q) => q.id === questionId);
    if (found) return found;
  }
  throw new Error("Failed to load question");
}

/** Grade a student answer image (base64). */
export async function gradeAnswer(
  questionId: number,
  imageBase64: string
): Promise<GradingResult> {
  // Simulate the 5-10 second grading time
  await delay(2000);
  return { ...MOCK_GRADING_RESULT, question_id: questionId };
}

/** Check if the backend server is reachable. */
export async function checkHealth(): Promise<boolean> {
  await delay(200);
  return true;
}
