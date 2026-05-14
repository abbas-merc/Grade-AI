/**
 * services/historyService.ts — AsyncStorage-backed grading history.
 *
 * Each graded paper is saved as a HistoryEntry. Entries are stored as a
 * JSON array, newest first. The list is loaded once per app session;
 * individual writes append to the front.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";
import type { HistoryEntry } from "../types";

const STORAGE_KEY = "@gradeai_history_v1";

export async function saveHistoryEntry(entry: HistoryEntry): Promise<void> {
  const existing = await getHistory();
  const updated = [entry, ...existing];
  const payload = JSON.stringify(updated);
  console.log(
    `[historyService] saveHistoryEntry → about to setItem (key=${STORAGE_KEY}, entries=${updated.length}, bytes=${payload.length}, id=${entry.id})`
  );
  try {
    await AsyncStorage.setItem(STORAGE_KEY, payload);
    console.log(
      `[historyService] saveHistoryEntry → setItem OK (entries=${updated.length}, id=${entry.id})`
    );
  } catch (err) {
    console.error("[historyService] saveHistoryEntry → setItem FAILED", err);
    throw err;
  }
}

export async function getHistory(): Promise<HistoryEntry[]> {
  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEY);
    if (!raw) {
      console.log("[historyService] getHistory → no entries stored");
      return [];
    }
    const parsed = JSON.parse(raw) as HistoryEntry[];
    console.log(`[historyService] getHistory → loaded ${parsed.length} entries`);
    return parsed;
  } catch (err) {
    console.error("[historyService] getHistory → read/parse FAILED", err);
    return [];
  }
}

export async function deleteHistoryEntry(id: string): Promise<void> {
  const existing = await getHistory();
  const updated = existing.filter((e) => e.id !== id);
  await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
}

export async function clearHistory(): Promise<void> {
  await AsyncStorage.removeItem(STORAGE_KEY);
}
