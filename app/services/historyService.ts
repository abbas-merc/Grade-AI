/**
 * services/historyService.ts — Grading history.
 *
 * The source of truth is Firestore at teachers/{uid}/markings — the backend
 * writes one document there per graded paper. The History tab reads directly
 * from that subcollection, so every entry's `id` (and `marking_id`) IS the
 * Firestore document ID. That guarantees a swipe-to-delete removes the exact
 * document at teachers/{uid}/markings/{markingId} and can never drift.
 *
 * AsyncStorage is kept only as an offline display cache: getHistory() refreshes
 * it on every successful Firestore read and falls back to it when Firestore is
 * unreachable or no user is signed in.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";
import auth from "@react-native-firebase/auth";
import firestore from "@react-native-firebase/firestore";
import type { HistoryEntry, PaperGradingResult } from "../types";

const STORAGE_KEY = "@gradeai_history_v1";

/**
 * The current user's markings subcollection (teachers/{uid}/markings), or null
 * if no user is signed in.
 */
function markingsCollection() {
  const uid = auth().currentUser?.uid;
  if (!uid) return null;
  return firestore().collection("teachers").doc(uid).collection("markings");
}

/**
 * Map a Firestore marking document into a HistoryEntry for display.
 * The document ID is used as both the local `id` and the `marking_id`, so the
 * delete path always has the correct Firestore reference.
 */
function docToEntry(
  id: string,
  data: Record<string, any>
): HistoryEntry {
  const awarded = Number(data.total_marks_awarded ?? 0);
  const available = Number(data.total_marks_available ?? 0);
  const percentage =
    typeof data.percentage === "number"
      ? data.percentage
      : available > 0
      ? Math.round((awarded / available) * 100)
      : 0;

  // Prefer the graded_at written by the client; otherwise derive from the
  // server timestamp; otherwise fall back to "now".
  let gradedAt: string;
  if (typeof data.graded_at === "string") {
    gradedAt = data.graded_at;
  } else if (data.created_at && typeof data.created_at.toDate === "function") {
    gradedAt = data.created_at.toDate().toISOString();
  } else {
    gradedAt = new Date().toISOString();
  }

  // The stored document IS the grading result. Drop the Firestore-only
  // created_at field so the replayed result object stays clean.
  const { created_at, paper_name, graded_at, percentage: _pct, ...result } =
    data;

  const status =
    typeof data.status === "string" ? data.status : "complete";

  return {
    id,
    marking_id: id,
    paper_id: Number(data.paper_id ?? 0),
    paper_name: data.paper_name || `Paper ${data.paper_id ?? ""}`.trim(),
    graded_at: gradedAt,
    total_marks_awarded: awarded,
    total_marks_available: available,
    percentage,
    result: result as PaperGradingResult,
    status: status as HistoryEntry["status"],
    progress_step:
      typeof data.progress_step === "string" ? data.progress_step : undefined,
  };
}

export async function saveHistoryEntry(entry: HistoryEntry): Promise<void> {
  // The backend already created the marking document in Firestore when it
  // graded the paper. Here we only enrich that document with the display
  // metadata the backend doesn't have (paper name, graded-at, percentage), so
  // the History tab can render it without a local cache. Non-fatal on failure.
  if (entry.marking_id) {
    const col = markingsCollection();
    if (col) {
      try {
        await col.doc(entry.marking_id).set(
          {
            paper_name: entry.paper_name,
            graded_at: entry.graded_at,
            percentage: entry.percentage,
          },
          { merge: true }
        );
      } catch (err) {
        console.error(
          "[historyService] saveHistoryEntry → Firestore merge FAILED",
          err
        );
      }
    }
  }

  // Keep a local cache copy for offline display.
  try {
    const existing = await readCache();
    const updated = [entry, ...existing.filter((e) => e.id !== entry.id)];
    await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
  } catch (err) {
    console.error("[historyService] saveHistoryEntry → cache write FAILED", err);
  }
}

async function readCache(): Promise<HistoryEntry[]> {
  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as HistoryEntry[];
  } catch (err) {
    console.error("[historyService] readCache → read/parse FAILED", err);
    return [];
  }
}

export async function getHistory(): Promise<HistoryEntry[]> {
  const col = markingsCollection();
  if (col) {
    try {
      const snap = await col.orderBy("created_at", "desc").get();
      const entries = snap.docs.map((doc) =>
        docToEntry(doc.id, (doc.data() as Record<string, any>) || {})
      );
      console.log(
        `[historyService] getHistory → loaded ${entries.length} entries from Firestore`
      );
      // Refresh the offline cache.
      try {
        await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
      } catch {
        // Cache refresh is best-effort.
      }
      return entries;
    } catch (err) {
      console.error(
        "[historyService] getHistory → Firestore read FAILED, using cache",
        err
      );
    }
  }
  // Offline / signed-out fallback.
  return readCache();
}

/**
 * Subscribe to the teacher's markings in real time.
 *
 * Uses a Firestore onSnapshot listener so the History tab updates automatically
 * when a grading job is created ("processing") and again when it completes
 * ("complete") — no manual refresh needed. The offline cache is refreshed on
 * every snapshot. Returns an unsubscribe function; call it on unmount.
 *
 * If no user is signed in, emits the cached entries once and is a no-op.
 */
export function subscribeToHistory(
  onChange: (entries: HistoryEntry[]) => void,
  onError?: (err: Error) => void
): () => void {
  const col = markingsCollection();
  if (!col) {
    readCache()
      .then(onChange)
      .catch(() => onChange([]));
    return () => {};
  }

  const unsubscribe = col.orderBy("created_at", "desc").onSnapshot(
    (snap) => {
      const entries = snap.docs.map((doc) =>
        docToEntry(doc.id, (doc.data() as Record<string, any>) || {})
      );
      AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(entries)).catch(() => {
        // Cache refresh is best-effort.
      });
      onChange(entries);
    },
    (err) => {
      console.error("[historyService] subscribeToHistory → snapshot error", err);
      if (onError) onError(err as Error);
    }
  );

  return unsubscribe;
}

/**
 * Delete a history entry.
 *
 * The Firestore document at teachers/{uid}/markings/{markingId} is deleted
 * FIRST. Only if that succeeds do we remove the entry from the local cache.
 * If the Firestore delete throws, this propagates so the caller can surface the
 * error and keep the row visible — the UI never drifts out of sync.
 *
 * Because the History tab is sourced from Firestore, `id` already equals the
 * document ID; `markingId` is accepted for compatibility and preferred when
 * present. Deleting a non-existent document is a no-op in Firestore, so legacy
 * cache-only rows clean up locally without raising a false error.
 *
 * @param id        Entry id (the Firestore document id).
 * @param markingId Firestore document id under teachers/{uid}/markings.
 */
export async function deleteHistoryEntry(
  id: string,
  markingId?: string
): Promise<void> {
  const docId = markingId || id;
  const col = markingsCollection();
  if (col && docId) {
    // Let any failure propagate — the caller must NOT update local state.
    await col.doc(docId).delete();
    console.log(
      `[historyService] deleteHistoryEntry → Firestore delete OK (docId=${docId})`
    );
  }

  // Only reached if the Firestore delete succeeded (or there was nothing to
  // delete). Remove the row from the local cache too.
  const existing = await readCache();
  const updated = existing.filter((e) => e.id !== id);
  await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
}

export async function clearHistory(): Promise<void> {
  await AsyncStorage.removeItem(STORAGE_KEY);
}
