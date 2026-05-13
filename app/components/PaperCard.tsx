/**
 * components/PaperCard.tsx — Tappable card for one exam paper.
 */

import React from "react";
import { View, Text, TouchableOpacity, StyleSheet } from "react-native";
import type { Paper } from "../types";

interface Props {
  paper: Paper;
  onPress: () => void;
}

export default function PaperCard({ paper, onPress }: Props) {
  return (
    <TouchableOpacity style={styles.card} onPress={onPress} activeOpacity={0.75}>
      <View style={styles.header}>
        <Text style={styles.code}>
          {paper.subject_code} / Paper {paper.paper_number}
        </Text>
        <View style={styles.tierBadge}>
          <Text style={styles.tierText}>{paper.tier}</Text>
        </View>
      </View>

      <Text style={styles.session}>
        {paper.session} {paper.year}
      </Text>

      <View style={styles.footer}>
        <Text style={styles.marks}>{paper.total_marks} marks total</Text>
      </View>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: "#fff",
    borderRadius: 12,
    padding: 16,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.07,
    shadowRadius: 4,
    elevation: 2,
  },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  code: {
    fontSize: 18,
    fontWeight: "700",
    color: "#1F2937",
  },
  tierBadge: {
    backgroundColor: "#EEF2FF",
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  tierText: {
    color: "#4F46E5",
    fontSize: 12,
    fontWeight: "600",
  },
  session: {
    fontSize: 14,
    color: "#6B7280",
    marginTop: 6,
  },
  footer: {
    marginTop: 12,
  },
  marks: {
    fontSize: 13,
    color: "#9CA3AF",
  },
});
