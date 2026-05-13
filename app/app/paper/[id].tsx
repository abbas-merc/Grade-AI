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
  FlatList,
  ActivityIndicator,
  TouchableOpacity,
  StyleSheet,
} from "react-native";
import { useLocalSearchParams, useRouter, useNavigation } from "expo-router";

import { getQuestions } from "../../services/api";
import type { Question } from "../../types";

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
      <Text style={styles.questionText}>{question.question_text}</Text>
    </View>
  );
}

export default function PaperScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
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
        <ActivityIndicator size="large" color="#4F46E5" />
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
            router.push({ pathname: "/capture/[paperId]", params: { paperId: id } })
          }
          activeOpacity={0.85}
        >
          <Text style={styles.gradeButtonText}>Grade My Paper</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#F9FAFB",
  },
  centered: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    gap: 10,
    padding: 24,
  },
  loadingText: {
    color: "#6B7280",
    fontSize: 15,
  },
  errorText: {
    fontSize: 17,
    fontWeight: "600",
    color: "#EF4444",
  },
  errorDetail: {
    fontSize: 14,
    color: "#6B7280",
    textAlign: "center",
  },
  emptyText: {
    color: "#9CA3AF",
    fontSize: 15,
  },
  retryButton: {
    backgroundColor: "#4F46E5",
    borderRadius: 10,
    paddingHorizontal: 24,
    paddingVertical: 12,
    marginTop: 8,
  },
  retryButtonText: {
    color: "#fff",
    fontWeight: "600",
    fontSize: 15,
  },
  flatList: {
    flex: 1,
  },
  list: {
    paddingHorizontal: 16,
    paddingTop: 12,
    paddingBottom: 8,
    gap: 10,
  },
  card: {
    backgroundColor: "#fff",
    borderRadius: 10,
    padding: 14,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.06,
    shadowRadius: 3,
    elevation: 1,
    gap: 8,
  },
  cardHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  numberBadge: {
    backgroundColor: "#EEF2FF",
    borderRadius: 6,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  numberText: {
    fontSize: 13,
    fontWeight: "700",
    color: "#4F46E5",
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
  questionText: {
    fontSize: 14,
    color: "#374151",
    lineHeight: 20,
  },
  footer: {
    padding: 16,
    paddingBottom: 32,
    backgroundColor: "#F9FAFB",
    borderTopWidth: 1,
    borderTopColor: "#E5E7EB",
  },
  gradeButton: {
    backgroundColor: "#4F46E5",
    borderRadius: 14,
    paddingVertical: 18,
    alignItems: "center",
    shadowColor: "#4F46E5",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 4,
  },
  gradeButtonText: {
    color: "#fff",
    fontSize: 17,
    fontWeight: "700",
    letterSpacing: 0.3,
  },
});
