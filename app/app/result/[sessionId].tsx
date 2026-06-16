/**
 * app/result/[sessionId].tsx — Grading result screen.
 *
 * Reads the GradingResult passed as a serialised param from the question
 * screen. No polling — the result is already complete when we arrive here.
 */

import React, { useMemo } from "react";
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  StyleSheet,
} from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";

import GradeResult from "../../components/GradeResult";
import type { GradingResult } from "../../types";
import { COLORS, RADIUS, SPACING, FONT } from "../../constants/theme";

export default function ResultScreen() {
  const { resultData } = useLocalSearchParams<{ resultData: string }>();
  const router = useRouter();

  const result: GradingResult | null = useMemo(() => {
    if (!resultData) return null;
    try {
      return JSON.parse(resultData) as GradingResult;
    } catch {
      return null;
    }
  }, [resultData]);

  if (!result) {
    return (
      <View style={styles.centered}>
        <Text style={styles.errorTitle}>Result unavailable</Text>
        <Text style={styles.errorDetail}>
          The grading result could not be loaded.
        </Text>
        <TouchableOpacity style={styles.homeButton} onPress={() => router.push("/")}>
          <Text style={styles.homeButtonText}>Back to Home</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      {/* Score hero + detailed breakdown + feedback */}
      <GradeResult result={result} />

      {/* Navigation */}
      <TouchableOpacity
        style={styles.homeButton}
        onPress={() => router.push("/")}
        activeOpacity={0.8}
      >
        <Text style={styles.homeButtonText}>Try Another Question</Text>
      </TouchableOpacity>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.surface,
  },
  content: {
    padding: SPACING.lg,
    gap: SPACING.lg,
    paddingBottom: 40,
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
  homeButton: {
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.lg,
    paddingVertical: SPACING.lg,
    alignItems: "center",
    marginTop: SPACING.xs,
  },
  homeButtonText: {
    color: COLORS.card,
    fontSize: 15,
    fontWeight: FONT.medium,
  },
});
