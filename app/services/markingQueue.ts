/**
 * services/markingQueue.ts — Submit a paper to the Firestore grading queue.
 *
 * Pages are delivered entirely through Firestore — NO Firebase Storage. Each
 * captured page is downscaled + JPEG-compressed (expo-image-manipulator) to fit
 * comfortably under Firestore's ~1 MB per-document limit, then written as its own
 * document in a `pages` subcollection under the marking. The parent
 * teachers/{uid}/markings/{auto-id} document is written LAST with status
 * "queued", so the backend's queue listener (marking_worker.py) only picks the
 * job up once every page is already in place. The worker reads the `pages`
 * subcollection, grades, and updates the same parent document — the History tab
 * sees every state change in real time.
 *
 * This path deliberately avoids Firebase Storage: that product requires the
 * Storage API + Blaze billing to be provisioned server-side, which this project
 * does not have. Firestore is already enabled and used everywhere else.
 */

import auth from "@react-native-firebase/auth";
import firestore from "@react-native-firebase/firestore";
import { ImageManipulator, SaveFormat } from "expo-image-manipulator";

import type { GeneratedPaper } from "../types/paperGenerator";

// IGCSE subject-code mapping used to route the backend examiner prompt. The
// generator is math-only today; the others are here for when it expands.
const SUBJECT_CODES: Record<string, string> = {
  math: "0580",
  physics: "0625",
  chemistry: "0620",
};

/**
 * Map a generated paper into the inline shape `run_full_paper_grading` consumes
 * when no stored paper_id is available — the same fields the backend would
 * otherwise read from the papers collection (paper meta + questions, each with
 * a `mark_scheme` list of `{description}` points).
 */
function buildInlinePaper(paper: GeneratedPaper) {
  const markSchemeByNumber = new Map(
    paper.markScheme.map((m) => [m.questionNumber, m])
  );
  return {
    paper: {
      id: 0,
      subject_code: SUBJECT_CODES[paper.subject] ?? "0580",
      paper_number: 0,
      session: "Custom",
      year: new Date().getFullYear(),
      tier: "Extended",
      total_marks: paper.totalMarks,
    },
    questions: paper.questions.map((q) => ({
      id: `gen_${q.assignedNumber}`,
      question_number: String(q.assignedNumber),
      marks_available: q.marks,
      // Questions are image snippets now, so there's no extracted question text;
      // give the grader a short context line and let it mark strictly against the
      // mark scheme (which carries the required answers + mark allocation).
      question_text: `Question ${q.assignedNumber} — ${q.topic} (${q.marks} marks). Mark strictly against the mark scheme below.`,
      mark_scheme: [
        { description: markSchemeByNumber.get(q.assignedNumber)?.markSchemeText ?? "" },
      ],
    })),
  };
}

// Downscale width + JPEG quality chosen to keep each encoded page well under
// Firestore's 1,048,576-byte document cap while staying legible for handwriting
// recognition. A 1600px-wide page at quality 0.6 is typically 200–470 KB base64.
const MAX_PAGE_WIDTH = 1600;
const JPEG_QUALITY = 0.6;

/**
 * Compress one captured page and return its raw base64 JPEG (no data-URI prefix).
 *
 * @param uri - Local file URI of the captured photo.
 * @returns Base64-encoded, downscaled JPEG suitable for storing in a Firestore doc.
 * @throws Error if the manipulator fails to produce base64 output.
 */
async function compressPageToBase64(uri: string): Promise<string> {
  const context = ImageManipulator.manipulate(uri).resize({ width: MAX_PAGE_WIDTH });
  const image = await context.renderAsync();
  const result = await image.saveAsync({
    base64: true,
    compress: JPEG_QUALITY,
    format: SaveFormat.JPEG,
  });
  if (!result.base64) {
    throw new Error("Could not encode a captured page. Please retake it.");
  }
  return result.base64;
}

/**
 * Compress the captured pages and enqueue a grading job.
 *
 * @param paperId        - Integer paper ID being graded (0 for generated papers).
 * @param paperName      - Human-readable paper name (for the History row label).
 * @param pageUris       - Local file URIs of the captured pages, in page order.
 * @param generatedPaper - When marking a Custom Paper Generator paper, the full
 *                         generate-paper response. Its questions + mark scheme
 *                         are written inline on the job so the backend can grade
 *                         without a stored paper_id.
 * @returns The new marking document ID.
 * @throws  Error if the teacher isn't signed in or a write fails.
 */
export async function submitPaperForGrading(
  paperId: number,
  paperName: string,
  pageUris: string[],
  generatedPaper?: GeneratedPaper
): Promise<string> {
  const uid = auth().currentUser?.uid;
  if (!uid) {
    throw new Error("You must be signed in to submit a paper.");
  }

  // Allocate the marking document ID up-front so its pages can be namespaced by it.
  const docRef = firestore()
    .collection("teachers")
    .doc(uid)
    .collection("markings")
    .doc();
  const markingId = docRef.id;

  // Write each compressed page as its own document in the `pages` subcollection.
  // Doc IDs are zero-padded so they also sort in page order, and each carries an
  // explicit `index` the worker sorts on.
  const pagesCollection = docRef.collection("pages");
  for (let i = 0; i < pageUris.length; i++) {
    const base64 = await compressPageToBase64(pageUris[i]);
    await pagesCollection.doc(String(i).padStart(4, "0")).set({
      index: i,
      image_base64: base64,
    });
  }

  // Write the queued job LAST. The backend listener watches for status == "queued";
  // by now every page document already exists.
  const job: Record<string, unknown> = {
    status: "queued",
    created_at: firestore.FieldValue.serverTimestamp(),
    paper_id: paperId,
    paper_name: paperName,
    page_count: pageUris.length,
    teacher_uid: uid,
  };

  // Generated paper: attach its questions + mark scheme inline so the backend
  // grades against them instead of looking the paper up by paper_id.
  if (generatedPaper) {
    job.inline_paper = buildInlinePaper(generatedPaper);
  }

  await docRef.set(job);

  return markingId;
}
