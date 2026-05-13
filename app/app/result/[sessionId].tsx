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
      {/* Score headline */}
      <View style={styles.headline}>
        <Text style={styles.headlineLabel}>Result</Text>
        <Text style={styles.headlineScore}>
          {result.marks_awarded} / {result.marks_available} marks
        </Text>
      </View>

      {/* Detailed breakdown + feedback */}
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
    backgroundColor: "#F9FAFB",
  },
  content: {
    padding: 16,
    gap: 16,
    paddingBottom: 40,
  },
  centered: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    gap: 12,
    padding: 24,
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
  headline: {
    backgroundColor: "#fff",
    borderRadius: 12,
    padding: 16,
    alignItems: "center",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.06,
    shadowRadius: 4,
    elevation: 2,
  },
  headlineLabel: {
    fontSize: 12,
    fontWeight: "600",
    color: "#9CA3AF",
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  headlineScore: {
    fontSize: 32,
    fontWeight: "800",
    color: "#1F2937",
    marginTop: 4,
  },
  homeButton: {
    backgroundColor: "#1F2937",
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: "center",
    marginTop: 4,
  },
  homeButtonText: {
    color: "#fff",
    fontSize: 16,
    fontWeight: "700",
  },
});
