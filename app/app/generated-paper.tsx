/**
 * app/generated-paper.tsx — Landing screen after a paper is generated.
 *
 * Shows a summary card (total marks + number of questions) and a single
 * "Preview Paper" button that opens the full PaperPreviewScreen. The question
 * list and per-document downloads live on the preview screen, not here.
 */

import React, { useMemo } from "react";
import { View, Text, TouchableOpacity, StyleSheet } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";

import type { GeneratedPaper } from "../types/paperGenerator";
import { COLORS, RADIUS, SPACING, FONT } from "../constants/theme";

export default function GeneratedPaperScreen() {
  const { paper: paperParam } = useLocalSearchParams<{ paper: string }>();
  const router = useRouter();

  const paper: GeneratedPaper | null = useMemo(() => {
    if (!paperParam) return null;
    try {
      return JSON.parse(paperParam) as GeneratedPaper;
    } catch {
      return null;
    }
  }, [paperParam]);

  if (!paper) {
    return (
      <View style={styles.centered}>
        <Text style={styles.errorTitle}>Paper unavailable</Text>
        <TouchableOpacity style={styles.previewButton} onPress={() => router.replace("/generate-paper")}>
          <Text style={styles.previewButtonText}>Back to Generator</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Your paper is ready</Text>
        <View style={styles.statsRow}>
          <View style={styles.stat}>
            <Text style={styles.statValue}>{paper.totalMarks}</Text>
            <Text style={styles.statLabel}>Total Marks</Text>
          </View>
          <View style={styles.statDivider} />
          <View style={styles.stat}>
            <Text style={styles.statValue}>{paper.numQuestions}</Text>
            <Text style={styles.statLabel}>Questions</Text>
          </View>
        </View>
      </View>

      <TouchableOpacity
        style={styles.previewButton}
        onPress={() =>
          router.push({
            pathname: "/paper-preview",
            params: { paper: JSON.stringify(paper) },
          })
        }
        activeOpacity={0.8}
      >
        <Text style={styles.previewButtonText}>Preview Paper</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.surface,
    padding: SPACING.lg,
  },
  centered: {
    flex: 1,
    backgroundColor: COLORS.surface,
    justifyContent: "center",
    alignItems: "center",
    padding: SPACING.lg,
  },
  card: {
    backgroundColor: COLORS.card,
    borderRadius: RADIUS.xl,
    padding: SPACING.xl,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  cardTitle: {
    fontSize: 18,
    fontWeight: FONT.medium,
    color: COLORS.textPrimary,
    marginBottom: SPACING.lg,
  },
  statsRow: {
    flexDirection: "row",
    alignItems: "center",
  },
  stat: {
    flex: 1,
    alignItems: "center",
  },
  statDivider: {
    width: 1,
    height: 40,
    backgroundColor: COLORS.border,
  },
  statValue: {
    fontSize: 32,
    fontWeight: FONT.medium,
    color: COLORS.primary,
  },
  statLabel: {
    fontSize: 13,
    color: COLORS.textSecondary,
    marginTop: SPACING.xs,
  },
  errorTitle: {
    fontSize: 18,
    fontWeight: FONT.medium,
    color: COLORS.textPrimary,
    marginBottom: SPACING.lg,
  },
  previewButton: {
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.lg,
    paddingVertical: SPACING.lg,
    alignItems: "center",
    marginTop: SPACING.xl,
  },
  previewButtonText: {
    color: COLORS.card,
    fontSize: 16,
    fontWeight: FONT.medium,
  },
});
