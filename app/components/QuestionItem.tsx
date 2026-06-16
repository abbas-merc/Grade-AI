/**
 * components/QuestionItem.tsx — Tappable row for one question in a paper.
 */

import React from "react";
import { View, Text, TouchableOpacity, StyleSheet } from "react-native";
import type { Question } from "../types";
import { COLORS, RADIUS, SPACING, FONT, ON } from "../constants/theme";

interface Props {
  question: Question;
  onPress: () => void;
}

export default function QuestionItem({ question, onPress }: Props) {
  return (
    <TouchableOpacity style={styles.row} onPress={onPress} activeOpacity={0.75}>
      <View style={styles.numberBadge}>
        <Text style={styles.numberText}>Q{question.question_number}</Text>
      </View>

      <Text style={styles.preview} numberOfLines={2}>
        {question.question_text}
      </Text>

      <View style={styles.marksBadge}>
        <Text style={styles.marksText}>{question.marks_available}m</Text>
      </View>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: COLORS.card,
    borderWidth: 0.5,
    borderColor: COLORS.border,
    borderRadius: RADIUS.lg,
    paddingVertical: SPACING.md,
    paddingHorizontal: SPACING.lg,
    gap: SPACING.md,
    marginBottom: SPACING.sm,
  },
  numberBadge: {
    backgroundColor: COLORS.primaryLight,
    borderRadius: RADIUS.sm,
    paddingHorizontal: 10,
    paddingVertical: SPACING.xs,
  },
  numberText: {
    fontSize: 12,
    fontWeight: FONT.medium,
    color: ON.primaryText,
  },
  preview: {
    flex: 1,
    fontSize: 13,
    color: COLORS.textSecondary,
    lineHeight: 19,
  },
  marksBadge: {
    backgroundColor: COLORS.primaryLight,
    borderRadius: RADIUS.sm,
    paddingHorizontal: 10,
    paddingVertical: SPACING.xs,
  },
  marksText: {
    fontSize: 12,
    fontWeight: FONT.medium,
    color: ON.primaryText,
  },
});
