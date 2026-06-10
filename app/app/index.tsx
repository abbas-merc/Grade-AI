/**
 * app/index.tsx — Home screen: Papers tab and History tab.
 *
 * History reloads from AsyncStorage every time this screen comes into focus
 * (via useFocusEffect) so a result saved on the results screen is visible
 * immediately when the user navigates back.
 *
 * Each history row supports swipe-left-to-delete using Animated + PanResponder
 * (no external gesture library required).
 */

import React, { useState, useCallback, useRef, useEffect } from "react";
import {
  View,
  Text,
  FlatList,
  TouchableOpacity,
  ActivityIndicator,
  StyleSheet,
  Animated,
  PanResponder,
} from "react-native";
import { useRouter, useFocusEffect, useLocalSearchParams } from "expo-router";
import auth from "@react-native-firebase/auth";

import { getPapers } from "../services/api";
import { getHistory, deleteHistoryEntry } from "../services/historyService";
import PaperCard from "../components/PaperCard";
import type { Paper, HistoryEntry } from "../types";

// Width of the red delete zone revealed by a left swipe
const DELETE_WIDTH = 80;

type Tab = "papers" | "history";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function scoreColor(pct: number): string {
  if (pct >= 80) return "#059669";
  if (pct >= 50) return "#4F46E5";
  return "#DC2626";
}

function paperLabel(paper: Paper): string {
  const session = paper.session
    .replace("May/June", "M/J")
    .replace("October/November", "O/N");
  return `IGCSE ${paper.subject_code} · Paper ${paper.paper_number} · ${session} ${paper.year}`;
}

// ─── HistoryRow (swipe-to-delete) ─────────────────────────────────────────────

function HistoryRow({
  entry,
  onDelete,
  onPress,
}: {
  entry: HistoryEntry;
  onDelete: () => void;
  onPress: () => void;
}) {
  const translateX = useRef(new Animated.Value(0)).current;
  const isOpen = useRef(false);

  // Keep latest callbacks in refs so panResponder (created once) can call them
  const onDeleteRef = useRef(onDelete);
  const onPressRef = useRef(onPress);
  useEffect(() => { onDeleteRef.current = onDelete; }, [onDelete]);
  useEffect(() => { onPressRef.current = onPress; }, [onPress]);

  const snapClosed = useCallback(() => {
    isOpen.current = false;
    Animated.spring(translateX, {
      toValue: 0,
      useNativeDriver: true,
      tension: 120,
      friction: 14,
    }).start();
  }, [translateX]);

  const snapOpen = useCallback(() => {
    isOpen.current = true;
    Animated.spring(translateX, {
      toValue: -DELETE_WIDTH,
      useNativeDriver: true,
      tension: 120,
      friction: 14,
    }).start();
  }, [translateX]);

  // Keep latest snap functions accessible to the stable panResponder
  const snapClosedRef = useRef(snapClosed);
  const snapOpenRef = useRef(snapOpen);
  useEffect(() => { snapClosedRef.current = snapClosed; }, [snapClosed]);
  useEffect(() => { snapOpenRef.current = snapOpen; }, [snapOpen]);

  const panResponder = useRef(
    PanResponder.create({
      // Claim the responder only on clear horizontal movement
      onMoveShouldSetPanResponder: (_, { dx, dy }) =>
        Math.abs(dx) > 8 && Math.abs(dx) > Math.abs(dy),

      onPanResponderMove: (_, { dx }) => {
        // Offset from current open/closed position
        const base = isOpen.current ? -DELETE_WIDTH : 0;
        const next = Math.max(-DELETE_WIDTH, Math.min(0, base + dx));
        translateX.setValue(next);
      },

      onPanResponderRelease: (_, { dx, vx }) => {
        const base = isOpen.current ? -DELETE_WIDTH : 0;
        const finalX = base + dx;
        // Open if swiped past threshold or flicked left quickly
        if (finalX < -DELETE_WIDTH / 3 || vx < -0.5) {
          snapOpenRef.current();
        } else {
          snapClosedRef.current();
        }
      },
    })
  ).current;

  const color = scoreColor(entry.percentage);

  return (
    // overflow:hidden clips the row as it slides left, keeping layout clean
    <View style={styles.swipeWrapper}>
      {/* Red delete button lives behind the sliding row */}
      <View style={styles.deleteAction}>
        <TouchableOpacity
          style={styles.deleteActionButton}
          onPress={() => onDeleteRef.current()}
          activeOpacity={0.85}
        >
          <Text style={styles.deleteActionText}>Delete</Text>
        </TouchableOpacity>
      </View>

      {/* Sliding foreground card */}
      <Animated.View
        style={{ transform: [{ translateX }] }}
        {...panResponder.panHandlers}
      >
        <TouchableOpacity
          style={styles.historyRow}
          activeOpacity={0.8}
          onPress={() => {
            if (isOpen.current) {
              snapClosed(); // first tap on open row closes it
            } else {
              onPressRef.current();
            }
          }}
        >
          <View style={styles.historyMain}>
            <Text style={styles.historyPaperName} numberOfLines={1}>
              {entry.paper_name}
            </Text>
            <Text style={styles.historyDate}>{formatDate(entry.graded_at)}</Text>
          </View>
          <View style={[styles.scoreBadge, { borderColor: color }]}>
            <Text style={[styles.scoreText, { color }]}>
              {entry.total_marks_awarded}/{entry.total_marks_available}
            </Text>
            <Text style={[styles.scorePercent, { color }]}>{entry.percentage}%</Text>
          </View>
        </TouchableOpacity>
      </Animated.View>
    </View>
  );
}

