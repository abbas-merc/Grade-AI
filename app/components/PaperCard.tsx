/**
 * components/PaperCard.tsx — Tappable card for one exam paper.
 */

import React from "react";
import { View, Text, TouchableOpacity, StyleSheet } from "react-native";
import type { Paper } from "../types";
import { COLORS, RADIUS, SPACING, FONT, ON } from "../constants/theme";

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
    backgroundColor: COLORS.card,
    borderWidth: 0.5,
    borderColor: COLORS.border,
    borderRadius: RADIUS.lg,
    paddingVertical: 14,
    paddingHorizontal: SPACING.lg,
    shadowColor: "rgba(0,0,0,1)",
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.06,
    shadowRadius: 4,
    elevation: 2,
  },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  code: {
    fontSize: 15,
    fontWeight: FONT.medium,
    color: COLORS.textPrimary,
  },
  tierBadge: {
    backgroundColor: ON.extendedBg,
    borderRadius: RADIUS.sm,
    paddingHorizontal: 10,
    paddingVertical: SPACING.xs,
  },
  tierText: {
    color: ON.extendedText,
    fontSize: 12,
    fontWeight: FONT.medium,
  },
  session: {
    fontSize: 13,
    color: COLORS.textSecondary,
    marginTop: SPACING.xs,
  },
  footer: {
    marginTop: SPACING.xs,
  },
  marks: {
    fontSize: 13,
    color: COLORS.textSecondary,
  },
});
