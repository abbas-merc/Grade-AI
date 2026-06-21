/**
 * types/paperGenerator.ts — Types for the Custom Paper Generator feature.
 *
 * Mirrors the backend contract: POST /api/generate-paper request/response and
 * the per-question / mark-scheme shapes used by the preview and PDF endpoints.
 */

export type GeneratorDifficulty = "mixed" | "easy" | "medium" | "hard";

export interface GeneratePaperRequest {
  subject: string;
  /** The full list of topic strings to draw from (never the word "all"). */
  topics: string[];
  totalMarks: number;
  difficulty: GeneratorDifficulty;
}

export interface GeneratedQuestion {
  assignedNumber: number;
  originalPaperCode: string;
  marks: number;
  questionText: string;
  topic: string;
  difficulty: string;
  /** True when the question has an extracted figure to render. */
  hasImage?: boolean;
  /** Host-agnostic figure path, e.g. "/diagrams/<id>.png"; prepend BASE_URL. */
  imageUrl?: string;
}

export interface MarkSchemeItem {
  questionNumber: number;
  marks: number;
  markSchemeText: string;
}

export interface GeneratedPaper {
  paperId: string;
  subject: string;
  totalMarks: number;
  numQuestions: number;
  questions: GeneratedQuestion[];
  markScheme: MarkSchemeItem[];
}
