/**
 * app/results/paper.tsx — Full-paper grading results screen.
 *
 * Displays:
 *  - Summary card: total score and grading cost
 *  - Cost-cap warning banner if the cap was hit mid-paper
 *  - FlatList of per-question result cards (not ScrollView+map for performance)
 *  - Back to Papers button
 */

import React, { useMemo } from "react";
import {
  View,
  Text,
  FlatList,
  TouchableOpacity,
  StyleSheet,
} from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import type { PaperGradingResult, QuestionResult, PaperMarkBreakdownPoint } from "../../types";

function MarkPoint({ point }: { point: PaperMarkBreakdownPoint }) {
  return (
    <View style={styles.markPoint}>
      <Text style={point.awarded ? styles.checkMark : styles.crossMark}>
        {point.awarded ? "✅" : "❌"}
      </Text>
      <View style={styles.markPointBody}>
        <Text style={styles.markCriterion}>{point.criterion}</Text>
        <Text style={styles.markReason}>{point.reason}</Text>
      </View>
    </View>
  );
}

function QuestionCard({ item }: { item: QuestionResult }) {
  const percentage =
    item.marks_available > 0
      ? Math.round((item.marks_awarded / item.marks_available) * 100)
      : 0;

  const scoreColor =
    percentage >= 80 ? "#059669" : percentage >= 50 ? "#4F46E5" : "#DC2626";

  return (
    <View style={styles.questionCard}>
      {/* Header row */}
      <View style={styles.questionHeader}>
        <View style={styles.qNumBadge}>
          <Text style={styles.qNumText}>Q{item.question_number}</Text>
        </View>
        <Text style={[styles.questionScore, { color: scoreColor }]}>
          {item.marks_awarded} / {item.marks_available}
        </Text>
      </View>

      {/* Question text */}
      <Text style={styles.questionText}>{item.question_text}</Text>

      {/* Extracted answer */}
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

      {/* Mark breakdown */}
      {item.mark_breakdown.length > 0 && (
        <View style={styles.breakdown}>
          {item.mark_breakdown.map((point, idx) => (
            <MarkPoint key={idx} point={point} />
          ))}
        </View>
      )}

      {/* Feedback */}
      {item.feedback ? (
        <View style={styles.feedbackBox}>
          <Text style={styles.feedbackText}>{item.feedback}</Text>
        </View>
      ) : null}
    </View>
  );
}

