/**
 * types/question.ts — Question schema for the Custom Paper Generator.
 *
 * A `Question` is one self-contained past-paper question (all its parts),
 * stored in the flat top-level Firestore `questions` collection. Unlike the
 * existing nested `papers/{id}/questions` data, these are denormalized with
 * topic/subtopic/paper metadata so the generator can query across papers by
 * subject + topic.
 *
 * NOTE: this project uses @react-native-firebase, not the web `firebase` SDK,
 * so `Timestamp` is `FirebaseFirestoreTypes.Timestamp`.
 */

import type { FirebaseFirestoreTypes } from "@react-native-firebase/firestore";

export type Subject = "math" | "physics" | "chemistry";

/** May/June, Oct/Nov, Feb/March. */
export type Session = "MJ" | "ON" | "FM";

/** Difficulty bucket, derived from marks: <=10 easy, 11-13 medium, 14+ hard
 *  (see backend/seed_custom_questions.py `difficulty()`, the source of truth). */
export type Difficulty = "easy" | "medium" | "hard";

export interface Question {
  id: string;
  subject: Subject;
  /** e.g. "algebra", "number", "geometry", "statistics", "probability" */
  topic: string;
  /** e.g. "linear equations", "fractions", "pie charts" */
  subtopic: string;
  /** e.g. 2023 */
  year: number;
  session: Session;
  /** e.g. "0580/42/M/J/23" */
  paperCode: string;
  /** Question number in the original paper. */
  originalQuestionNumber: number;
  marks: number;
  /** Full question text including all parts (a), (b), (c). */
  questionText: string;
  /** Full mark scheme for this question. */
  markSchemeText: string;
  hasImage: boolean;
  /** Firebase Storage URL, present only when `hasImage` is true. */
  imageUrl?: string;
  difficulty: Difficulty;
  createdAt: FirebaseFirestoreTypes.Timestamp;
}
