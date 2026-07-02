/**
 * services/generatedPapers.ts — Persist and read a teacher's saved custom papers.
 *
 * When a teacher is happy with a generated paper on the preview screen they can
 * name and save it. Saved papers live at teachers/{uid}/generated_papers/{id} —
 * scoped to the owner, mirroring how markings are stored (the Firestore rules
 * are default-deny, so a top-level collection would be blocked; a subcollection
 * under teachers/{uid} is allowed for the owner). The app writes and reads these
 * directly via @react-native-firebase, the same pattern as markingQueue.ts and
 * historyService.ts — no backend endpoint required.
 *
 * The full generated-paper payload (questions + mark scheme + image URLs) is
 * stored so the "My Generated Papers" list can reopen the exact same
 * PaperPreviewScreen (download question paper / mark scheme, mark responses).
 */

import auth from "@react-native-firebase/auth";
import firestore from "@react-native-firebase/firestore";

import type {
  GeneratedPaper,
  GeneratedQuestion,
  MarkSchemeItem,
} from "../types/paperGenerator";

const COLLECTION = "generated_papers";

/** A saved custom paper as read back from Firestore. */
export interface SavedGeneratedPaper {
  id: string;
  paperName: string;
  /** ISO string derived from the Firestore createdAt server timestamp. */
  createdAt: string;
  subject: string;
  /** "P2" | "P4" | "both", derived from the questions when saved. */
  paperType: string;
  topics: string[];
  totalMarks: number;
  numQuestions: number;
  schoolName: string;
  questions: GeneratedQuestion[];
  markScheme: MarkSchemeItem[];
}

/** The current user's generated_papers subcollection, or null if signed out. */
function papersCollection() {
  const uid = auth().currentUser?.uid;
  if (!uid) return null;
  return firestore().collection("teachers").doc(uid).collection(COLLECTION);
}

/** Derive the paper-type tag from the mix of source question types. */
function derivePaperType(questions: GeneratedQuestion[]): string {
  const types = new Set(questions.map((q) => q.paperType).filter(Boolean));
  if (types.size === 1) return [...types][0];
  return "both";
}

/** Distinct, ordered topics represented in the paper. */
function deriveTopics(questions: GeneratedQuestion[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const q of questions) {
    if (q.topic && !seen.has(q.topic)) {
      seen.add(q.topic);
      out.push(q.topic);
    }
  }
  return out;
}

/**
 * Save a generated paper under the teacher's generated_papers collection.
 *
 * @param paper - The full generate-paper response the teacher is previewing.
 * @param name  - The teacher-provided display name.
 * @returns The new document ID.
 * @throws  Error if the teacher isn't signed in or the write fails.
 */
export async function saveGeneratedPaper(
  paper: GeneratedPaper,
  name: string
): Promise<string> {
  const uid = auth().currentUser?.uid;
  if (!uid) {
    throw new Error("You must be signed in to save a paper.");
  }
  const col = papersCollection();
  if (!col) {
    throw new Error("You must be signed in to save a paper.");
  }

  const doc = col.doc();
  await doc.set({
    paperName: name.trim() || "Untitled Paper",
    createdAt: firestore.FieldValue.serverTimestamp(),
    teacherUid: uid,
    subject: paper.subject,
    paperType: derivePaperType(paper.questions),
    topics: deriveTopics(paper.questions),
    totalMarks: paper.totalMarks,
    numQuestions: paper.numQuestions,
    schoolName: paper.schoolName ?? "",
    questions: paper.questions,
    markScheme: paper.markScheme,
  });
  return doc.id;
}

/** Map a Firestore document into a SavedGeneratedPaper for display. */
function docToSaved(
  id: string,
  data: Record<string, any>
): SavedGeneratedPaper {
  let createdAt: string;
  if (data.createdAt && typeof data.createdAt.toDate === "function") {
    createdAt = data.createdAt.toDate().toISOString();
  } else {
    createdAt = new Date().toISOString();
  }
  return {
    id,
    paperName: data.paperName || "Untitled Paper",
    createdAt,
    subject: data.subject || "math",
    paperType: data.paperType || "both",
    topics: Array.isArray(data.topics) ? data.topics : [],
    totalMarks: Number(data.totalMarks ?? 0),
    numQuestions: Number(data.numQuestions ?? 0),
    schoolName: data.schoolName || "",
    questions: Array.isArray(data.questions) ? data.questions : [],
    markScheme: Array.isArray(data.markScheme) ? data.markScheme : [],
  };
}

/**
 * Rebuild the GeneratedPaper payload the preview screen expects from a saved
 * paper, so tapping a saved paper reopens the identical preview/download flow.
 */
export function savedToGeneratedPaper(saved: SavedGeneratedPaper): GeneratedPaper {
  return {
    paperId: saved.id,
    subject: saved.subject,
    totalMarks: saved.totalMarks,
    numQuestions: saved.numQuestions,
    questions: saved.questions,
    markScheme: saved.markScheme,
    schoolName: saved.schoolName,
    paperName: saved.paperName,
  };
}

/**
 * Subscribe to the teacher's saved papers in real time (newest first). Returns
 * an unsubscribe function. Emits an empty list once if no user is signed in.
 */
export function subscribeToGeneratedPapers(
  onChange: (papers: SavedGeneratedPaper[]) => void,
  onError?: (err: Error) => void
): () => void {
  const col = papersCollection();
  if (!col) {
    onChange([]);
    return () => {};
  }
  return col.orderBy("createdAt", "desc").onSnapshot(
    (snap) => {
      onChange(
        snap.docs.map((d) => docToSaved(d.id, (d.data() as Record<string, any>) || {}))
      );
    },
    (err) => {
      console.error("[generatedPapers] subscribe → snapshot error", err);
      if (onError) onError(err as Error);
    }
  );
}

/** One-shot read of the teacher's saved papers (newest first). */
export async function getGeneratedPapers(): Promise<SavedGeneratedPaper[]> {
  const col = papersCollection();
  if (!col) return [];
  const snap = await col.orderBy("createdAt", "desc").get();
  return snap.docs.map((d) => docToSaved(d.id, (d.data() as Record<string, any>) || {}));
}

/** Delete a saved paper. Deleting a non-existent doc is a no-op in Firestore. */
export async function deleteGeneratedPaper(id: string): Promise<void> {
  const col = papersCollection();
  if (col && id) {
    await col.doc(id).delete();
  }
}
