/**
 * app/generate-paper.tsx — Custom Paper Generator: the request form.
 *
 * The teacher picks topics (chip row with an "All" chip), a total mark target,
 * and a difficulty, then taps Generate. On success we navigate to
 * /generated-paper with the API response serialised as a route param.
 */

import React, { useEffect, useState } from "react";
import {
  View,
  Text,
  ScrollView,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  StyleSheet,
} from "react-native";
import { useRouter } from "expo-router";

import TopicChips from "../components/TopicChips";
import { getTopics, generatePaper } from "../services/api";
import type { GeneratorDifficulty } from "../types/paperGenerator";
import { COLORS, RADIUS, SPACING, FONT } from "../constants/theme";

const SUBJECT = "math";
const DIFFICULTIES: GeneratorDifficulty[] = ["mixed", "easy", "medium", "hard"];

export default function GeneratePaperScreen() {
  const router = useRouter();

  const [topics, setTopics] = useState<string[]>([]);
  const [selectedTopics, setSelectedTopics] = useState<string[]>([]);
  const [totalMarks, setTotalMarks] = useState("60");
  const [difficulty, setDifficulty] = useState<GeneratorDifficulty>("mixed");

  const [topicsLoading, setTopicsLoading] = useState(true);
  const [topicsError, setTopicsError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const loadTopics = async () => {
    setTopicsLoading(true);
    setTopicsError(null);
    try {
      const fetched = await getTopics(SUBJECT);
      setTopics(fetched);
      setSelectedTopics(fetched); // default: All selected
    } catch (err) {
      setTopicsError(err instanceof Error ? err.message : "Failed to load topics");
    } finally {
      setTopicsLoading(false);
    }
  };

  useEffect(() => {
    loadTopics();
  }, []);

  const onGenerate = async () => {
    setFormError(null);
    const marks = parseInt(totalMarks, 10);
    if (!Number.isFinite(marks) || marks <= 0) {
      setFormError("Enter a total mark greater than 0.");
      return;
    }
    if (selectedTopics.length === 0) {
      setFormError("Select at least one topic.");
      return;
    }

    setGenerating(true);
    try {
      const paper = await generatePaper({
        subject: SUBJECT,
        topics: selectedTopics, // resolved topic strings, never "all"
        totalMarks: marks,
        difficulty,
      });
      // The selector returns an empty paper when nothing fits the request (e.g.
      // the mark target is below the smallest available question, or the chosen
      // topics/difficulty have no non-diagram questions). Surface that here
      // instead of navigating into a "0 / 0" paper that can't be marked.
      if (paper.questions.length === 0) {
        setFormError(
          "No questions match these settings. Try selecting more topics, a different difficulty, or a higher mark total."
        );
        return;
      }
      router.push({
        pathname: "/generated-paper",
        params: { paper: JSON.stringify(paper) },
      });
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to generate paper.");
    } finally {
      setGenerating(false);
    }
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.label}>Subject</Text>
      <View style={styles.subjectBox}>
        <Text style={styles.subjectText}>Mathematics (0580)</Text>
      </View>

      <Text style={styles.label}>Total marks</Text>
      <TextInput
        style={styles.input}
        value={totalMarks}
        onChangeText={(t) => setTotalMarks(t.replace(/[^0-9]/g, ""))}
        keyboardType="number-pad"
        placeholder="e.g. 60"
        placeholderTextColor={COLORS.textTertiary}
        maxLength={3}
      />

      <Text style={styles.label}>Difficulty</Text>
      <View style={styles.segmentRow}>
        {DIFFICULTIES.map((d) => {
          const active = difficulty === d;
          return (
            <TouchableOpacity
              key={d}
              style={[styles.segment, active ? styles.segmentActive : styles.segmentInactive]}
              onPress={() => setDifficulty(d)}
              activeOpacity={0.8}
            >
              <Text style={[styles.segmentText, active ? styles.segmentTextActive : styles.segmentTextInactive]}>
                {d[0].toUpperCase() + d.slice(1)}
              </Text>
            </TouchableOpacity>
          );
        })}
      </View>

      <Text style={styles.label}>Topics</Text>
      {topicsLoading ? (
        <ActivityIndicator color={COLORS.primary} style={styles.topicsLoading} />
      ) : topicsError ? (
        <View>
          <Text style={styles.errorText}>{topicsError}</Text>
          <TouchableOpacity style={styles.retryButton} onPress={loadTopics} activeOpacity={0.8}>
            <Text style={styles.retryText}>Retry</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <TopicChips topics={topics} selected={selectedTopics} onChange={setSelectedTopics} />
      )}

      {formError ? <Text style={styles.errorText}>{formError}</Text> : null}

      <TouchableOpacity
        style={[styles.generateButton, generating && styles.buttonDisabled]}
        onPress={onGenerate}
        disabled={generating}
        activeOpacity={0.8}
      >
        {generating ? (
          <ActivityIndicator color={COLORS.card} />
        ) : (
          <Text style={styles.generateButtonText}>Generate Paper</Text>
        )}
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
    paddingBottom: SPACING.xxl,
  },
  label: {
    fontSize: 14,
    fontWeight: FONT.medium,
    color: COLORS.textSecondary,
    marginTop: SPACING.lg,
    marginBottom: SPACING.sm,
  },
  subjectBox: {
    backgroundColor: COLORS.card,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    borderColor: COLORS.border,
    padding: SPACING.md,
  },
  subjectText: {
    fontSize: 16,
    color: COLORS.textPrimary,
    fontWeight: FONT.medium,
  },
  input: {
    backgroundColor: COLORS.card,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    borderColor: COLORS.border,
    padding: SPACING.md,
    fontSize: 16,
    color: COLORS.textPrimary,
  },
  segmentRow: {
    flexDirection: "row",
    gap: SPACING.sm,
  },
  segment: {
    flex: 1,
    paddingVertical: SPACING.md,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    alignItems: "center",
  },
  segmentActive: {
    backgroundColor: COLORS.primary,
    borderColor: COLORS.primary,
  },
  segmentInactive: {
    backgroundColor: COLORS.card,
    borderColor: COLORS.border,
  },
  segmentText: {
    fontSize: 13,
    fontWeight: FONT.medium,
  },
  segmentTextActive: {
    color: COLORS.card,
  },
  segmentTextInactive: {
    color: COLORS.textSecondary,
  },
  topicsLoading: {
    alignSelf: "flex-start",
  },
  generateButton: {
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.lg,
    paddingVertical: SPACING.lg,
    alignItems: "center",
    marginTop: SPACING.xl,
  },
  generateButtonText: {
    color: COLORS.card,
    fontSize: 16,
    fontWeight: FONT.medium,
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  errorText: {
    color: COLORS.fail,
    fontSize: 14,
    marginTop: SPACING.md,
  },
  retryButton: {
    alignSelf: "flex-start",
    marginTop: SPACING.sm,
    paddingHorizontal: SPACING.md,
    paddingVertical: SPACING.sm,
    borderRadius: RADIUS.md,
    backgroundColor: COLORS.primaryLight,
  },
  retryText: {
    color: COLORS.primary,
    fontWeight: FONT.medium,
  },
});
