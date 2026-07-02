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
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  StyleSheet,
  Animated,
  PanResponder,
  Alert,
} from "react-native";
import {
  useRouter,
  useLocalSearchParams,
} from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import auth from "@react-native-firebase/auth";

import { getPapers } from "../services/api";
import {
  getHistory,
  deleteHistoryEntry,
  subscribeToHistory,
} from "../services/historyService";
import {
  subscribeToGeneratedPapers,
  savedToGeneratedPaper,
  deleteGeneratedPaper,
  type SavedGeneratedPaper,
} from "../services/generatedPapers";
import PaperCard from "../components/PaperCard";
import type { Paper, HistoryEntry } from "../types";
import { COLORS, RADIUS, SPACING, FONT, ON } from "../constants/theme";

// Width of the red delete zone revealed by a left swipe
const DELETE_WIDTH = 80;

// A queued/processing job older than this is almost certainly stuck (a typical
// paper grades in 30–90 s). We surface that to the teacher instead of spinning
// "Grading…" forever. The backend also sweeps stale jobs to "failed" on restart.
const STUCK_AFTER_MS = 3 * 60 * 1000;

type Tab = "papers" | "history";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function scoreBadgeColors(pct: number): { backgroundColor: string; color: string } {
  if (pct >= 70) return { backgroundColor: COLORS.passLight, color: ON.passText };
  if (pct >= 50) return { backgroundColor: COLORS.warningLight, color: ON.warningText };
  return { backgroundColor: COLORS.failLight, color: ON.failText };
}

function paperLabel(paper: Paper): string {
  const session = paper.session
    .replace("May/June", "M/J")
    .replace("October/November", "O/N");
  return `IGCSE ${paper.subject_code} · Paper ${paper.paper_number} · ${session} ${paper.year}`;
}

function getSubjectName(subject_code: string): string {
  switch (subject_code) {
    case "0580":
      return "Mathematics";
    case "0625":
      return "Physics";
    case "0620":
      return "Chemistry";
    default:
      return subject_code;
  }
}

// Group papers by subject name, preserving the order Mathematics, Physics,
// Chemistry (any other subjects follow in first-seen order).
function groupPapersBySubject(papers: Paper[]): Record<string, Paper[]> {
  const groups: Record<string, Paper[]> = {};
  for (const paper of papers) {
    const name = getSubjectName(paper.subject_code);
    if (!groups[name]) {
      groups[name] = [];
    }
    groups[name].push(paper);
  }

  const ordered: Record<string, Paper[]> = {};
  for (const name of ["Mathematics", "Physics", "Chemistry"]) {
    if (groups[name]) {
      ordered[name] = groups[name];
    }
  }
  for (const name of Object.keys(groups)) {
    if (!ordered[name]) {
      ordered[name] = groups[name];
    }
  }
  return ordered;
}

// ─── ProcessingBadge (in-progress indicator) ──────────────────────────────────