// ─── HomeScreen ───────────────────────────────────────────────────────────────

export default function HomeScreen() {
  const router = useRouter();
  const { tab } = useLocalSearchParams<{ tab?: string }>();
  const [activeTab, setActiveTab] = useState<Tab>(tab === "history" ? "history" : "papers");

  // React to deep-link / nav params (e.g. Done button on results screen passes tab=history)
  useEffect(() => {
    if (tab === "history" || tab === "papers") {
      setActiveTab(tab);
    }
  }, [tab]);

  // ── Papers ────────────────────────────────────────────────────────────────
  const [papers, setPapers] = useState<Paper[]>([]);
  const [papersLoading, setPapersLoading] = useState(true);
  const [papersError, setPapersError] = useState<string | null>(null);

  const loadPapers = useCallback(() => {
    setPapersLoading(true);
    setPapersError(null);
    getPapers()
      .then(setPapers)
      .catch((err: Error) => setPapersError(err.message))
      .finally(() => setPapersLoading(false));
  }, []);

  useEffect(() => {
    loadPapers();
  }, [loadPapers]);

  // ── History ───────────────────────────────────────────────────────────────
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      setHistory(await getHistory());
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  // Pull-to-refresh — reads AsyncStorage without showing the full-screen spinner
  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      setHistory(await getHistory());
    } finally {
      setRefreshing(false);
    }
  }, []);

  // Reload every time the screen comes back into focus (e.g. after grading)
  useFocusEffect(
    useCallback(() => {
      loadHistory();
    }, [loadHistory])
  );

  const handleDelete = useCallback(async (id: string) => {
    // Optimistic update — remove from UI immediately
    setHistory((prev) => prev.filter((e) => e.id !== id));
    try {
      await deleteHistoryEntry(id);
    } catch {
      // If the delete fails, reload to restore correct state
      loadHistory();
    }
  }, [loadHistory]);

  // Sign out — the auth listener in _layout.tsx redirects to the sign-in screen.
  const handleSignOut = useCallback(async () => {
    try {
      await auth().signOut();
    } catch {
      // Ignore — signing out locally effectively always succeeds.
    }
  }, []);

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <View style={styles.container}>
      {/* Tab bar */}
      <View style={styles.tabBar}>
        <TouchableOpacity
          style={[styles.tab, activeTab === "papers" && styles.tabActive]}
          onPress={() => setActiveTab("papers")}
          activeOpacity={0.8}
        >
          <Text style={[styles.tabText, activeTab === "papers" && styles.tabTextActive]}>
            Papers
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.tab, activeTab === "history" && styles.tabActive]}
          onPress={() => setActiveTab("history")}
          activeOpacity={0.8}
        >
          <Text style={[styles.tabText, activeTab === "history" && styles.tabTextActive]}>
            History
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={styles.signOutButton}
          onPress={handleSignOut}
          activeOpacity={0.7}
        >
          <Text style={styles.signOutText}>Sign out</Text>
        </TouchableOpacity>
      </View>

      {/* ── Papers tab ── */}
      {activeTab === "papers" && (
        <>
          {papersLoading ? (
            <View style={styles.centered}>
              <ActivityIndicator size="large" color="#4F46E5" />
              <Text style={styles.mutedText}>Loading papers…</Text>
            </View>
          ) : papersError ? (
            <View style={styles.centered}>
              <Text style={styles.errorText}>Failed to load papers.</Text>
              <Text style={styles.errorDetail}>{papersError}</Text>
              <TouchableOpacity style={styles.retryButton} onPress={loadPapers}>
                <Text style={styles.retryText}>Retry</Text>
              </TouchableOpacity>
            </View>
          ) : papers.length === 0 ? (
            <View style={styles.centered}>
              <Text style={styles.mutedText}>No papers available yet.</Text>
            </View>
          ) : (
            <FlatList
              data={papers}
              keyExtractor={(item) => String(item.id)}
              contentContainerStyle={styles.listContent}
              ListHeaderComponent={
                <Text style={styles.sectionLabel}>Select a paper to begin</Text>
              }
              ItemSeparatorComponent={() => <View style={{ height: 12 }} />}
              renderItem={({ item }) => (
                <PaperCard
                  paper={item}
                  onPress={() =>
                    router.push({
                      pathname: "/paper/[id]",
                      params: { id: String(item.id), paperName: paperLabel(item) },
                    })
                  }
                />
              )}
            />
          )}
        </>
      )}

      {/* ── History tab ── */}
      {activeTab === "history" && (
        // Show the centered loader only on first load. Subsequent reloads
        // show the list with a pull-to-refresh spinner instead.
        historyLoading && history.length === 0 ? (
          <View style={styles.centered}>
            <ActivityIndicator size="large" color="#4F46E5" />
            <Text style={styles.mutedText}>Loading history…</Text>
          </View>
        ) : (
          <FlatList
            data={history}
            keyExtractor={(item) => item.id}
            contentContainerStyle={
              history.length === 0 ? styles.emptyListContent : styles.listContent
            }
            refreshing={refreshing}
            onRefresh={handleRefresh}
            ListHeaderComponent={
              history.length > 0 ? (
                <Text style={styles.sectionLabel}>
                  {history.length} session{history.length !== 1 ? "s" : ""} · swipe left to delete
                </Text>
              ) : null
            }
            ListEmptyComponent={
              <View style={styles.emptyHistory}>
                <Text style={styles.emptyIcon}>📋</Text>
                <Text style={styles.emptyTitle}>No grading history yet</Text>
                <Text style={styles.emptySubtitle}>
                  Grade a paper and your results will appear here.
                  {"\n"}Pull down to refresh.
                </Text>
              </View>
            }
            renderItem={({ item }) => (
              <HistoryRow
                entry={item}
                onDelete={() => handleDelete(item.id)}
                onPress={() =>
                  router.push({
                    pathname: "/results/paper",
                    params: {
                      resultData: JSON.stringify(item.result),
                      paperName: item.paper_name,
                      gradedAt: item.graded_at,
                      fromHistory: "true",
                    },
                  })
                }
              />
            )}
          />
        )
      )}
    </View>
  );
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#F9FAFB",
  },
  centered: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    gap: 10,
    padding: 24,
  },

  // Tab bar
  tabBar: {
    flexDirection: "row",
    backgroundColor: "#fff",
    borderBottomWidth: 1,
    borderBottomColor: "#E5E7EB",
    paddingHorizontal: 16,
  },
  tab: {
    paddingVertical: 12,
    paddingHorizontal: 20,
    borderBottomWidth: 2,
    borderBottomColor: "transparent",
  },
  tabActive: {
    borderBottomColor: "#4F46E5",
  },
  tabText: {
    fontSize: 15,
    fontWeight: "600",
    color: "#9CA3AF",
  },
  tabTextActive: {
    color: "#4F46E5",
  },
  signOutButton: {
    marginLeft: "auto",
    justifyContent: "center",
    paddingVertical: 12,
    paddingHorizontal: 8,
  },
  signOutText: {
    fontSize: 14,
    fontWeight: "600",
    color: "#DC2626",
  },

  // Shared list
  listContent: {
    paddingHorizontal: 16,
    paddingTop: 12,
    paddingBottom: 32,
  },
  sectionLabel: {
    fontSize: 13,
    color: "#9CA3AF",
    marginBottom: 10,
  },

  // States
  mutedText: {
    color: "#6B7280",
    fontSize: 15,
  },
  errorText: {
    fontSize: 17,
    fontWeight: "600",
    color: "#EF4444",
  },
  errorDetail: {
    fontSize: 13,
    color: "#6B7280",
    textAlign: "center",
  },
  retryButton: {
    backgroundColor: "#4F46E5",
    borderRadius: 10,
    paddingHorizontal: 24,
    paddingVertical: 12,
    marginTop: 4,
  },
  retryText: {
    color: "#fff",
    fontWeight: "600",
    fontSize: 15,
  },

  // Empty history (FlatList content style + the empty component itself)
  emptyListContent: {
    flexGrow: 1,
    paddingHorizontal: 16,
  },
  emptyHistory: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    gap: 10,
    paddingVertical: 80,
  },
  emptyIcon: {
    fontSize: 40,
  },
  emptyTitle: {
    fontSize: 17,
    fontWeight: "700",
    color: "#1F2937",
  },
  emptySubtitle: {
    fontSize: 14,
    color: "#9CA3AF",
    textAlign: "center",
    lineHeight: 20,
  },

  // Swipe wrapper — overflow:hidden clips the row as it slides left
  swipeWrapper: {
    overflow: "hidden",
    borderRadius: 12,
    marginBottom: 10,
    // Shadow lives here so overflow:hidden doesn't clip it on Android;
    // on iOS shadows render outside the bounds anyway
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.06,
    shadowRadius: 3,
    elevation: 1,
  },

  // Red delete button (sits behind the sliding row)
  deleteAction: {
    position: "absolute",
    right: 0,
    top: 0,
    bottom: 0,
    width: DELETE_WIDTH,
    backgroundColor: "#EF4444",
    justifyContent: "center",
    alignItems: "center",
  },
  deleteActionButton: {
    flex: 1,
    width: "100%",
    justifyContent: "center",
    alignItems: "center",
  },
  deleteActionText: {
    color: "#fff",
    fontSize: 14,
    fontWeight: "700",
  },

  // History row card (slides over the delete button)
  historyRow: {
    backgroundColor: "#fff",
    padding: 14,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  historyMain: {
    flex: 1,
    gap: 3,
  },
  historyPaperName: {
    fontSize: 14,
    fontWeight: "600",
    color: "#1F2937",
  },
  historyDate: {
    fontSize: 12,
    color: "#9CA3AF",
  },
  scoreBadge: {
    borderWidth: 1.5,
    borderRadius: 10,
    paddingHorizontal: 10,
    paddingVertical: 6,
    alignItems: "center",
    minWidth: 70,
  },
  scoreText: {
    fontSize: 14,
    fontWeight: "700",
  },
  scorePercent: {
    fontSize: 11,
    fontWeight: "600",
  },
});