export default function PaperResultsScreen() {
  const { resultData } = useLocalSearchParams<{ resultData: string }>();
  const router = useRouter();

  const result: PaperGradingResult | null = useMemo(() => {
    if (!resultData) return null;
    try {
      return JSON.parse(resultData) as PaperGradingResult;
    } catch {
      return null;
    }
  }, [resultData]);

  if (!result) {
    return (
      <View style={styles.centered}>
        <Text style={styles.errorTitle}>Results unavailable</Text>
        <Text style={styles.errorDetail}>
          The grading result could not be loaded.
        </Text>
        <TouchableOpacity
          style={styles.backButton}
          onPress={() => router.push("/")}
        >
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

  const summaryBg =
    percentage >= 80 ? "#059669" : percentage >= 50 ? "#4F46E5" : "#DC2626";

  return (
    <FlatList
      data={result.results}
      keyExtractor={(item) => item.question_number}
      contentContainerStyle={styles.listContent}
      ListHeaderComponent={
        <>
          {/* Summary card */}
          <View style={[styles.summaryCard, { backgroundColor: summaryBg }]}>
            <Text style={styles.summaryLabel}>Total Score</Text>
            <Text style={styles.summaryScore}>
              {result.total_marks_awarded} / {result.total_marks_available}
            </Text>
            <Text style={styles.summaryPercent}>{percentage}%</Text>
            <Text style={styles.summaryCost}>
              Grading cost: ${result.cost_usd.toFixed(4)}
            </Text>
          </View>

          {/* Cost cap warning */}
          {result.cost_cap_reached && (
            <View style={styles.capWarning}>
              <Text style={styles.capWarningText}>
                ⚠️  Grading stopped early — the $0.50 cost cap was reached.
                Some questions may show 0 marks.
              </Text>
            </View>
          )}

          <Text style={styles.sectionHeader}>Question Breakdown</Text>
        </>
      }
      renderItem={({ item }) => <QuestionCard item={item} />}
      ListFooterComponent={
        <TouchableOpacity
          style={styles.backButton}
          onPress={() => router.push("/")}
          activeOpacity={0.85}
        >
          <Text style={styles.backButtonText}>Back to Papers</Text>
        </TouchableOpacity>
      }
      ItemSeparatorComponent={() => <View style={styles.separator} />}
    />
  );
}

const styles = StyleSheet.create({
  listContent: {
    padding: 16,
    paddingBottom: 40,
    backgroundColor: "#F9FAFB",
    gap: 0,
  },
  centered: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    gap: 12,
    padding: 24,
    backgroundColor: "#F9FAFB",
  },
  errorTitle: {
    fontSize: 20,
    fontWeight: "700",
    color: "#EF4444",
  },
  errorDetail: {
    fontSize: 14,
    color: "#6B7280",
    textAlign: "center",
  },

  // Summary
  summaryCard: {
    borderRadius: 16,
    padding: 24,
    alignItems: "center",
    gap: 4,
    marginBottom: 12,
  },
  summaryLabel: {
    fontSize: 13,
    fontWeight: "600",
    color: "rgba(255,255,255,0.8)",
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  summaryScore: {
    fontSize: 52,
    fontWeight: "800",
    color: "#fff",
    lineHeight: 60,
  },
  summaryPercent: {
    fontSize: 18,
    fontWeight: "600",
    color: "rgba(255,255,255,0.85)",
  },
  summaryCost: {
    fontSize: 12,
    color: "rgba(255,255,255,0.65)",
    marginTop: 4,
  },

  // Cap warning
  capWarning: {
    backgroundColor: "#FEF3C7",
    borderRadius: 10,
    padding: 12,
    marginBottom: 12,
    borderLeftWidth: 3,
    borderLeftColor: "#F59E0B",
  },
  capWarningText: {
    fontSize: 13,
    color: "#92400E",
    lineHeight: 18,
  },

  sectionHeader: {
    fontSize: 16,
    fontWeight: "700",
    color: "#1F2937",
    marginBottom: 10,
    marginTop: 4,
  },

  // Question card
  questionCard: {
    backgroundColor: "#fff",
    borderRadius: 12,
    padding: 14,
    gap: 10,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.06,
    shadowRadius: 3,
    elevation: 1,
  },
  questionHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  qNumBadge: {
    backgroundColor: "#EEF2FF",
    borderRadius: 6,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  qNumText: {
    fontSize: 13,
    fontWeight: "700",
    color: "#4F46E5",
  },
  questionScore: {
    fontSize: 16,
    fontWeight: "700",
  },
  questionText: {
    fontSize: 14,
    color: "#1F2937",
    lineHeight: 20,
  },

  // Answer box
  answerBox: {
    backgroundColor: "#F9FAFB",
    borderRadius: 8,
    padding: 10,
    gap: 4,
    borderLeftWidth: 3,
    borderLeftColor: "#D1D5DB",
  },
  answerLabel: {
    fontSize: 11,
    fontWeight: "600",
    color: "#9CA3AF",
    textTransform: "uppercase",
    letterSpacing: 0.4,
  },
  answerText: {
    fontSize: 13,
    color: "#374151",
    lineHeight: 19,
  },
  noAnswerBox: {
    backgroundColor: "#FEF2F2",
    borderRadius: 8,
    padding: 10,
  },
  noAnswerText: {
    fontSize: 13,
    color: "#DC2626",
    fontStyle: "italic",
  },

  // Mark breakdown
  breakdown: {
    gap: 6,
  },
  markPoint: {
    flexDirection: "row",
    gap: 8,
    paddingTop: 6,
    borderTopWidth: 1,
    borderTopColor: "#F3F4F6",
  },
  checkMark: {
    fontSize: 16,
    lineHeight: 22,
    width: 24,
    textAlign: "center",
  },
  crossMark: {
    fontSize: 16,
    lineHeight: 22,
    width: 24,
    textAlign: "center",
  },
  markPointBody: {
    flex: 1,
  },
  markCriterion: {
    fontSize: 13,
    fontWeight: "600",
    color: "#1F2937",
  },
  markReason: {
    fontSize: 12,
    color: "#6B7280",
    marginTop: 1,
    lineHeight: 17,
  },

  // Feedback
  feedbackBox: {
    backgroundColor: "#F0FDF4",
    borderRadius: 8,
    padding: 10,
    borderLeftWidth: 3,
    borderLeftColor: "#059669",
  },
  feedbackText: {
    fontSize: 13,
    color: "#065F46",
    lineHeight: 19,
  },

  // Separator + footer
  separator: {
    height: 10,
  },
  backButton: {
    backgroundColor: "#1F2937",
    borderRadius: 14,
    paddingVertical: 18,
    alignItems: "center",
    marginTop: 16,
  },
  backButtonText: {
    color: "#fff",
    fontSize: 16,
    fontWeight: "700",
  },
});
