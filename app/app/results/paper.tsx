/**
 * app/results/paper.tsx — Full-paper grading results screen.
 *
 * Fresh results: saves to history when the user taps "Back to Papers".
 * History replay (fromHistory="true"): shows the result but never re-saves.
 */

import React, { useMemo, useCallback, useRef, useState } from "react";
import {
  View,
  Text,
  FlatList,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  StyleSheet,
} from "react-native";
import { useLocalSearchParams, useRouter, useNavigation, useFocusEffect } from "expo-router";
import * as FileSystem from "expo-file-system/legacy";
import * as Sharing from "expo-sharing";
import type {
  PaperGradingResult,
  QuestionResult,
  PaperMarkBreakdownPoint,
  HistoryEntry,
} from "../../types";
import { saveHistoryEntry } from "../../services/historyService";
import { downloadResultsPdf } from "../../services/api";
import { COLORS, RADIUS, SPACING, FONT, ON } from "../../constants/theme";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function MarkPoint({ point }: { point: PaperMarkBreakdownPoint }) {
  return (
    <View style={styles.markPoint}>
      <View style={point.awarded ? styles.tickCircle : styles.crossCircle}>
        <Text style={point.awarded ? styles.tickIcon : styles.crossIcon}>
          {point.awarded ? "✓" : "✕"}
        </Text>
      </View>
      <View style={styles.markPointBody}>
        <Text style={styles.markCriterion}>{point.criterion}</Text>
        <Text style={styles.markReason}>{point.reason}</Text>
      </View>
    </View>
  );
}

function QuestionCard({ item }: { item: QuestionResult }) {
  return (
    <View style={styles.questionCard}>
      <View style={styles.questionHeader}>
        <View style={styles.qNumRow}>
          <View style={styles.qNumBadge}>
            <Text style={styles.qNumText}>Q{item.question_number}</Text>
          </View>
          {/* Subtle "check reading" hint: the model flagged the transcription of
              this answer as uncertain. It does not change the marks — it just
              tells the teacher to verify the reading manually. */}
          {item.low_confidence && (
            <View style={styles.lowConfBadge}>
              <Text style={styles.lowConfText}>⚠ Check reading</Text>
            </View>
          )}
        </View>
        <Text style={styles.questionScore}>
          {item.marks_awarded} / {item.marks_available}
        </Text>
      </View>

      <Text style={styles.questionText}>{item.question_text}</Text>

      {item.has_illegible && (
        <View style={styles.illegibleNote}>
          <Text style={styles.illegibleNoteText}>
            ⚠️  Some handwriting in this answer could not be read (marked
            [illegible] below). Please check this question manually.
          </Text>
        </View>
      )}

      {item.extracted_answer ? (
        <View style={styles.answerBox}>
          <Text style={styles.answerLabel}>Your answer</Text>
          <Text style={styles.answerText}>{item.extracted_answer}</Text>
        </View>
      ) : (
        <View style={styles.noAnswerBox}>
          <Text style={styles.noAnswerText}>No answer found on submitted pages</Text>
        </View>
      )}

      {item.mark_breakdown.length > 0 && (
        <View style={styles.breakdown}>
          {item.mark_breakdown.map((point, idx) => (
            <MarkPoint key={idx} point={point} />
          ))}
        </View>
      )}

      {item.feedback ? (
        <View style={styles.feedbackBox}>
          <Text style={styles.feedbackText}>{item.feedback}</Text>
        </View>
      ) : null}
    </View>
  );
}

