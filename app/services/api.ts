/**
 * services/api.ts — Typed HTTP client for the GradeAI FastAPI backend.
 *
 * All functions use named exports. The axios instance is not exported —
 * consumers import individual functions only.
 *
 * Error contract:
 *   - All functions throw an Error on failure.
 *   - checkHealth() is the only function that never throws; it returns false.
 */

import axios from "axios";
import type { AxiosError } from "axios";
import {
  BASE_URL,
  GRADING_TIMEOUT_MS,
  POLL_INTERVAL_MS,
  MAX_POLL_ATTEMPTS,
} from "../constants/config";
import type { Paper, Question, GradingResult, PaperGradingResult } from "../types";

// ---------------------------------------------------------------------------
// Axios instance
// ---------------------------------------------------------------------------

const client = axios.create({
  baseURL: BASE_URL,
  timeout: 30000,
  headers: { "Content-Type": "application/json" },
});

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/** Shape of FastAPI's standard error response body. */
interface FastAPIErrorBody {
  detail: string;
}

function isFastAPIErrorBody(data: unknown): data is FastAPIErrorBody {
  return (
    typeof data === "object" &&
    data !== null &&
    "detail" in data &&
    typeof (data as FastAPIErrorBody).detail === "string"
  );
}

/**
 * Extract a human-readable message from an axios error.
 * Prefers `response.data.detail` (FastAPI standard), falls back to
 * `response.statusText`, then a generic network error message.
 */
function extractAxiosMessage(error: AxiosError): string {
  if (error.response) {
    const data = error.response.data;
    if (isFastAPIErrorBody(data)) {
      return data.detail;
    }
    return error.response.statusText || "Server error";
  }
  return "Network error — is the server running?";
}

// ---------------------------------------------------------------------------
// Papers
// ---------------------------------------------------------------------------

/**
 * Fetch all available exam papers.
 *
 * @returns Array of Paper objects from GET /papers.
 * @throws  Error("Failed to load papers") on any failure.
 */
export async function getPapers(): Promise<Paper[]> {
  try {
    const { data } = await client.get<Paper[]>("/papers/");
    return data;
  } catch (err) {
    if (axios.isAxiosError(err)) {
      throw new Error(`Failed to load papers: ${extractAxiosMessage(err)}`);
    }
    throw new Error("Failed to load papers");
  }
}

// ---------------------------------------------------------------------------
// Questions
// ---------------------------------------------------------------------------

/**
 * Fetch all questions belonging to a paper.
 *
 * @param paperId - The paper ID whose questions to retrieve.
 * @returns Array of Question objects from GET /papers/{paperId}/questions.
 * @throws  Error("Failed to load questions") on any failure.
 */
export async function getQuestions(paperId: number): Promise<Question[]> {
  try {
    const { data } = await client.get<Question[]>(
      `/papers/${paperId}/questions`
    );
    return data;
  } catch (err) {
    if (axios.isAxiosError(err)) {
      throw new Error(`Failed to load questions: ${extractAxiosMessage(err)}`);
    }
    throw new Error("Failed to load questions");
  }
}

/**
 * Fetch a single question by ID.
 *
 * @param questionId - The question ID to retrieve.
 * @returns A Question object from GET /questions/{questionId}.
 * @throws  Error("Failed to load question") on any failure.
 */
export async function getQuestion(questionId: number): Promise<Question> {
  try {
    const { data } = await client.get<Question>(`/questions/${questionId}`);
    return data;
  } catch (err) {
    if (axios.isAxiosError(err)) {
      throw new Error(`Failed to load question: ${extractAxiosMessage(err)}`);
    }
    throw new Error("Failed to load question");
  }
}

// ---------------------------------------------------------------------------
// Single-question grading
// ---------------------------------------------------------------------------

/**
 * Submit a student answer image for AI grading (single question).
 *
 * @param questionId  - ID of the question being answered.
 * @param imageBase64 - Raw base64 image string (no data URI prefix).
 * @returns GradingResult containing score, mark breakdown, and feedback.
 * @throws  Error("Grading failed: {detail}") on any failure.
 */
export async function gradeAnswer(
  questionId: number,
  imageBase64: string
): Promise<GradingResult> {
  try {
    const { data } = await client.post<GradingResult>(
      "/grade",
      { question_id: questionId, image_base64: imageBase64 },
      { timeout: GRADING_TIMEOUT_MS }
    );
    return data;
  } catch (err) {
    if (axios.isAxiosError(err)) {
      throw new Error(`Grading failed: ${extractAxiosMessage(err)}`);
    }
    throw new Error("Grading failed: unexpected error");
  }
}

// ---------------------------------------------------------------------------
// Full-paper grading
// ---------------------------------------------------------------------------

interface StartGradingResponse {
  job_id: string;
}

interface GradingStatusResponse {
  status: "pending" | "running" | "done" | "error";
  result?: PaperGradingResult | null;
  error?: string | null;
}

/**
 * Submit multiple page photos of an answer booklet to grade an entire paper.
 *
 * Uses the async backend pattern to avoid Cloudflare's ~100s edge timeout:
 *   1. POST /grade/paper           — returns a job_id immediately
 *   2. GET  /grade/paper/status/id — polled every POLL_INTERVAL_MS until done
 *
 * @param paperId    - ID of the paper being graded.
 * @param pageImages - Array of raw base64 JPEG strings, one per photographed page.
 * @returns PaperGradingResult with total score and per-question breakdowns.
 * @throws  Error("Paper grading failed: {detail}") on any failure.
 */
export async function gradePaper(
  paperId: number,
  pageImages: string[]
): Promise<PaperGradingResult> {
  let jobId: string;
  try {
    const { data } = await client.post<StartGradingResponse>(
      "/grade/paper",
      { paper_id: paperId, page_images: pageImages },
      { timeout: 60000 }
    );
    jobId = data.job_id;
  } catch (err) {
    if (axios.isAxiosError(err)) {
      throw new Error(`Paper grading failed: ${extractAxiosMessage(err)}`);
    }
    throw new Error("Paper grading failed: unexpected error");
  }

  for (let attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
    try {
      const { data } = await client.get<GradingStatusResponse>(
        `/grade/paper/status/${jobId}`,
        { timeout: 15000 }
      );
      if (data.status === "done" && data.result) {
        return data.result;
      }
      if (data.status === "error") {
        throw new Error(data.error || "Grading failed");
      }
    } catch (err) {
      // Transient poll failure — try again on next tick. Only give up
      // if it's a non-axios error (real bug) or a 404 (job lost).
      if (axios.isAxiosError(err) && err.response?.status === 404) {
        throw new Error("Grading job expired. Please try again.");
      }
      if (!axios.isAxiosError(err)) {
        throw err;
      }
    }
  }

  throw new Error("Grading is taking longer than expected. Please try again.");
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

/** Shape of the backend GET /health response. */
interface HealthResponse {
  status: string;
}

/**
 * Check whether the backend server is reachable.
 *
 * @returns true if the server responds with { status: "ok" }, false otherwise.
 *          Never throws.
 */
export async function checkHealth(): Promise<boolean> {
  try {
    const { data } = await client.get<HealthResponse>("/health");
    return data.status === "ok";
  } catch {
    return false;
  }
}
