/**
 * app/capture/[paperId].tsx — Multi-page answer booklet capture screen.
 *
 * Phase 1 — Scanning:
 *   Live camera view with a page counter and Done button overlaid.
 *   Each tap of the shutter captures a page and increments the counter.
 *   The camera stays live between captures.
 *   Tapping Done (requires ≥ 1 page) moves to the review phase.
 *
 * Phase 2 — Review:
 *   Thumbnail grid of all captured pages.
 *   Each page has a Delete button and a Retake button.
 *   Retake sends the user back to scanning, captures one photo,
 *   replaces that specific page, then returns to review.
 *   Submit for Grading sends images and navigates to results.
 */

import React, { useState, useCallback, useEffect, useRef } from "react";
import {
  View,
  Text,
  TouchableOpacity,
  ScrollView,
  Image,
  Alert,
  StyleSheet,
  Modal,
  ActivityIndicator,
  Dimensions,
} from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { CameraView, useCameraPermissions } from "expo-camera";
import * as ImageManipulator from "expo-image-manipulator";

import { gradePaper } from "../../services/api";
import type { PaperGradingResult } from "../../types";

const SCREEN_WIDTH = Dimensions.get("window").width;
const THUMB_SIZE = (SCREEN_WIDTH - 48) / 2;

const MSG_UPLOAD = "Uploading pages…";
const MSG_EXTRACT = "Reading your handwriting…";
const MSG_GRADE = "Grading every question…";

interface CapturedPage {
  uri: string;
  base64: string;
}

type Phase = "scanning" | "review";