// Blue "Grading..." pill that fades between 0.4 and 1.0 on a 1-second loop, with
// the current backend progress_step shown as a subtitle beneath it.
function ProcessingBadge({ progressStep }: { progressStep?: string }) {
  const opacity = useRef(new Animated.Value(0.4)).current;
  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, {
          toValue: 1,
          duration: 500,
          useNativeDriver: true,
        }),
        Animated.timing(opacity, {
          toValue: 0.4,
          duration: 500,
          useNativeDriver: true,
        }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [opacity]);
  return (
    <View style={styles.processingWrap}>
      <Animated.View style={[styles.processingPill, { opacity }]}>
        <Text style={styles.processingPillText}>Grading...</Text>
      </Animated.View>
      {progressStep ? (
        <Text style={styles.progressStepText} numberOfLines={1}>
          {progressStep}
        </Text>
      ) : null}
    </View>
  );
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
  useEffect(() => {
    onDeleteRef.current = onDelete;
  }, [onDelete]);
  useEffect(() => {
    onPressRef.current = onPress;
  }, [onPress]);

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
  useEffect(() => {
    snapClosedRef.current = snapClosed;
  }, [snapClosed]);
  useEffect(() => {
    snapOpenRef.current = snapOpen;
  }, [snapOpen]);

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
    }),
  ).current;

  const badge = scoreBadgeColors(entry.percentage);
  const queued = entry.status === "queued";
  const processing = entry.status === "processing";
  const failed = entry.status === "failed" || entry.status === "error";
  // Surface jobs that have been queued/processing far longer than normal.
  const stale =
    (queued || processing) &&
    Date.now() - new Date(entry.graded_at).getTime() > STUCK_AFTER_MS;

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
              return;
            }
            // Don't open results until the job has finished grading.
            if (entry.status && entry.status !== "complete") return;
            onPressRef.current();
          }}
        >
          <View style={styles.historyMain}>
            <Text style={styles.historyPaperName} numberOfLines={1}>
              {entry.paper_name}
            </Text>
            {/* Paper name + timestamp always show, regardless of status. */}
            <Text style={styles.historyDate}>
              {formatDate(entry.graded_at)}
            </Text>
            {stale && (
              <Text style={styles.staleNote}>
                Taking longer than expected — check back soon.
              </Text>
            )}
          </View>
          {queued ? (
            <View style={styles.queuePill}>
              <Text style={styles.queuePillText}>In queue</Text>
            </View>
          ) : processing ? (
            <ProcessingBadge progressStep={entry.progress_step} />
          ) : failed ? (
            <View style={styles.failPill}>
              <Text style={styles.failPillText}>Failed</Text>
            </View>
          ) : (
            <View
              style={[styles.scoreBadge, { backgroundColor: badge.backgroundColor }]}
            >
              <Text style={[styles.scoreText, { color: badge.color }]}>
                {entry.total_marks_awarded}/{entry.total_marks_available}
              </Text>
              <Text style={[styles.scorePercent, { color: badge.color }]}>
                {entry.percentage}%
              </Text>
            </View>
          )}
        </TouchableOpacity>
      </Animated.View>
    </View>
  );
}

// ─── GeneratedPaperRow (saved custom paper) ───────────────────────────────────

function GeneratedPaperRow({
  paper,
  onPress,
  onLongPress,
}: {
  paper: SavedGeneratedPaper;
  onPress: () => void;
  onLongPress: () => void;
}) {
  const subtitle = `${paper.totalMarks} marks · ${paper.numQuestions} question${
    paper.numQuestions === 1 ? "" : "s"
  } · ${formatDate(paper.createdAt)}`;
  return (
    <TouchableOpacity
      style={styles.generatedRow}
      activeOpacity={0.8}
      onPress={onPress}
      onLongPress={onLongPress}
    >
      <View style={styles.generatedMain}>
        <Text style={styles.generatedName} numberOfLines={1}>
          {paper.paperName}
        </Text>
        <Text style={styles.generatedMeta}>{subtitle}</Text>
      </View>
      <Text style={styles.generatedChevron}>›</Text>
    </TouchableOpacity>
  );
}

// ─── HomeScreen ───────────────────────────────────────────────────────────────

