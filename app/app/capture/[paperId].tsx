/**
 * app/capture/[paperId].tsx — Multi-page answer booklet capture screen.
 *
 * Flow:
 *  1. Student photographs each page of their answer booklet one at a time.
 *  2. Captured pages appear as thumbnails with a remove button.
 *  3. Student taps "Submit for Grading" — loading overlay appears with
 *     cycling status messages while the API call runs.
 *  4. On success → navigate to /results/paper with the full result.
 *  5. On failure → alert with message, student can retry.
 */

import React, { useState, useCallback, useEffect } from "react";
import {
  View,
  Text,
  TouchableOpacity,
  FlatList,
  Image,
  Alert,
  StyleSheet,
  Modal,
  ActivityIndicator,
} from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import * as ImageManipulator from "expo-image-manipulator";

import { gradePaper } from "../../services/api";
import type { PaperGradingResult } from "../../types";

const MSG_UPLOAD = "Uploading pages…";
const MSG_EXTRACT = "Reading your handwriting…";
const MSG_GRADE = "Grading every question…";

interface CapturedPage {
  uri: string;
  base64: string;
}

export default function CaptureScreen() {
  const { paperId } = useLocalSearchParams<{ paperId: string }>();
  const router = useRouter();

  const [pages, setPages] = useState<CapturedPage[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState(MSG_UPLOAD);

  // Timed state machine — advances the loading message through fixed phases.
  //   0-5s   → "Uploading pages…"
  //   5-25s  → "Extracting your answers…"
  //   25s+   → "Grading question by question…"
  useEffect(() => {
    if (!submitting) {
      setLoadingMessage(MSG_UPLOAD);
      return;
    }
    setLoadingMessage(MSG_UPLOAD);
    const t1 = setTimeout(() => setLoadingMessage(MSG_EXTRACT), 3000);
    const t2 = setTimeout(() => setLoadingMessage(MSG_GRADE), 12000);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, [submitting]);

  const handleCapturePage = useCallback(async () => {
    const { status } = await ImagePicker.requestCameraPermissionsAsync();
    if (status !== "granted") {
      Alert.alert(
        "Camera permission required",
        "Allow camera access in Settings to photograph your answer booklet."
      );
      return;
    }

    const result = await ImagePicker.launchCameraAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      base64: false,
      quality: 1,
    });

    if (result.canceled) return;

    const asset = result.assets[0];

    // Anthropic's request size limit is 32MB total. Raw iPhone photos are
    // 2–3 MB each in base64; 10+ pages overflows. Downscale to 1500px on
    // the long edge (Anthropic resamples to 1568px internally anyway) and
    // re-encode at quality 0.6 — keeps handwriting legible at ~200–400 KB.
    try {
      const manipulated = await ImageManipulator.manipulateAsync(
        asset.uri,
        [{ resize: { width: 1500 } }],
        {
          compress: 0.6,
          format: ImageManipulator.SaveFormat.JPEG,
          base64: true,
        }
      );
      if (!manipulated.base64) {
        Alert.alert("Photo error", "Could not encode the photo. Please try again.");
        return;
      }
      setPages((prev) => [
        ...prev,
        { uri: manipulated.uri, base64: manipulated.base64! },
      ]);
    } catch {
      Alert.alert("Photo error", "Could not process the photo. Please try again.");
    }
  }, []);

  const handleRemovePage = useCallback((index: number) => {
    setPages((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const handleSubmit = useCallback(async () => {
    if (pages.length === 0) return;

    setSubmitting(true);
    try {
      const result: PaperGradingResult = await gradePaper(
        Number(paperId),
        pages.map((p) => p.base64)
      );

      router.push({
        pathname: "/results/paper",
        params: { resultData: JSON.stringify(result) },
      });
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Grading failed. Please try again.";
      Alert.alert("Grading failed", message, [{ text: "OK" }]);
    } finally {
      setSubmitting(false);
    }
  }, [pages, paperId, router]);

  return (
    <View style={styles.container}>
      {/* Instructions */}
      <View style={styles.instructions}>
        <Text style={styles.instructionTitle}>
          How it works
        </Text>
        <Text style={styles.instructionText}>
          Photograph each page of your answer booklet, then tap Submit.
          The AI will find and grade every question automatically.
        </Text>
      </View>

      {/* Page count */}
      <Text style={styles.pageCount}>
        {pages.length === 0
          ? "No pages captured yet"
          : `${pages.length} page${pages.length !== 1 ? "s" : ""} captured`}
      </Text>

      {/* Thumbnails */}
      {pages.length > 0 && (
        <FlatList
          data={pages}
          keyExtractor={(_, index) => String(index)}
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.thumbnailList}
          renderItem={({ item, index }) => (
            <View style={styles.thumbnailWrapper}>
              <Image
                source={{ uri: item.uri }}
                style={styles.thumbnail}
                resizeMode="cover"
              />
              <TouchableOpacity
                style={styles.removeButton}
                onPress={() => handleRemovePage(index)}
                activeOpacity={0.8}
              >
                <Text style={styles.removeButtonText}>✕</Text>
              </TouchableOpacity>
              <Text style={styles.pageLabel}>Page {index + 1}</Text>
            </View>
          )}
        />
      )}

      {/* Spacer */}
      <View style={styles.spacer} />

      {/* Capture button */}
      <TouchableOpacity
        style={styles.captureButton}
        onPress={handleCapturePage}
        disabled={submitting}
        activeOpacity={0.8}
      >
        <Text style={styles.captureButtonText}>
          {pages.length === 0 ? "📷  Photograph Page 1" : "📷  Add Next Page"}
        </Text>
      </TouchableOpacity>

      {/* Submit button */}
      <TouchableOpacity
        style={[
          styles.submitButton,
          pages.length === 0 && styles.submitButtonDisabled,
        ]}
        onPress={handleSubmit}
        disabled={pages.length === 0 || submitting}
        activeOpacity={0.85}
      >
        <Text style={styles.submitButtonText}>
          Submit for Grading
        </Text>
      </TouchableOpacity>

      {/* Loading overlay with cycling messages */}
      <Modal visible={submitting} transparent animationType="fade" statusBarTranslucent>
        <View style={styles.backdrop}>
          <View style={styles.loadingCard}>
            <ActivityIndicator size="large" color="#4F46E5" />
            <Text style={styles.loadingTitle}>Grading in progress</Text>
            <Text style={styles.loadingMessage}>{loadingMessage}</Text>
            <Text style={styles.loadingHint}>
              This usually takes 30–60 seconds.
            </Text>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#F9FAFB",
    padding: 16,
    paddingBottom: 32,
  },
  instructions: {
    backgroundColor: "#EEF2FF",
    borderRadius: 12,
    padding: 14,
    marginBottom: 16,
    gap: 4,
  },
  instructionTitle: {
    fontSize: 14,
    fontWeight: "700",
    color: "#4338CA",
  },
  instructionText: {
    fontSize: 13,
    color: "#4338CA",
    lineHeight: 19,
  },
  pageCount: {
    fontSize: 14,
    fontWeight: "600",
    color: "#6B7280",
    marginBottom: 12,
  },
  thumbnailList: {
    paddingBottom: 4,
    gap: 12,
  },
  thumbnailWrapper: {
    alignItems: "center",
    gap: 4,
  },
  thumbnail: {
    width: 90,
    height: 120,
    borderRadius: 8,
    backgroundColor: "#E5E7EB",
  },
  removeButton: {
    position: "absolute",
    top: -6,
    right: -6,
    backgroundColor: "#EF4444",
    borderRadius: 12,
    width: 24,
    height: 24,
    justifyContent: "center",
    alignItems: "center",
  },
  removeButtonText: {
    color: "#fff",
    fontSize: 11,
    fontWeight: "700",
  },
  pageLabel: {
    fontSize: 11,
    color: "#9CA3AF",
    fontWeight: "500",
  },
  spacer: {
    flex: 1,
  },
  captureButton: {
    backgroundColor: "#fff",
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: "center",
    borderWidth: 2,
    borderColor: "#4F46E5",
    marginBottom: 12,
  },
  captureButtonText: {
    color: "#4F46E5",
    fontSize: 16,
    fontWeight: "700",
  },
  submitButton: {
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
  submitButtonDisabled: {
    backgroundColor: "#C7D2FE",
    shadowOpacity: 0,
    elevation: 0,
  },
  submitButtonText: {
    color: "#fff",
    fontSize: 17,
    fontWeight: "700",
    letterSpacing: 0.3,
  },
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.65)",
    justifyContent: "center",
    alignItems: "center",
  },
  loadingCard: {
    backgroundColor: "#fff",
    borderRadius: 20,
    paddingHorizontal: 32,
    paddingVertical: 32,
    alignItems: "center",
    gap: 12,
    minWidth: 260,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.2,
    shadowRadius: 12,
    elevation: 8,
  },
  loadingTitle: {
    fontSize: 17,
    fontWeight: "700",
    color: "#1F2937",
  },
  loadingMessage: {
    fontSize: 15,
    fontWeight: "600",
    color: "#4F46E5",
    textAlign: "center",
  },
  loadingHint: {
    fontSize: 12,
    color: "#9CA3AF",
    textAlign: "center",
  },
});
