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
  /** Host-agnostic snippet path ("/question_snippets/<id>.png"); prepend BASE_URL.
   *  Present for image-snippet papers, empty/absent for legacy text papers. */
  question_image_url?: string;
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
  // Topic this question belongs to (e.g. "algebra"). Present for generated
  // papers (and re-seeded reference papers); drives the results PDF's per-topic
  // performance analysis. Empty/absent when the source carries no topic.
  topic?: string;
  extracted_answer: string;
  marks_awarded: number;
  marks_available: number;
  mark_breakdown: PaperMarkBreakdownPoint[];
  feedback: string;
  // True when the transcript contains an [illegible] token — the model could
  // not read part of this answer, so the teacher should check it manually.
  has_illegible?: boolean;
  // True when the model was unsure about reading part of this answer (a digit or
  // symbol was ambiguous). Surfaced as a subtle "check reading" hint so a human
  // verifies the transcription. Does not affect the marks awarded.
  low_confidence?: boolean;
}

export interface PaperGradingResult {
  paper_id: number;
  total_marks_awarded: number;
  total_marks_available: number;
  cost_usd: number;
  results: QuestionResult[];
  cost_cap_reached: boolean;
  // True when the per-question maximum marks don't sum to the paper total —
  // individual question totals may contain a marking error.
  marks_total_mismatch?: boolean;
  // Firestore document ID of the saved marking (teachers/{uid}/markings/{id}).
  // Present when the backend successfully persisted the result.
  marking_id?: string;
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
  // Lifecycle of the marking job. Absent on legacy documents → treat as
  // "complete". "processing"/"queued" rows show a progress indicator instead of
  // a score; "failed"/"error" rows show a failure note.
  status?: "queued" | "processing" | "complete" | "failed" | "error";
  // While status is "processing", the current pipeline step (e.g. "Reading
  // handwriting") shown as a subtitle in the History row.
  progress_step?: string;
  // Firestore document ID of this marking under teachers/{uid}/markings.
  // Used to delete the corresponding Firestore document. Absent on entries
  // graded before this field existed (those delete locally only).
  marking_id?: string;
}
