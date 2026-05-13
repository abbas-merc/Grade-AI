/**
 * components/GradeResult.tsx — Displays the full AI grading result.
 *
 * Shows: score, per-point mark breakdown with awarded/not-awarded icons,
 * and the feedback paragraph generated for the student.
 */

import React from "react";
import { View, Text, ScrollView, StyleSheet } from "react-native";
import type { GradingResult, MarkBreakdownPoint } from "../types";

interface Props {
  result: GradingResult;
}

export default function GradeResult({ result }: Props) {
  const percentage = result.marks_available > 0
    ? Math.round((result.marks_awarded / result.marks_available) * 100)
    : 0;

  return (
    <View style={styles.container}>
      {/* Score hero */}
      <View style={[styles.scoreCard, scoreCardColor(percentage)]}>
        <Text style={styles.scoreLabel}>Your Score</Text>
        <Text style={styles.scoreValue}>
          {result.marks_awarded} / {result.marks_available}
        </Text>
        <Text style={styles.scorePercent}>{percentage}%</Text>
      </View>

      {/* Mark breakdown */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Mark Breakdown</Text>
        {result.mark_breakdown.map((point: MarkBreakdownPoint) => (
          <View key={point.point_number} style={styles.pointRow}>
            <Text style={[styles.icon, point.awarded ? styles.iconAwarded : styles.iconMissed]}>
              {point.awarded ? "✅" : "❌"}
            </Text>
            <View style={styles.pointBody}>
              <Text style={styles.criterion}>{point.criterion}</Text>
              <Text style={styles.reason}>{point.reason}</Text>
            </View>
          </View>
        ))}
      </View>

      {/* Feedback */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Feedback</Text>
        <Text style={styles.feedbackText}>{result.feedback}</Text>
      </View>
    </View>
  );
}

function scoreCardColor(percentage: number): { backgroundColor: string } {
  if (percentage >= 80) return { backgroundColor: "#059669" };
  if (percentage >= 50) return { backgroundColor: "#4F46E5" };
  return { backgroundColor: "#DC2626" };
}

const styles = StyleSheet.create({
  container: {
    gap: 16,
  },
  scoreCard: {
    borderRadius: 16,
    padding: 24,
    alignItems: "center",
    gap: 4,
  },
  scoreLabel: {
    fontSize: 13,
    fontWeight: "600",
    color: "rgba(255,255,255,0.8)",
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  scoreValue: {
    fontSize: 52,
    fontWeight: "800",
    color: "#fff",
    lineHeight: 60,
  },
  scorePercent: {
    fontSize: 18,
    fontWeight: "600",
    color: "rgba(255,255,255,0.85)",
  },
  section: {
    backgroundColor: "#fff",
    borderRadius: 12,
    padding: 16,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.06,
    shadowRadius: 4,
    elevation: 2,
    gap: 10,
  },
  sectionTitle: {
    fontSize: 15,
    fontWeight: "700",
    color: "#1F2937",
    marginBottom: 4,
  },
  pointRow: {
    flexDirection: "row",
    gap: 10,
    paddingVertical: 8,
    borderTopWidth: 1,
    borderTopColor: "#F3F4F6",
  },
  icon: {
    fontSize: 18,
    lineHeight: 24,
    width: 28,
    textAlign: "center",
  },
  iconAwarded: {
    // colour baked into emoji
  },
  iconMissed: {
    // colour baked into emoji
  },
  pointBody: {
    flex: 1,
  },
  criterion: {
    fontSize: 14,
    fontWeight: "600",
    color: "#1F2937",
  },
  reason: {
    fontSize: 13,
    color: "#6B7280",
    marginTop: 2,
    lineHeight: 18,
  },
  feedbackText: {
    fontSize: 14,
    color: "#374151",
    lineHeight: 22,
  },
});