export default function PaperResultsScreen() {
  const { resultData, paperName, gradedAt, fromHistory, markingId } =
    useLocalSearchParams<{
      resultData: string;
      paperName?: string;
      gradedAt?: string;
      fromHistory?: string;
      // Firestore marking doc id, passed from History so the download endpoint
      // can verify ownership server-side. Absent for legacy entries.
      markingId?: string;
    }>();
  const router = useRouter();
  const navigation = useNavigation();
  // Guard against double-save if the button is tapped twice quickly
  const hasSaved = useRef(false);
  const [downloading, setDownloading] = useState(false);

  const result: PaperGradingResult | null = useMemo(() => {
    if (!resultData) return null;
    try {
      return JSON.parse(resultData) as PaperGradingResult;
    } catch {
      return null;
    }
  }, [resultData]);

  // Set the Stack header title to the paper name
  useFocusEffect(
    useCallback(() => {
      if (paperName) {
        navigation.setOptions({ title: paperName });
      }
    }, [paperName, navigation])
  );

  // Called when the user explicitly taps "Done".
  // This is the single save point — intentional, never automatic.
  const handleDone = useCallback(async () => {
    if (fromHistory !== "true" && result && !hasSaved.current) {
      hasSaved.current = true;
      const name = paperName || `Paper ${result.paper_id}`;
      const pct =
        result.total_marks_available > 0
          ? Math.round(
              (result.total_marks_awarded / result.total_marks_available) * 100
            )
          : 0;
      const entry: HistoryEntry = {
        id: Date.now().toString(),
        paper_id: result.paper_id,
        paper_name: name,
        graded_at: new Date().toISOString(),
        total_marks_awarded: result.total_marks_awarded,
        total_marks_available: result.total_marks_available,
        percentage: pct,
        result,
        // Firestore doc ID from the backend, so this entry can be deleted from
        // teachers/{uid}/markings later. May be undefined if the save failed.
        marking_id: result.marking_id,
      };
      try {
        await saveHistoryEntry(entry);
      } catch (err) {
        // AsyncStorage failure is non-fatal for navigation, but no longer silent —
        // surface it so we can actually see write failures in Metro logs.
        console.error("[results/paper] handleDone → saveHistoryEntry threw", err);
      }
    }
    // Reset the navigation stack: clear the entire grading flow (capture,
    // breakdown, etc.) so Back can't return to any of it, and land on the
    // History tab.
    if (router.canDismiss()) {
      router.dismissAll();
    }
    router.replace({ pathname: "/", params: { tab: "history" } });
  }, [result, paperName, fromHistory, router]);

  // Fetch the shareable "Marked Results" PDF from the backend, write it to the
  // cache, and hand it to the OS share sheet — the same pattern the paper/mark
  // scheme downloads use.
  const handleDownload = useCallback(async () => {
    if (!result || downloading) return;
    setDownloading(true);
    try {
      const base64 = await downloadResultsPdf({
        resultId: markingId || result.marking_id,
        result,
        paperName,
        gradedAt,
      });
      const safe =
        (paperName || "results")
          .replace(/[^A-Za-z0-9]+/g, "_")
          .replace(/^_+|_+$/g, "") || "results";
      const fileUri = `${FileSystem.cacheDirectory}results_${safe}.pdf`;
      await FileSystem.writeAsStringAsync(fileUri, base64, {
        encoding: FileSystem.EncodingType.Base64,
      });
      if (await Sharing.isAvailableAsync()) {
        await Sharing.shareAsync(fileUri, {
          mimeType: "application/pdf",
          UTI: "com.adobe.pdf",
          dialogTitle: "Marked Results",
        });
      } else {
        Alert.alert("Saved", `Results PDF saved to:\n${fileUri}`);
      }
    } catch (err) {
      Alert.alert(
        "Download failed",
        err instanceof Error ? err.message : "Could not download the results PDF."
      );
    } finally {
      setDownloading(false);
    }
  }, [result, downloading, markingId, paperName, gradedAt]);

  if (!result) {
    return (
      <View style={styles.centered}>
        <Text style={styles.errorTitle}>Results unavailable</Text>
        <Text style={styles.errorDetail}>
          The grading result could not be loaded.
        </Text>
        <TouchableOpacity style={styles.backButton} onPress={() => router.push("/")}>
          <Text style={styles.backButtonText}>Back to Papers</Text>
        </TouchableOpacity>
      </View>
    );
  }

  const percentage =
    result.total_marks_available > 0
      ? Math.round(
          (result.total_marks_awarded / result.total_marks_available) * 100
        )
      : 0;

  const displayDate =
    fromHistory === "true" && gradedAt ? formatDate(gradedAt) : null;

  return (
    <FlatList
      data={result.results}
      keyExtractor={(item) => item.question_number}
      contentContainerStyle={styles.listContent}
      ListHeaderComponent={
        <>
          <View style={styles.summaryCard}>
            <Text style={styles.summaryLabel}>Total Score</Text>
            <Text style={styles.summaryScore}>
              {result.total_marks_awarded} / {result.total_marks_available}
            </Text>
            <Text style={styles.summaryPercent}>{percentage}%</Text>
            {displayDate && (
              <Text style={styles.summaryDate}>Graded {displayDate}</Text>
            )}
          </View>

          {result.marks_total_mismatch && (
            <View style={styles.capWarning}>
              <Text style={styles.capWarningText}>
                ⚠️  Heads up — the marks for this paper don't add up to its
                official total, so an individual question's total may be off.
                Your answers were still graded; double-check any question that
                looks wrong.
              </Text>
            </View>
          )}

          <Text style={styles.sectionHeader}>Question Breakdown</Text>
        </>
      }
      renderItem={({ item }) => <QuestionCard item={item} />}
      ListFooterComponent={
        <View style={styles.footer}>
          <TouchableOpacity
            style={[styles.downloadButton, downloading && styles.buttonDisabled]}
            onPress={handleDownload}
            disabled={downloading}
            activeOpacity={0.85}
          >
            {downloading ? (
              <ActivityIndicator color={COLORS.primary} />
            ) : (
              <Text style={styles.downloadButtonText}>Download Results</Text>
            )}
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.doneButton}
            onPress={handleDone}
            activeOpacity={0.85}
          >
            <Text style={styles.backButtonText}>Done</Text>
          </TouchableOpacity>
        </View>
      }
      ItemSeparatorComponent={() => <View style={styles.separator} />}
    />
  );
}

