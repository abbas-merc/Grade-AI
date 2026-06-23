/**
 * types/paperGenerator.ts — Types for the Custom Paper Generator feature.
 *
 * Mirrors the backend contract: POST /api/generate-paper request/response, the
 * GET /api/generate-paper/pool summary, and the per-question / mark-scheme
 * shapes used by the preview and PDF endpoints.
 *
 * Questions are now image snippets: each carries a `questionImageUrl`
 * (host-agnostic, e.g. "/question_snippets/<id>.png" — prepend BASE_URL) instead
 * of `questionText`. The mark scheme stays text.
 */

export type GeneratorDifficulty = "mixed" | "easy" | "medium" | "hard";

/** Which source paper type to draw from. "both" = the full pool. */
export type PaperType = "P2" | "P4" | "both";

export interface GeneratePaperRequest {
  subject: string;
  paperType: PaperType;
  /** The full list of topic strings to draw from (never the word "all"). */
  topics: string[];
  totalMarks: number;
  difficulty: GeneratorDifficulty;
}

export interface GeneratedQuestion {
  assignedNumber: number;
  originalPaperCode: string;
  /** Source paper type of this question ("P2" | "P4"). */
  paperType: string;
  /** True when sourced from a specimen paper. */
  isSpecimen?: boolean;
  marks: number;
  topic: string;
  difficulty: string;
  /** Host-agnostic snippet path, e.g. "/question_snippets/<id>.png"; prepend BASE_URL. */
  questionImageUrl: string;
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

/** One question's selection metadata from GET /api/generate-paper/pool — enough
 *  to compute the available-marks ceiling for any filter combination. */
export interface PoolQuestion {
  paperType: string;
  topic: string;
  difficulty: string;
  marks: number;
}

export interface GeneratorPool {
  topics: string[];
  questions: PoolQuestion[];
}
