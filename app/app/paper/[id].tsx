/**
 * app/paper/[id].tsx — Question list for a selected paper.
 *
 * Shows all questions with their number, text, and marks.
 * The "Grade My Paper" button at the bottom navigates to the
 * multi-page capture screen.
 */

import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  Image,
  FlatList,
  ActivityIndicator,
  TouchableOpacity,
  StyleSheet,
} from "react-native";
import { useLocalSearchParams, useRouter, useNavigation } from "expo-router";

import { getQuestions } from "../../services/api";
import type { Question } from "../../types";
import { COLORS, RADIUS, SPACING, FONT, ON } from "../../constants/theme";
import { BASE_URL } from "../../constants/config";

/** Render a question's snippet image at the card width, preserving aspect ratio.
 *  question_image_url is host-agnostic, so we prepend BASE_URL. */
function QuestionImage({ imageUrl }: { imageUrl: string }) {
  const uri = `${BASE_URL}${imageUrl}`;
  const [aspect, setAspect] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    Image.getSize(
      uri,
      (w, h) => {
        if (alive && h > 0) setAspect(w / h);
      },
      () => {
        if (alive) setFailed(true);
      }
    );
    return () => {
      alive = false;
    };
  }, [uri]);

  if (failed) return null;

  return (
    <Image
      source={{ uri }}
      resizeMode="contain"
      style={[styles.questionImage, aspect ? { aspectRatio: aspect } : { height: 200 }]}
    />
  );
}

function QuestionCard({ question }: { question: Question }) {
  return (
    <View style={styles.card}>
      <View style={styles.cardHeader}>
        <View style={styles.numberBadge}>
          <Text style={styles.numberText}>Q{question.question_number}</Text>
        </View>
        <View style={styles.marksBadge}>
          <Text style={styles.marksText}>
            {question.marks_available}m
          </Text>
        </View>
      </View>
      {question.question_image_url ? (
        <QuestionImage imageUrl={question.question_image_url} />
      ) : (
        <Text style={styles.questionText}>{question.question_text}</Text>
      )}
    </View>
  );
}

export default function PaperScreen() {
  const { id, paperName } = useLocalSearchParams<{ id: string; paperName?: string }>();
  const router = useRouter();
  const navigation = useNavigation();

  const [questions, setQuestions] = useState<Question[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    const paperId = Number(id);
    setLoading(true);
    setError(null);
    navigation.setOptions({ title: `Paper ${id}` });

    getQuestions(paperId)
      .then((qs) => {
        setQuestions(qs);
        navigation.setOptions({
          title: `Paper ${id} — ${qs.length} Questions`,
        });
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [id, navigation]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" color={COLORS.primary} />
        <Text style={styles.loadingText}>Loading questions…</Text>
      </View>
    );
  }

  if (error) {
    return (
      <View style={styles.centered}>
        <Text style={styles.errorText}>Failed to load questions.</Text>
        <Text style={styles.errorDetail}>{error}</Text>
        <TouchableOpacity style={styles.retryButton} onPress={load} activeOpacity={0.85}>
          <Text style={styles.retryButtonText}>Retry</Text>
        </TouchableOpacity>
      </View>
    );
  }

  if (questions.length === 0) {
    return (
      <View style={styles.centered}>
        <Text style={styles.emptyText}>No questions found for this paper.</Text>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <FlatList
        style={styles.flatList}
        data={questions}
        keyExtractor={(item) => String(item.id)}
        contentContainerStyle={styles.list}
        renderItem={({ item }) => <QuestionCard question={item} />}
      />
      <View style={styles.footer}>
        <TouchableOpacity
          style={styles.gradeButton}
          onPress={() =>
            router.push({ pathname: "/capture/[paperId]", params: { paperId: id, paperName: paperName ?? "" } })
          }
          activeOpacity={0.85}
        >
          <Text style={styles.gradeButtonText}>Start Scanning</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.surface,
  },
  centered: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    gap: SPACING.sm,
    padding: SPACING.xl,
    backgroundColor: COLORS.surface,
  },
  loadingText: {
    color: COLORS.textSecondary,
    fontSize: 15,
  },
  errorText: {
    fontSize: 17,
    fontWeight: FONT.medium,
    color: COLORS.fail,
  },
  errorDetail: {
    fontSize: 14,
    color: COLORS.textSecondary,
    textAlign: "center",
  },
  emptyText: {
    color: COLORS.textTertiary,
    fontSize: 15,
  },
  retryButton: {
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.md,
    paddingHorizontal: SPACING.xl,
    paddingVertical: SPACING.md,
    marginTop: SPACING.sm,
  },
  retryButtonText: {
    color: COLORS.card,
    fontWeight: FONT.medium,
    fontSize: 15,
  },
  flatList: {
    flex: 1,
  },
  list: {
    paddingHorizontal: SPACING.lg,
    paddingTop: SPACING.md,
    paddingBottom: SPACING.sm,
    gap: SPACING.sm,
  },
  card: {
    backgroundColor: COLORS.card,
    borderWidth: 0.5,
    borderColor: COLORS.border,
    borderRadius: RADIUS.lg,
    paddingVertical: SPACING.md,
    paddingHorizontal: SPACING.lg,
    gap: SPACING.sm,
  },
  cardHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
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
  questionText: {
    fontSize: 13,
    color: COLORS.textSecondary,
    lineHeight: 20,
    marginTop: SPACING.xs,
  },
  questionImage: {
    width: "100%",
    marginTop: SPACING.sm,
    borderRadius: RADIUS.md,
    backgroundColor: "#FFFFFF",
  },
  footer: {
    padding: SPACING.lg,
    paddingBottom: SPACING.xxl,
    backgroundColor: COLORS.surface,
    borderTopWidth: 0.5,
    borderTopColor: COLORS.border,
  },
  gradeButton: {
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.lg,
    paddingVertical: SPACING.lg,
    alignItems: "center",
  },
  gradeButtonText: {
    color: COLORS.card,
    fontSize: 15,
    fontWeight: FONT.medium,
  },
});