const styles = StyleSheet.create({
  listContent: {
    padding: SPACING.lg,
    paddingBottom: 40,
    backgroundColor: COLORS.surface,
  },
  centered: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    gap: SPACING.md,
    padding: SPACING.xl,
    backgroundColor: COLORS.surface,
  },
  errorTitle: {
    fontSize: 20,
    fontWeight: FONT.medium,
    color: COLORS.fail,
  },
  errorDetail: {
    fontSize: 14,
    color: COLORS.textSecondary,
    textAlign: "center",
  },

  // Summary
  summaryCard: {
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.lg,
    padding: SPACING.xl,
    alignItems: "center",
    marginBottom: SPACING.md,
  },
  summaryLabel: {
    fontSize: 11,
    fontWeight: FONT.medium,
    color: "rgba(255,255,255,0.6)",
    textTransform: "uppercase",
    letterSpacing: 0.8,
    marginBottom: SPACING.sm,
  },
  summaryScore: {
    fontSize: 36,
    fontWeight: FONT.medium,
    color: COLORS.card,
  },
  summaryPercent: {
    fontSize: 18,
    color: "rgba(255,255,255,0.85)",
    marginTop: SPACING.xs,
  },
  summaryDate: {
    fontSize: 12,
    color: "rgba(255,255,255,0.5)",
    marginTop: SPACING.sm,
  },

  // Cap warning
  capWarning: {
    backgroundColor: COLORS.warningLight,
    borderRadius: RADIUS.md,
    padding: SPACING.md,
    marginBottom: SPACING.md,
    borderLeftWidth: 3,
    borderLeftColor: COLORS.warning,
  },
  capWarningText: {
    fontSize: 13,
    color: ON.warningText,
    lineHeight: 18,
  },

  sectionHeader: {
    fontSize: 16,
    fontWeight: FONT.medium,
    color: COLORS.textPrimary,
    marginBottom: SPACING.sm,
    marginTop: SPACING.xs,
  },

  // Question card
  questionCard: {
    backgroundColor: COLORS.card,
    borderWidth: 0.5,
    borderColor: COLORS.border,
    borderRadius: RADIUS.lg,
    padding: SPACING.lg,
    gap: SPACING.md,
  },
  questionHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  qNumRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: SPACING.sm,
    flexShrink: 1,
  },
  qNumBadge: {
    backgroundColor: COLORS.primaryLight,
    borderRadius: RADIUS.sm,
    paddingHorizontal: 10,
    paddingVertical: SPACING.xs,
  },
  qNumText: {
    fontSize: 12,
    fontWeight: FONT.medium,
    color: ON.primaryText,
  },
  lowConfBadge: {
    backgroundColor: COLORS.warningLight,
    borderRadius: RADIUS.sm,
    paddingHorizontal: 8,
    paddingVertical: SPACING.xs,
  },
  lowConfText: {
    fontSize: 11,
    fontWeight: FONT.medium,
    color: ON.warningText,
  },
  questionScore: {
    fontSize: 13,
    fontWeight: FONT.medium,
    color: COLORS.textSecondary,
  },
  questionText: {
    fontSize: 14,
    color: COLORS.textPrimary,
    lineHeight: 20,
  },
  illegibleNote: {
    backgroundColor: COLORS.warningLight,
    borderRadius: RADIUS.md,
    padding: 10,
    borderLeftWidth: 3,
    borderLeftColor: COLORS.warning,
  },
  illegibleNoteText: {
    fontSize: 13,
    color: ON.warningText,
    lineHeight: 18,
  },
  answerBox: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md,
    padding: 10,
    gap: SPACING.xs,
    borderLeftWidth: 3,
    borderLeftColor: COLORS.border,
  },
  answerLabel: {
    fontSize: 11,
    fontWeight: FONT.medium,
    color: COLORS.textTertiary,
    textTransform: "uppercase",
    letterSpacing: 0.4,
  },
  answerText: {
    fontSize: 13,
    color: COLORS.textSecondary,
    lineHeight: 19,
  },
  noAnswerBox: {
    backgroundColor: COLORS.failLight,
    borderRadius: RADIUS.md,
    padding: 10,
  },
  noAnswerText: {
    fontSize: 13,
    color: COLORS.fail,
    fontStyle: "italic",
  },
  breakdown: {
    gap: SPACING.sm,
  },
  markPoint: {
    flexDirection: "row",
    gap: SPACING.sm,
    paddingTop: SPACING.sm,
    borderTopWidth: 0.5,
    borderTopColor: COLORS.border,
  },
  tickCircle: {
    width: 20,
    height: 20,
    borderRadius: 10,
    backgroundColor: COLORS.passLight,
    alignItems: "center",
    justifyContent: "center",
  },
  crossCircle: {
    width: 20,
    height: 20,
    borderRadius: 10,
    backgroundColor: COLORS.failLight,
    alignItems: "center",
    justifyContent: "center",
  },
  tickIcon: {
    color: COLORS.pass,
    fontSize: 11,
    fontWeight: FONT.medium,
  },
  crossIcon: {
    color: COLORS.fail,
    fontSize: 11,
    fontWeight: FONT.medium,
  },
  markPointBody: {
    flex: 1,
  },
  markCriterion: {
    fontSize: 13,
    fontWeight: FONT.medium,
    color: COLORS.textPrimary,
  },
  markReason: {
    fontSize: 12,
    color: COLORS.textSecondary,
    marginTop: SPACING.xs,
    lineHeight: 17,
  },
  feedbackBox: {
    backgroundColor: COLORS.primaryLight,
    borderLeftWidth: 3,
    borderLeftColor: COLORS.primary,
    borderTopRightRadius: 8,
    borderBottomRightRadius: 8,
    paddingVertical: 10,
    paddingHorizontal: 14,
  },
  feedbackText: {
    fontSize: 13,
    color: ON.primaryText,
    lineHeight: 20,
  },
  separator: {
    height: SPACING.md,
  },
  // Footer action stack: outlined "Download Results" (secondary) above the
  // filled "Done" (primary) so both are clearly visible without competing.
  footer: {
    marginTop: SPACING.xl,
    gap: SPACING.md,
  },
  downloadButton: {
    backgroundColor: COLORS.card,
    borderRadius: RADIUS.lg,
    borderWidth: 1.5,
    borderColor: COLORS.primary,
    paddingVertical: SPACING.lg,
    alignItems: "center",
  },
  downloadButtonText: {
    color: COLORS.primary,
    fontSize: 15,
    fontWeight: FONT.medium,
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  doneButton: {
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.lg,
    paddingVertical: SPACING.lg,
    alignItems: "center",
  },
  // Used by the error-state button and the footer "Done" button.
  backButton: {
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.lg,
    paddingVertical: SPACING.lg,
    alignItems: "center",
    marginTop: SPACING.xl,
  },
  backButtonText: {
    color: COLORS.card,
    fontSize: 15,
    fontWeight: FONT.medium,
  },
});
