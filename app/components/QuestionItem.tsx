/**
 * components/QuestionItem.tsx — Tappable row for one question in a paper.
 */

import React from "react";
import { View, Text, TouchableOpacity, StyleSheet } from "react-native";
import type { Question } from "../types";

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
    backgroundColor: "#fff",
    borderRadius: 10,
    padding: 14,
    gap: 12,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.06,
    shadowRadius: 3,
    elevation: 1,
  },
  numberBadge: {
    width: 40,
    height: 40,
    borderRadius: 8,
    backgroundColor: "#EEF2FF",
    justifyContent: "center",
    alignItems: "center",
  },
  numberText: {
    fontSize: 14,
    fontWeight: "700",
    color: "#4F46E5",
  },
  preview: {
    flex: 1,
    fontSize: 14,
    color: "#374151",
    lineHeight: 19,
  },
  marksBadge: {
    backgroundColor: "#F3F4F6",
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
  marksText: {
    fontSize: 12,
    fontWeight: "600",
    color: "#6B7280",
  },
});
