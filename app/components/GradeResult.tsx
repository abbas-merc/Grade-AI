/**
 * components/GradeResult.tsx — Displays the full AI grading result.
 *
 * Shows: score, per-point mark breakdown with awarded/not-awarded badges,
 * and the feedback paragraph generated for the student.
 */

import React from "react";
import { View, Text, StyleSheet } from "react-native";
import type { GradingResult, MarkBreakdownPoint } from "../types";
import { COLORS, RADIUS, SPACING, FONT, ON } from "../constants/theme";

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
      <View style={styles.scoreCard}>
        <Text style={styles.scoreLabel}>Total Score</Text>
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
            <View style={point.awarded ? styles.tickCircle : styles.crossCircle}>
              <Text style={point.awarded ? styles.tickIcon : styles.crossIcon}>
                {point.awarded ? "✓" : "✕"}
              </Text>
            </View>
            <View style={styles.pointBody}>
              <Text style={styles.criterion}>{point.criterion}</Text>
              <Text style={styles.reason}>{point.reason}</Text>
            </View>
          </View>
        ))}
      </View>

      {/* Feedback */}
      <View style={styles.feedbackBox}>
        <Text style={styles.feedbackTitle}>Feedback</Text>
        <Text style={styles.feedbackText}>{result.feedback}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    gap: SPACING.lg,
  },
  scoreCard: {
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.lg,
    padding: SPACING.xl,
    alignItems: "center",
    gap: SPACING.xs,
  },
  scoreLabel: {
    fontSize: 11,
    fontWeight: FONT.medium,
    color: "rgba(255,255,255,0.6)",
    textTransform: "uppercase",
    letterSpacing: 0.8,
  },
  scoreValue: {
    fontSize: 36,
    fontWeight: FONT.medium,
    color: COLORS.card,
  },
  scorePercent: {
    fontSize: 18,
    color: "rgba(255,255,255,0.85)",
    marginTop: SPACING.xs,
  },
  section: {
    backgroundColor: COLORS.card,
    borderWidth: 0.5,
    borderColor: COLORS.border,
    borderRadius: RADIUS.lg,
    padding: SPACING.lg,
    gap: SPACING.sm,
  },
  sectionTitle: {
    fontSize: 15,
    fontWeight: FONT.medium,
    color: COLORS.textPrimary,
    marginBottom: SPACING.xs,
  },
  pointRow: {
    flexDirection: "row",
    gap: SPACING.md,
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
  pointBody: {
    flex: 1,
  },
  criterion: {
    fontSize: 13,
    fontWeight: FONT.medium,
    color: COLORS.textPrimary,
  },
  reason: {
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
    gap: SPACING.xs,
  },
  feedbackTitle: {
    fontSize: 13,
    fontWeight: FONT.medium,
    color: ON.primaryText,
  },
  feedbackText: {
    fontSize: 13,
    color: ON.primaryText,
    lineHeight: 20,
  },
});
