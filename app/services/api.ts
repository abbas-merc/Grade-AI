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
import type { AxiosError, InternalAxiosRequestConfig } from "axios";
import auth from "@react-native-firebase/auth";
import { encode as encodeBase64 } from "base64-arraybuffer";
import { BASE_URL, GRADING_TIMEOUT_MS } from "../constants/config";
import type { Paper, Question, GradingResult, PaperGradingResult } from "../types";
import type {
  GeneratedPaper,
  GeneratePaperRequest,
  GeneratorPool,
} from "../types/paperGenerator";

// ---------------------------------------------------------------------------
// Axios instance
// ---------------------------------------------------------------------------

const client = axios.create({
  baseURL: BASE_URL,
  timeout: 30000,
  headers: { "Content-Type": "application/json" },
});

// ---------------------------------------------------------------------------
// Auth interceptor
// ---------------------------------------------------------------------------

// Before every request, attach the current Firebase user's ID token as a
// Bearer token. getIdToken() returns a cached token and silently refreshes it
// when it's close to expiry. If no user is signed in, the request proceeds
// without an Authorization header (e.g. the open /health check).
client.interceptors.request.use(
  async (config: InternalAxiosRequestConfig) => {
    const currentUser = auth().currentUser;
    if (currentUser) {
      // Propagate token errors instead of swallowing — sending a tokenless
      // request always yields a 401 and wastes the retry budget.
      const token = await currentUser.getIdToken();
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  }
);

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
    const msg = err instanceof Error ? err.message : String(err);
    throw new Error(`Failed to load papers: ${msg}`);
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

// Full-paper grading no longer goes through an HTTP endpoint. The app writes a
// "queued" document directly to Firestore (see services/markingQueue.ts) and a
// backend listener grades it. The History tab observes status changes live.

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

// ---------------------------------------------------------------------------
// Custom Paper Generator
// ---------------------------------------------------------------------------

/**
 * Fetch the distinct topics available for a subject (for the topic chip row).
 *
 * @param subject - e.g. "math".
 * @returns Array of topic strings from GET /questions/topics?subject=...
 * @throws  Error("Failed to load topics") on any failure.
 */
export async function getTopics(subject: string): Promise<string[]> {
  try {
    const { data } = await client.get<{ topics: string[] }>("/questions/topics", {
      params: { subject },
    });
    return data.topics ?? [];
  } catch (err) {
    if (axios.isAxiosError(err)) {
      throw new Error(`Failed to load topics: ${extractAxiosMessage(err)}`);
    }
    throw new Error("Failed to load topics");
  }
}

/**
 * Fetch the question pool summary for a subject: the distinct topics plus
 * lightweight per-question metadata (paperType, topic, difficulty, marks). The
 * Custom Paper form uses this to render the topic chips and to compute the
 * reactive "Available: X marks" ceiling for any filter combination client-side.
 *
 * @param subject - e.g. "math".
 * @returns GeneratorPool from GET /api/generate-paper/pool?subject=...
 * @throws  Error("Failed to load question pool") on any failure.
 */
export async function getQuestionPool(subject: string): Promise<GeneratorPool> {
  try {
    const { data } = await client.get<GeneratorPool>("/api/generate-paper/pool", {
      params: { subject },
    });
    return { topics: data.topics ?? [], questions: data.questions ?? [] };
  } catch (err) {
    if (axios.isAxiosError(err)) {
      throw new Error(`Failed to load question pool: ${extractAxiosMessage(err)}`);
    }
    throw new Error("Failed to load question pool");
  }
}

/**
 * Generate a custom paper from the questions collection.
 *
 * @param req - Subject, paperType, topics, totalMarks, difficulty.
 * @returns The generated paper (questions + mark scheme) from
 *          POST /api/generate-paper.
 * @throws  Error("Failed to generate paper") on any failure.
 */
export async function generatePaper(
  req: GeneratePaperRequest
): Promise<GeneratedPaper> {
  try {
    const { data } = await client.post<GeneratedPaper>("/api/generate-paper", req);
    return data;
  } catch (err) {
    if (axios.isAxiosError(err)) {
      throw new Error(`Failed to generate paper: ${extractAxiosMessage(err)}`);
    }
    throw new Error("Failed to generate paper");
  }
}

/**
 * POST a generated paper to a PDF endpoint and return the PDF as a base64
 * string (ready for FileSystem.writeAsStringAsync with Base64 encoding).
 */
async function downloadPdfAsBase64(
  path: string,
  paper: GeneratedPaper
): Promise<string> {
  const { data } = await client.post<ArrayBuffer>(path, paper, {
    responseType: "arraybuffer",
    timeout: GRADING_TIMEOUT_MS,
  });
  return encodeBase64(data);
}

/**
 * Download the question-paper PDF for a generated paper.
 * @returns base64-encoded PDF bytes.
 * @throws  Error("Failed to download question paper") on any failure.
 */
export async function downloadQuestionPaperPdf(
  paper: GeneratedPaper
): Promise<string> {
  try {
    return await downloadPdfAsBase64(
      "/api/generate-paper/download-question-paper",
      paper
    );
  } catch (err) {
    if (axios.isAxiosError(err)) {
      throw new Error(`Failed to download question paper: ${extractAxiosMessage(err)}`);
    }
    throw new Error("Failed to download question paper");
  }
}

/**
 * Download the mark-scheme PDF for a generated paper.
 * @returns base64-encoded PDF bytes.
 * @throws  Error("Failed to download mark scheme") on any failure.
 */
export async function downloadMarkSchemePdf(
  paper: GeneratedPaper
): Promise<string> {
  try {
    return await downloadPdfAsBase64(
      "/api/generate-paper/download-mark-scheme",
      paper
    );
  } catch (err) {
    if (axios.isAxiosError(err)) {
      throw new Error(`Failed to download mark scheme: ${extractAxiosMessage(err)}`);
    }
    throw new Error("Failed to download mark scheme");
  }
}

// ---------------------------------------------------------------------------
// Marked-results PDF
// ---------------------------------------------------------------------------

/**
 * Download the shareable "Marked Results" PDF for a completed marking.
 *
 * Sends the Firestore marking id (`resultId`) when known — the backend reads it
 * from the caller's own markings, which enforces ownership — and always carries
 * the full result + display fields as a fallback for legacy entries that have no
 * stored id.
 *
 * @returns base64-encoded PDF bytes (ready for FileSystem.writeAsStringAsync).
 * @throws  Error("Failed to download results: {detail}") on any failure.
 */
export async function downloadResultsPdf(params: {
  resultId?: string;
  result: PaperGradingResult;
  paperName?: string;
  gradedAt?: string;
}): Promise<string> {
  try {
    const { data } = await client.post<ArrayBuffer>(
      "/api/results/download-pdf",
      {
        result_id: params.resultId,
        result: params.result,
        paper_name: params.paperName,
        graded_at: params.gradedAt,
      },
      { responseType: "arraybuffer", timeout: GRADING_TIMEOUT_MS }
    );
    return encodeBase64(data);
  } catch (err) {
    if (axios.isAxiosError(err)) {
      throw new Error(`Failed to download results: ${extractAxiosMessage(err)}`);
    }
    throw new Error("Failed to download results");
  }
}