export default function CaptureScreen() {
  const { paperId, paperName } = useLocalSearchParams<{ paperId: string; paperName?: string }>();
  const router = useRouter();

  const [permission, requestPermission] = useCameraPermissions();
  const cameraRef = useRef<CameraView>(null);

  const [phase, setPhase] = useState<Phase>("scanning");
  const [pages, setPages] = useState<CapturedPage[]>([]);
  const [capturing, setCapturing] = useState(false);
  const [retakeIndex, setRetakeIndex] = useState<number | null>(null);

  const [submitting, setSubmitting] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState(MSG_UPLOAD);

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

  const handleCapture = useCallback(async () => {
    if (!cameraRef.current || capturing) return;
    setCapturing(true);
    try {
      const photo = await cameraRef.current.takePictureAsync({ base64: false });
      if (!photo) return;

      // Downscale to 1500px wide and re-encode at 0.6 quality.
      // Raw iPhone photos are 2–3 MB each; 10+ pages would exceed Anthropic's
      // 32 MB request limit. 1500px keeps handwriting legible at ~200–400 KB.
      const manipulated = await ImageManipulator.manipulateAsync(
        photo.uri,
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

      const newPage: CapturedPage = {
        uri: manipulated.uri,
        base64: manipulated.base64,
      };

      if (retakeIndex !== null) {
        setPages((prev) => prev.map((p, i) => (i === retakeIndex ? newPage : p)));
        setRetakeIndex(null);
        setPhase("review");
      } else {
        setPages((prev) => [...prev, newPage]);
      }
    } catch {
      Alert.alert("Photo error", "Could not process the photo. Please try again.");
    } finally {
      setCapturing(false);
    }
  }, [capturing, retakeIndex]);

  const handleDone = useCallback(() => {
    if (pages.length === 0) {
      Alert.alert("No pages captured", "Photograph at least one page before continuing.");
      return;
    }
    setPhase("review");
    setRetakeIndex(null);
  }, [pages.length]);

  const handleRetake = useCallback((index: number) => {
    setRetakeIndex(index);
    setPhase("scanning");
  }, []);

  const handleDelete = useCallback((index: number) => {
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
        params: { resultData: JSON.stringify(result), paperName: paperName ?? "" },
      });
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Grading failed. Please try again.";
      Alert.alert("Grading failed", message, [{ text: "OK" }]);
    } finally {
      setSubmitting(false);
    }
  }, [pages, paperId, paperName, router]);

  // ── Permission states ───────────────────────────────────────────────────────

  if (!permission) {
    return <View style={styles.container} />;
  }

  if (!permission.granted) {
    return (
      <View style={styles.centered}>
        <Text style={styles.permissionText}>
          Camera access is required to scan your answer booklet.
        </Text>
        <TouchableOpacity
          style={styles.permissionButton}
          onPress={requestPermission}
          activeOpacity={0.85}
        >
          <Text style={styles.permissionButtonText}>Grant Camera Access</Text>
        </TouchableOpacity>
      </View>
    );
  }

  // ── Phase 1: Scanning ───────────────────────────────────────────────────────

  if (phase === "scanning") {
    const isRetaking = retakeIndex !== null;
    const counterLabel = isRetaking
      ? `Retaking page ${retakeIndex! + 1}`
      : pages.length === 0
      ? "No pages captured yet"
      : `${pages.length} page${pages.length !== 1 ? "s" : ""} captured`;

    return (
      <View style={styles.container}>
        <CameraView ref={cameraRef} style={styles.camera} facing="back">
          {/* Top bar — counter + Done/Cancel */}
          <View style={styles.cameraTopBar}>
            <Text style={styles.pageCounter}>{counterLabel}</Text>
            {isRetaking ? (
              <TouchableOpacity
                style={styles.cancelButton}
                onPress={() => {
                  setRetakeIndex(null);
                  setPhase("review");
                }}
                activeOpacity={0.8}
              >
                <Text style={styles.cancelButtonText}>Cancel</Text>
              </TouchableOpacity>
            ) : (
              <TouchableOpacity
                style={[
                  styles.doneButton,
                  pages.length === 0 && styles.doneButtonDisabled,
                ]}
                onPress={handleDone}
                disabled={pages.length === 0}
                activeOpacity={0.8}
              >
                <Text
                  style={[
                    styles.doneButtonText,
                    pages.length === 0 && styles.doneButtonTextDisabled,
                  ]}
                >
                  Done
                </Text>
              </TouchableOpacity>
            )}
          </View>

          {/* Bottom bar — shutter */}
          <View style={styles.cameraBottomBar}>
            <TouchableOpacity
              style={[styles.shutter, capturing && styles.shutterCapturing]}
              onPress={handleCapture}
              disabled={capturing}
              activeOpacity={0.85}
            >
              <View style={styles.shutterInner} />
            </TouchableOpacity>
          </View>
        </CameraView>
      </View>
    );
  }

  // ── Phase 2: Review ─────────────────────────────────────────────────────────

  return (
    <View style={styles.container}>
      <View style={styles.reviewHeader}>
        <Text style={styles.reviewTitle}>
          {pages.length} page{pages.length !== 1 ? "s" : ""} captured
        </Text>
        <Text style={styles.reviewSubtitle}>
          Delete or retake any page, then submit when ready.
        </Text>
      </View>

      <ScrollView
        style={styles.reviewScroll}
        contentContainerStyle={styles.reviewGrid}
        showsVerticalScrollIndicator={false}
      >
        {pages.map((page, index) => (
          <View key={index} style={styles.thumbCard}>
            <Image
              source={{ uri: page.uri }}
              style={styles.thumbImage}
              resizeMode="cover"
            />
            <Text style={styles.thumbLabel}>Page {index + 1}</Text>
            <View style={styles.thumbActions}>
              <TouchableOpacity
                style={styles.retakeButton}
                onPress={() => handleRetake(index)}
                activeOpacity={0.8}
              >
                <Text style={styles.retakeButtonText}>Retake</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={styles.deleteButton}
                onPress={() => handleDelete(index)}
                activeOpacity={0.8}
              >
                <Text style={styles.deleteButtonText}>Delete</Text>
              </TouchableOpacity>
            </View>
          </View>
        ))}
      </ScrollView>

      <View style={styles.reviewFooter}>
        <TouchableOpacity
          style={styles.addMoreButton}
          onPress={() => setPhase("scanning")}
          activeOpacity={0.8}
        >
          <Text style={styles.addMoreButtonText}>+ Add More Pages</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={styles.submitButton}
          onPress={handleSubmit}
          activeOpacity={0.85}
        >
          <Text style={styles.submitButtonText}>Submit for Grading</Text>
        </TouchableOpacity>
      </View>

      <Modal visible={submitting} transparent animationType="fade" statusBarTranslucent>
        <View style={styles.backdrop}>
          <View style={styles.loadingCard}>
            <ActivityIndicator size="large" color="#4F46E5" />
            <Text style={styles.loadingTitle}>Grading in progress</Text>
            <Text style={styles.loadingMessage}>{loadingMessage}</Text>
            <Text style={styles.loadingHint}>This usually takes 30–60 seconds.</Text>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#000",
  },
  centered: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    gap: 16,
    padding: 32,
    backgroundColor: "#F9FAFB",
  },

  // ── Permission ──────────────────────────────────────────────────────────────
  permissionText: {
    fontSize: 16,
    color: "#374151",
    textAlign: "center",
    lineHeight: 24,
  },
  permissionButton: {
    backgroundColor: "#4F46E5",
    borderRadius: 12,
    paddingHorizontal: 24,
    paddingVertical: 14,
  },
  permissionButtonText: {
    color: "#fff",
    fontSize: 15,
    fontWeight: "700",
  },

  // ── Camera / Scanning ───────────────────────────────────────────────────────
  camera: {
    flex: 1,
  },
  cameraTopBar: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingTop: 56,
    paddingHorizontal: 20,
    paddingBottom: 16,
    backgroundColor: "rgba(0,0,0,0.45)",
  },
  pageCounter: {
    color: "#fff",
    fontSize: 16,
    fontWeight: "600",
  },
  doneButton: {
    backgroundColor: "#fff",
    borderRadius: 20,
    paddingHorizontal: 20,
    paddingVertical: 8,
  },
  doneButtonDisabled: {
    backgroundColor: "rgba(255,255,255,0.3)",
  },
  doneButtonText: {
    color: "#1F2937",
    fontSize: 15,
    fontWeight: "700",
  },
  doneButtonTextDisabled: {
    color: "rgba(255,255,255,0.5)",
  },
  cancelButton: {
    backgroundColor: "rgba(255,255,255,0.2)",
    borderRadius: 20,
    paddingHorizontal: 20,
    paddingVertical: 8,
  },
  cancelButtonText: {
    color: "#fff",
    fontSize: 15,
    fontWeight: "600",
  },
  cameraBottomBar: {
    position: "absolute",
    bottom: 0,
    left: 0,
    right: 0,
    paddingBottom: 48,
    paddingTop: 24,
    alignItems: "center",
    backgroundColor: "rgba(0,0,0,0.45)",
  },
  shutter: {
    width: 76,
    height: 76,
    borderRadius: 38,
    backgroundColor: "transparent",
    borderWidth: 4,
    borderColor: "#fff",
    justifyContent: "center",
    alignItems: "center",
  },
  shutterCapturing: {
    opacity: 0.5,
  },
  shutterInner: {
    width: 58,
    height: 58,
    borderRadius: 29,
    backgroundColor: "#fff",
  },

  // ── Review ──────────────────────────────────────────────────────────────────
  reviewHeader: {
    paddingHorizontal: 16,
    paddingTop: 16,
    paddingBottom: 12,
    backgroundColor: "#F9FAFB",
    gap: 4,
  },
  reviewTitle: {
    fontSize: 18,
    fontWeight: "700",
    color: "#111827",
  },
  reviewSubtitle: {
    fontSize: 13,
    color: "#6B7280",
  },
  reviewScroll: {
    flex: 1,
    backgroundColor: "#F9FAFB",
  },
  reviewGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 16,
    padding: 16,
  },
  thumbCard: {
    width: THUMB_SIZE,
    gap: 6,
  },
  thumbImage: {
    width: THUMB_SIZE,
    height: THUMB_SIZE * 1.35,
    borderRadius: 10,
    backgroundColor: "#E5E7EB",
  },
  thumbLabel: {
    fontSize: 12,
    fontWeight: "600",
    color: "#6B7280",
    textAlign: "center",
  },
  thumbActions: {
    flexDirection: "row",
    gap: 8,
  },
  retakeButton: {
    flex: 1,
    backgroundColor: "#EEF2FF",
    borderRadius: 8,
    paddingVertical: 8,
    alignItems: "center",
  },
  retakeButtonText: {
    color: "#4F46E5",
    fontSize: 13,
    fontWeight: "600",
  },
  deleteButton: {
    flex: 1,
    backgroundColor: "#FEE2E2",
    borderRadius: 8,
    paddingVertical: 8,
    alignItems: "center",
  },
  deleteButtonText: {
    color: "#EF4444",
    fontSize: 13,
    fontWeight: "600",
  },
  reviewFooter: {
    padding: 16,
    paddingBottom: 32,
    backgroundColor: "#F9FAFB",
    borderTopWidth: 1,
    borderTopColor: "#E5E7EB",
    gap: 10,
  },
  addMoreButton: {
    borderWidth: 2,
    borderColor: "#4F46E5",
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
  },
  addMoreButtonText: {
    color: "#4F46E5",
    fontSize: 15,
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
  submitButtonText: {
    color: "#fff",
    fontSize: 17,
    fontWeight: "700",
    letterSpacing: 0.3,
  },

  // ── Loading overlay ─────────────────────────────────────────────────────────
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