export default function HomeScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { tab } = useLocalSearchParams<{ tab?: string }>();
  const [activeTab, setActiveTab] = useState<Tab>(
    tab === "history" ? "history" : "papers",
  );

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

  const loadPapers = useCallback(async () => {
    setPapersLoading(true);
    setPapersError(null);
    // Retry up to 3 times (1.5 s apart) to survive brief backend restarts and
    // Firebase token re-initialization that happen after hot reloads.
    let lastError: Error | null = null;
    for (let attempt = 0; attempt < 3; attempt++) {
      if (attempt > 0) {
        await new Promise<void>((resolve) => setTimeout(resolve, 1500));
      }
      try {
        setPapers(await getPapers());
        setPapersLoading(false);
        return;
      } catch (err) {
        lastError = err as Error;
      }
    }
    setPapersError(lastError?.message ?? "Unknown error");
    setPapersLoading(false);
  }, []);

  useEffect(() => {
    loadPapers();
  }, [loadPapers]);

  // ── My Generated Papers ─────────────────────────────────────────────────────
  const [generatedPapers, setGeneratedPapers] = useState<SavedGeneratedPaper[]>([]);

  // Real-time listener so a paper saved on the preview screen appears here
  // immediately, and a deletion is reflected without a manual refresh.
  useEffect(() => {
    const unsubscribe = subscribeToGeneratedPapers(
      (papers) => setGeneratedPapers(papers),
      () => setGeneratedPapers([]),
    );
    return unsubscribe;
  }, []);

  const openSavedPaper = useCallback(
    (saved: SavedGeneratedPaper) => {
      router.push({
        pathname: "/paper-preview",
        params: {
          paper: JSON.stringify(savedToGeneratedPaper(saved)),
          saved: "true",
        },
      });
    },
    [router],
  );

  const confirmDeleteSavedPaper = useCallback((saved: SavedGeneratedPaper) => {
    Alert.alert(
      "Delete paper",
      `Delete "${saved.paperName}"? This can't be undone.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: async () => {
            try {
              await deleteGeneratedPaper(saved.id);
              // The live listener removes the row; update optimistically too.
              setGeneratedPapers((prev) => prev.filter((p) => p.id !== saved.id));
            } catch {
              Alert.alert(
                "Couldn't delete",
                "We couldn't remove this paper. Please try again.",
              );
            }
          },
        },
      ],
    );
  }, []);

  // ── History ───────────────────────────────────────────────────────────────
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  // Real-time Firestore listener: the History list updates automatically when a
  // grading job is created ("processing") and again when it completes
  // ("complete"), with no manual refresh. Subscribe once on mount.
  useEffect(() => {
    setHistoryLoading(true);
    const unsubscribe = subscribeToHistory(
      (entries) => {
        setHistory(entries);
        setHistoryLoading(false);
      },
      () => setHistoryLoading(false),
    );
    return unsubscribe;
  }, []);

  // Pull-to-refresh — one-shot read as an offline fallback; the live listener
  // already keeps the list current.
  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      setHistory(await getHistory());
    } finally {
      setRefreshing(false);
    }
  }, []);

  const handleDelete = useCallback(async (entry: HistoryEntry) => {
    // Delete from Firestore (teachers/{uid}/markings) FIRST. Only remove the
    // row from local state if that succeeds — if it fails, keep the row and
    // tell the user, so the UI never drifts out of sync with Firestore.
    try {
      await deleteHistoryEntry(entry.id, entry.marking_id);
      setHistory((prev) => prev.filter((e) => e.id !== entry.id));
    } catch (err) {
      console.error("[index] handleDelete → delete failed", err);
      Alert.alert(
        "Couldn't delete",
        "We couldn't remove this result from your history. Please check your connection and try again.",
      );
    }
  }, []);

  // Sign out — the auth listener in _layout.tsx redirects to the sign-in screen.
  const handleSignOut = useCallback(async () => {
    try {
      await auth().signOut();
    } catch {
      // Ignore — signing out locally effectively always succeeds.
    }
  }, []);

  // Profile button in the header → confirm before signing out.
  const handleProfilePress = useCallback(() => {
    Alert.alert("Profile", "Sign out?", [
      { text: "Cancel", style: "cancel" },
      { text: "Sign out", style: "destructive", onPress: handleSignOut },
    ]);
  }, [handleSignOut]);

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <View style={styles.container}>
      {/* Blue header: wordmark + profile, with a segmented control beneath */}
      <View style={[styles.header, { paddingTop: insets.top + SPACING.sm }]}>
        <View style={styles.headerTop}>
          <View style={styles.brand}>
            <View style={styles.logoSquare}>
              <Text style={styles.logoLetter}>G</Text>
            </View>
            <Text style={styles.wordmark}>
              <Text style={styles.wordmarkLight}>Grade</Text>
              <Text style={styles.wordmarkBold}>AI</Text>
            </Text>
          </View>
          <TouchableOpacity
            onPress={handleProfilePress}
            style={styles.headerButton}
            hitSlop={8}
            activeOpacity={0.7}
          >
            <Text style={styles.headerIcon}>☰</Text>
          </TouchableOpacity>
        </View>

        <View style={styles.segment}>
          <TouchableOpacity
            style={[
              styles.segmentItem,
              activeTab === "papers" && styles.segmentItemActive,
            ]}
            onPress={() => setActiveTab("papers")}
            activeOpacity={0.8}
          >
            <Text
              style={[
                styles.segmentText,
                activeTab === "papers" && styles.segmentTextActive,
              ]}
            >
              Papers
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[
              styles.segmentItem,
              activeTab === "history" && styles.segmentItemActive,
            ]}
            onPress={() => setActiveTab("history")}
            activeOpacity={0.8}
          >
            <Text
              style={[
                styles.segmentText,
                activeTab === "history" && styles.segmentTextActive,
              ]}
            >
              History
            </Text>
          </TouchableOpacity>
        </View>
      </View>

      {/* ── Papers tab ── */}
      {activeTab === "papers" && (
        <>
          {papersLoading ? (
            <View style={styles.centered}>
              <ActivityIndicator size="large" color={COLORS.primary} />
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
          ) : (
            // The "Create Custom Paper" button is the primary teacher action and
            // does NOT depend on seeded past papers, so it is always rendered
            // first — even when the past-paper list is empty.
            <ScrollView contentContainerStyle={styles.listContent}>
              <TouchableOpacity
                style={styles.createPaperButton}
                onPress={() => router.push("/generate-paper")}
                activeOpacity={0.8}
              >
                <Text style={styles.createPaperButtonText}>+ Create Custom Paper</Text>
              </TouchableOpacity>

              {/* My Generated Papers — the teacher's own saved custom papers,
                  kept visually separate from the fixed reference papers below. */}
              {generatedPapers.length > 0 && (
                <View style={styles.generatedSection}>
                  <Text style={styles.sectionLabel}>My Generated Papers</Text>
                  {generatedPapers.map((gp) => (
                    <GeneratedPaperRow
                      key={gp.id}
                      paper={gp}
                      onPress={() => openSavedPaper(gp)}
                      onLongPress={() => confirmDeleteSavedPaper(gp)}
                    />
                  ))}
                </View>
              )}

              {papers.length === 0 ? (
                <View style={styles.emptyPapers}>
                  <Text style={styles.emptyTitle}>No past papers yet</Text>
                  <Text style={styles.emptySubtitle}>
                    Tap “Create Custom Paper” above to build a practice paper from
                    real IGCSE questions.
                  </Text>
                </View>
              ) : (
                <>
                  <Text style={styles.sectionLabel}>Select a paper to begin</Text>
                  {Object.entries(groupPapersBySubject(papers)).map(
                ([subjectName, subjectPapers], groupIndex) => (
                  <React.Fragment key={subjectName}>
                    {groupIndex > 0 && <View style={{ height: 24 }} />}
                    <Text style={styles.subjectHeader}>{subjectName}</Text>
                    {subjectPapers.map((item, paperIndex) => (
                      <React.Fragment key={String(item.id)}>
                        {paperIndex > 0 && <View style={{ height: 10 }} />}
                        <PaperCard
                          paper={item}
                          onPress={() =>
                            router.push({
                              pathname: "/paper/[id]",
                              params: {
                                id: String(item.id),
                                paperName: paperLabel(item),
                              },
                            })
                          }
                        />
                      </React.Fragment>
                    ))}
                  </React.Fragment>
                ),
                  )}
                </>
              )}
            </ScrollView>
          )}
        </>
      )}

      {/* ── History tab ── */}
      {activeTab === "history" &&
        // Show the centered loader only on first load. Subsequent reloads
        // show the list with a pull-to-refresh spinner instead.
        (historyLoading && history.length === 0 ? (
          <View style={styles.centered}>
            <ActivityIndicator size="large" color={COLORS.primary} />
            <Text style={styles.mutedText}>Loading history…</Text>
          </View>
        ) : (
          <FlatList
            data={history}
            keyExtractor={(item) => item.id}
            contentContainerStyle={
              history.length === 0
                ? styles.emptyListContent
                : styles.listContent
            }
            refreshing={refreshing}
            onRefresh={handleRefresh}
            ListHeaderComponent={
              history.length > 0 ? (
                <Text style={styles.sectionLabel}>
                  {history.length} session{history.length !== 1 ? "s" : ""} ·
                  swipe left to delete
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
                onDelete={() => handleDelete(item)}
                onPress={() =>
                  router.push({
                    pathname: "/results/paper",
                    params: {
                      resultData: JSON.stringify(item.result),
                      paperName: item.paper_name,
                      gradedAt: item.graded_at,
                      fromHistory: "true",
                      // Firestore doc id → lets the results PDF download verify
                      // ownership server-side.
                      markingId: item.marking_id ?? "",
                    },
                  })
                }
              />
            )}
          />
        ))}
    </View>
  );
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.surface,
  },
  centered: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    gap: SPACING.sm,
    padding: SPACING.xl,
  },

  // Blue header
  header: {
    backgroundColor: COLORS.primary,
    paddingHorizontal: SPACING.lg,
    paddingBottom: SPACING.md,
  },
  headerTop: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: SPACING.md,
  },
  brand: {
    flexDirection: "row",
    alignItems: "center",
    gap: SPACING.sm,
  },
  logoSquare: {
    width: 32,
    height: 32,
    borderRadius: 8,
    backgroundColor: COLORS.card,
    alignItems: "center",
    justifyContent: "center",
  },
  logoLetter: {
    color: COLORS.primary,
    fontSize: 18,
    fontWeight: "700",
  },
  wordmark: {
    fontSize: 20,
  },
  wordmarkLight: {
    color: COLORS.card,
    fontSize: 20,
    fontWeight: FONT.regular,
  },
  wordmarkBold: {
    color: COLORS.card,
    fontSize: 20,
    fontWeight: "600",
  },
  headerButton: {
    paddingHorizontal: SPACING.sm,
  },
  headerIcon: {
    color: COLORS.card,
    fontSize: 22,
  },

  // Segmented control (Papers / History)
  segment: {
    flexDirection: "row",
    backgroundColor: "rgba(255,255,255,0.2)",
    borderRadius: RADIUS.md,
    padding: 3,
  },
  segmentItem: {
    flex: 1,
    paddingVertical: SPACING.sm,
    alignItems: "center",
    borderRadius: 8,
  },
  segmentItemActive: {
    backgroundColor: COLORS.card,
  },
  segmentText: {
    fontSize: 14,
    fontWeight: FONT.medium,
    color: "rgba(255,255,255,0.7)",
  },
  segmentTextActive: {
    color: COLORS.primary,
  },

  // Shared list
  listContent: {
    paddingHorizontal: SPACING.lg,
    paddingTop: SPACING.md,
    paddingBottom: SPACING.xxl,
  },
  createPaperButton: {
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.lg,
    paddingVertical: SPACING.md,
    alignItems: "center",
    marginBottom: SPACING.lg,
  },
  createPaperButtonText: {
    color: COLORS.card,
    fontSize: 15,
    fontWeight: FONT.medium,
  },
  sectionLabel: {
    fontSize: 13,
    color: COLORS.textTertiary,
    marginBottom: SPACING.sm,
  },
  generatedSection: {
    marginBottom: SPACING.lg,
  },
  generatedRow: {
    backgroundColor: COLORS.card,
    borderWidth: 0.5,
    borderColor: COLORS.border,
    borderRadius: RADIUS.lg,
    paddingVertical: SPACING.md,
    paddingHorizontal: SPACING.lg,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 10,
  },
  generatedMain: {
    flex: 1,
  },
  generatedName: {
    fontSize: 15,
    fontWeight: FONT.medium,
    color: COLORS.textPrimary,
  },
  generatedMeta: {
    fontSize: 13,
    color: COLORS.textSecondary,
    marginTop: SPACING.xs,
  },
  generatedChevron: {
    fontSize: 24,
    color: COLORS.textTertiary,
    marginLeft: SPACING.sm,
  },
  subjectHeader: {
    fontSize: 11,
    fontWeight: FONT.medium,
    color: COLORS.textTertiary,
    letterSpacing: 0.8,
    textTransform: "uppercase",
    marginTop: SPACING.xl,
    marginBottom: SPACING.sm,
  },

  // States
  mutedText: {
    color: COLORS.textSecondary,
    fontSize: 15,
  },
  errorText: {
    fontSize: 17,
    fontWeight: FONT.medium,
    color: COLORS.fail,
  },
  errorDetail: {
    fontSize: 13,
    color: COLORS.textSecondary,
    textAlign: "center",
  },
  retryButton: {
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.md,
    paddingHorizontal: SPACING.xl,
    paddingVertical: SPACING.md,
    marginTop: SPACING.xs,
  },
  retryText: {
    color: COLORS.card,
    fontWeight: FONT.medium,
    fontSize: 15,
  },

  // Empty past-paper list (Create button stays above this)
  emptyPapers: {
    alignItems: "center",
    gap: SPACING.sm,
    paddingVertical: 64,
    paddingHorizontal: SPACING.lg,
  },

  // Empty history (FlatList content style + the empty component itself)
  emptyListContent: {
    flexGrow: 1,
    paddingHorizontal: SPACING.lg,
  },
  emptyHistory: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    gap: SPACING.sm,
    paddingVertical: 80,
  },
  emptyIcon: {
    fontSize: 40,
  },
  emptyTitle: {
    fontSize: 17,
    fontWeight: FONT.medium,
    color: COLORS.textPrimary,
  },
  emptySubtitle: {
    fontSize: 14,
    color: COLORS.textTertiary,
    textAlign: "center",
    lineHeight: 20,
  },

  // Swipe wrapper — overflow:hidden clips the row as it slides left.
  // Shadow lives here (not on the clipped row) so it renders on both platforms.
  swipeWrapper: {
    overflow: "hidden",
    borderRadius: RADIUS.lg,
    marginBottom: 10,
    shadowColor: "rgba(0,0,0,1)",
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.06,
    shadowRadius: 4,
    elevation: 2,
  },

  // Red delete button (sits behind the sliding row)
  deleteAction: {
    position: "absolute",
    right: 0,
    top: 0,
    bottom: 0,
    width: DELETE_WIDTH,
    backgroundColor: COLORS.fail,
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
    color: COLORS.card,
    fontSize: 14,
    fontWeight: FONT.medium,
  },

  // History row card (slides over the delete button)
  historyRow: {
    backgroundColor: COLORS.card,
    borderWidth: 0.5,
    borderColor: COLORS.border,
    borderRadius: RADIUS.lg,
    paddingVertical: SPACING.md,
    paddingHorizontal: SPACING.lg,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: SPACING.md,
  },
  historyMain: {
    flex: 1,
  },
  historyPaperName: {
    fontSize: 15,
    fontWeight: FONT.medium,
    color: COLORS.textPrimary,
  },
  historyDate: {
    fontSize: 13,
    color: COLORS.textSecondary,
    marginTop: SPACING.xs,
  },
  staleNote: {
    fontSize: 12,
    color: COLORS.warning,
    marginTop: SPACING.xs,
  },
  scoreBadge: {
    borderRadius: RADIUS.md,
    paddingHorizontal: 10,
    paddingVertical: 6,
    alignItems: "center",
    minWidth: 70,
  },
  // Status pills (queued / processing / failed)
  queuePill: {
    borderRadius: RADIUS.md,
    paddingHorizontal: 12,
    paddingVertical: 6,
    alignItems: "center",
    justifyContent: "center",
    minWidth: 70,
    backgroundColor: COLORS.border,
  },
  queuePillText: {
    fontSize: 12,
    fontWeight: FONT.medium,
    color: COLORS.textSecondary,
  },
  processingWrap: {
    alignItems: "flex-end",
    gap: 2,
    maxWidth: 130,
  },
  processingPill: {
    borderRadius: RADIUS.md,
    paddingHorizontal: 12,
    paddingVertical: 6,
    alignItems: "center",
    justifyContent: "center",
    minWidth: 70,
    backgroundColor: COLORS.primary,
  },
  processingPillText: {
    fontSize: 12,
    fontWeight: FONT.medium,
    color: COLORS.card,
  },
  progressStepText: {
    fontSize: 11,
    color: COLORS.textTertiary,
    textAlign: "right",
  },
  failPill: {
    borderRadius: RADIUS.md,
    paddingHorizontal: 12,
    paddingVertical: 6,
    alignItems: "center",
    justifyContent: "center",
    minWidth: 70,
    backgroundColor: COLORS.failLight,
  },
  failPillText: {
    fontSize: 12,
    fontWeight: FONT.medium,
    color: COLORS.fail,
  },
  scoreText: {
    fontSize: 13,
    fontWeight: FONT.medium,
  },
  scorePercent: {
    fontSize: 11,
    fontWeight: FONT.medium,
  },
});
