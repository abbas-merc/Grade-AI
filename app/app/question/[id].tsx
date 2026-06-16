/**
 * app/question/[id].tsx — Question detail + photo capture screen.
 *
 * Flow:
 *  1. Load and display the question text + marks available.
 *  2. Student taps "Grade My Answer" → camera opens (base64, quality 0.7).
 *  3. Photo taken → LoadingOverlay shown → gradeAnswer() called.
 *  4. Success → navigate to /result/[sessionId] with result as params.
 *  5. Error → Alert with message, student can retry.
 */

import React, { useEffect, useState, useCallback } from "react";
import {
  View,
  Text,
  TouchableOpacity,
  ScrollView,
  Image,
  Alert,
  ActivityIndicator,
  StyleSheet,
} from "react-native";
import { useLocalSearchParams, useRouter, useNavigation } from "expo-router";
import * as ImagePicker from "expo-image-picker";

import { getQuestion, gradeAnswer } from "../../services/api";
import LoadingOverlay from "../../components/LoadingOverlay";
import type { Question } from "../../types";
import { COLORS, RADIUS, SPACING, FONT, ON } from "../../constants/theme";

export default function QuestionScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const navigation = useNavigation();

  const [question, setQuestion] = useState<Question | null>(null);
  const [loadingQuestion, setLoadingQuestion] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [imageUri, setImageUri] = useState<string | null>(null);
  const [grading, setGrading] = useState(false);

  const loadQuestion = useCallback(() => {
    setLoadingQuestion(true);
    setLoadError(null);
    getQuestion(Number(id))
      .then((q) => {
        setQuestion(q);
        navigation.setOptions({
          title: `Q${q.question_number} — ${q.marks_available} mark${q.marks_available !== 1 ? "s" : ""}`,
        });
      })
      .catch((err: Error) => setLoadError(err.message))
      .finally(() => setLoadingQuestion(false));
  }, [id, navigation]);

  useEffect(() => {
    loadQuestion();
  }, [loadQuestion]);

  const handleGradeMyAnswer = useCallback(async () => {
    if (!question) return;

    // Request camera permission
    const { status } = await ImagePicker.requestCameraPermissionsAsync();
    if (status !== "granted") {
      Alert.alert(
        "Camera permission required",
        "Please allow camera access in Settings so you can photograph your answer."
      );
      return;
    }

    // Open camera — request base64 so we can send directly to the API
    const result = await ImagePicker.launchCameraAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      base64: true,
      quality: 0.7,
    });

    if (result.canceled) return;

    const asset = result.assets[0];
    const base64 = asset.base64;

    if (!base64) {
      Alert.alert("Photo error", "Could not read the photo. Please try again.");
      return;
    }

    // Keep preview visible while grading
    setImageUri(asset.uri);
    setGrading(true);

    try {
      const gradingResult = await gradeAnswer(question.id, base64);

      router.push({
        pathname: "/result/[sessionId]",
        params: { sessionId: String(gradingResult.session_id), resultData: JSON.stringify(gradingResult) },
      });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Grading failed. Please try again.";
      Alert.alert("Grading failed", message, [{ text: "OK" }]);
    } finally {
      setGrading(false);
    }
  }, [question, router]);

  const handlePickFromLibrary = useCallback(async () => {
    if (!question) return;

    const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (status !== "granted") {
      Alert.alert("Permission required", "Please allow photo library access in Settings.");
      return;
    }

    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      base64: true,
      quality: 0.7,
    });

    if (result.canceled) return;

    const asset = result.assets[0];
    const base64 = asset.base64;

    if (!base64) {
      Alert.alert("Photo error", "Could not read the photo. Please try again.");
      return;
    }

    setImageUri(asset.uri);
    setGrading(true);

    try {
      const gradingResult = await gradeAnswer(question.id, base64);

      router.push({
        pathname: "/result/[sessionId]",
        params: { sessionId: String(gradingResult.session_id), resultData: JSON.stringify(gradingResult) },
      });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Grading failed. Please try again.";
      Alert.alert("Grading failed", message);
    } finally {
      setGrading(false);
    }
  }, [question, router]);

  if (loadingQuestion) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" color={COLORS.primary} />
        <Text style={styles.loadingText}>Loading question…</Text>
      </View>
    );
  }

  if (loadError || !question) {
    return (
      <View style={styles.centered}>
        <Text style={styles.errorText}>Failed to load question.</Text>
        <Text style={styles.errorDetail}>
          {loadError ?? "Question not found."}
        </Text>
        <TouchableOpacity
          style={styles.retryButton}
          onPress={loadQuestion}
          activeOpacity={0.85}
        >
          <Text style={styles.retryButtonText}>Retry</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <>
      <ScrollView style={styles.container} contentContainerStyle={styles.content}>
        {/* Question card */}
        <View style={styles.questionCard}>
          <Text style={styles.questionLabel}>
            Question {question.question_number}
          </Text>
          <Text style={styles.questionText}>{question.question_text}</Text>
          <View style={styles.marksRow}>
            <View style={styles.marksBadge}>
              <Text style={styles.marksText}>
                {question.marks_available} mark{question.marks_available !== 1 ? "s" : ""} available
              </Text>
            </View>
          </View>
        </View>

        {/* Photo preview (shown after capture) */}
        {imageUri && !grading && (
          <View style={styles.previewContainer}>
            <Text style={styles.previewLabel}>Your photo</Text>
            <Image
              source={{ uri: imageUri }}
              style={styles.preview}
              resizeMode="contain"
            />
          </View>
        )}

        {/* Instructions */}
        {!imageUri && (
          <View style={styles.instructions}>
            <Text style={styles.instructionText}>
              Write your answer on paper, then tap the button below to photograph it. The AI will grade it instantly.
            </Text>
          </View>
        )}

        {/* Primary action */}
        <TouchableOpacity
          style={styles.gradeButton}
          onPress={handleGradeMyAnswer}
          disabled={grading}
          activeOpacity={0.8}
        >
          <Text style={styles.gradeButtonText}>
            {imageUri ? "Retake & Grade Again" : "Grade My Answer"}
          </Text>
        </TouchableOpacity>

        {/* Secondary: pick from library */}
        <TouchableOpacity
          style={styles.libraryButton}
          onPress={handlePickFromLibrary}
          disabled={grading}
          activeOpacity={0.8}
        >
          <Text style={styles.libraryButtonText}>Choose from Photo Library</Text>
        </TouchableOpacity>
      </ScrollView>

      <LoadingOverlay visible={grading} message="Grading your answer…" />
    </>
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
  },
  loadingText: {
    color: COLORS.textSecondary,
    fontSize: 15,
  },
  errorText: {
    fontSize: 18,
    fontWeight: FONT.medium,
    color: COLORS.fail,
  },
  errorDetail: {
    fontSize: 14,
    color: COLORS.textSecondary,
    textAlign: "center",
  },
  retryButton: {
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.md,
    paddingHorizontal: SPACING.xl,
    paddingVertical: SPACING.md,
    marginTop: SPACING.xs,
  },
  retryButtonText: {
    color: COLORS.card,
    fontWeight: FONT.medium,
    fontSize: 15,
  },

  questionCard: {
    backgroundColor: COLORS.card,
    borderWidth: 0.5,
    borderColor: COLORS.border,
    borderRadius: RADIUS.lg,
    padding: SPACING.lg,
    gap: SPACING.sm,
  },
  questionLabel: {
    fontSize: 12,
    fontWeight: FONT.medium,
    color: COLORS.primary,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  questionText: {
    fontSize: 16,
    color: COLORS.textPrimary,
    lineHeight: 26,
  },
  marksRow: {
    flexDirection: "row",
  },
  marksBadge: {
    backgroundColor: COLORS.primaryLight,
    borderRadius: RADIUS.sm,
    paddingHorizontal: 10,
    paddingVertical: SPACING.xs,
  },
  marksText: {
    color: ON.primaryText,
    fontSize: 13,
    fontWeight: FONT.medium,
  },

  previewContainer: {
    gap: SPACING.sm,
  },
  previewLabel: {
    fontSize: 13,
    fontWeight: FONT.medium,
    color: COLORS.textSecondary,
  },
  preview: {
    width: "100%",
    height: 240,
    borderRadius: RADIUS.lg,
    backgroundColor: COLORS.border,
  },

  instructions: {
    backgroundColor: COLORS.primaryLight,
    borderRadius: RADIUS.md,
    padding: 14,
    borderLeftWidth: 3,
    borderLeftColor: COLORS.primary,
  },
  instructionText: {
    fontSize: 14,
    color: ON.primaryText,
    lineHeight: 20,
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

  libraryButton: {
    backgroundColor: COLORS.surface,
    borderWidth: 0.5,
    borderColor: COLORS.border,
    borderRadius: RADIUS.lg,
    paddingVertical: 14,
    alignItems: "center",
  },
  libraryButtonText: {
    color: COLORS.textSecondary,
    fontSize: 15,
    fontWeight: FONT.medium,
  },
});
