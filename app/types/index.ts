/**
 * types/index.ts — Shared TypeScript interfaces for GradeAI.
 * These mirror the shape of the FastAPI response models.
 */

// Shared TypeScript interfaces used by all frontend agents
// DO NOT MODIFY without updating all agents

export interface Paper {
  id: number;
  subject_code: string;
  year: number;
  session: string;
  paper_number: number;
  tier: string;
  total_marks: number;
}

export interface Question {
  id: number;
  question_number: string;
  question_text: string;
  marks_available: number;
}

export interface MarkBreakdownPoint {
  point_number: number;
  criterion: string;
  awarded: boolean;
  reason: string;
}

export interface GradingResult {
  session_id: number;
  question_id: number;
  question_text: string;
  marks_awarded: number;
  marks_available: number;
  mark_breakdown: MarkBreakdownPoint[];
  feedback: string;
  extracted_text: string;
  cost_usd: number;
}

export interface GradeRequest {
  question_id: number;
  image_base64: string;
}

// --- Full-paper grading types ---

export interface PaperMarkBreakdownPoint {
  criterion: string;
  awarded: boolean;
  reason: string;
}

export interface QuestionResult {
  question_number: string;
  question_text: string;
  extracted_answer: string;
  marks_awarded: number;
  marks_available: number;
  mark_breakdown: PaperMarkBreakdownPoint[];
  feedback: string;
}

export interface PaperGradingResult {
  paper_id: number;
  total_marks_awarded: number;
  total_marks_available: number;
  cost_usd: number;
  results: QuestionResult[];
  cost_cap_reached: boolean;
}

export interface HistoryEntry {
  id: string;
  paper_id: number;
  paper_name: string;
  graded_at: string;
  total_marks_awarded: number;
  total_marks_available: number;
  percentage: number;
  result: PaperGradingResult;
}
