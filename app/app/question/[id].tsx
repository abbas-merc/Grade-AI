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
        <ActivityIndicator size="large" color="#4F46E5" />
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
  loadingText: {
    color: "#6B7280",
    fontSize: 15,
  },
  errorText: {
    fontSize: 18,
    fontWeight: "600",
    color: "#EF4444",
  },
  errorDetail: {
    fontSize: 14,
    color: "#6B7280",
    textAlign: "center",
  },
  retryButton: {
    backgroundColor: "#4F46E5",
    borderRadius: 10,
    paddingHorizontal: 24,
    paddingVertical: 12,
    marginTop: 4,
  },
  retryButtonText: {
    color: "#fff",
    fontWeight: "600",
    fontSize: 15,
  },

  questionCard: {
    backgroundColor: "#fff",
    borderRadius: 12,
    padding: 16,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.07,
    shadowRadius: 4,
    elevation: 2,
    gap: 10,
  },
  questionLabel: {
    fontSize: 12,
    fontWeight: "700",
    color: "#4F46E5",
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  questionText: {
    fontSize: 16,
    color: "#1F2937",
    lineHeight: 26,
  },
  marksRow: {
    flexDirection: "row",
  },
  marksBadge: {
    backgroundColor: "#EEF2FF",
    borderRadius: 6,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  marksText: {
    color: "#4F46E5",
    fontSize: 13,
    fontWeight: "600",
  },

  previewContainer: {
    gap: 8,
  },
  previewLabel: {
    fontSize: 13,
    fontWeight: "600",
    color: "#6B7280",
  },
  preview: {
    width: "100%",
    height: 240,
    borderRadius: 12,
    backgroundColor: "#E5E7EB",
  },

  instructions: {
    backgroundColor: "#F0FDF4",
    borderRadius: 10,
    padding: 14,
    borderLeftWidth: 3,
    borderLeftColor: "#059669",
  },
  instructionText: {
    fontSize: 14,
    color: "#065F46",
    lineHeight: 20,
  },

  gradeButton: {
    backgroundColor: "#4F46E5",
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: "center",
    shadowColor: "#4F46E5",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 4,
  },
  gradeButtonText: {
    color: "#fff",
    fontSize: 16,
    fontWeight: "700",
  },

  libraryButton: {
    backgroundColor: "#F3F4F6",
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
  },
  libraryButtonText: {
    color: "#374151",
    fontSize: 15,
    fontWeight: "600",
  },
});
