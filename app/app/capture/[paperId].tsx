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
} from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { CameraView, useCameraPermissions } from "expo-camera";

import { submitPaperForGrading } from "../../services/markingQueue";
import type { GeneratedPaper } from "../../types/paperGenerator";
import { COLORS, RADIUS, SPACING, FONT, ON } from "../../constants/theme";

const THUMB_SIZE = 130;

const LOADING_MESSAGES = ["Uploading pages…"];

interface CapturedPage {
  uri: string;
  base64: string;
}

type Phase = "scanning" | "review";

export default function CaptureScreen() {
  const { paperId, paperName, generatedPaper } = useLocalSearchParams<{
    paperId: string;
    paperName?: string;
    // Present only when marking a Custom Paper Generator paper: the full
    // generate-paper response, serialised. Carried in memory through the route.
    generatedPaper?: string;
  }>();
  const router = useRouter();

  const [permission, requestPermission] = useCameraPermissions();
  const cameraRef = useRef<CameraView>(null);

  const [phase, setPhase] = useState<Phase>("scanning");
  const [pages, setPages] = useState<CapturedPage[]>([]);
  const [capturing, setCapturing] = useState(false);
  const [retakeIndex, setRetakeIndex] = useState<number | null>(null);

  const [submitting, setSubmitting] = useState(false);
  const [loadingIndex, setLoadingIndex] = useState(0);

  // While submitting, cycle the sub-status line every 8 seconds.
  useEffect(() => {
    if (!submitting) {
      setLoadingIndex(0);
      return;
    }
    const id = setInterval(() => {
      setLoadingIndex((i) => (i + 1) % LOADING_MESSAGES.length);
    }, 8000);
    return () => clearInterval(id);
  }, [submitting]);

  const handleCapture = useCallback(async () => {
    if (!cameraRef.current || capturing) return;
    setCapturing(true);
    try {
      // Capture at full original resolution with no compression or downscaling,
      // so the backend receives the sharpest possible image for handwriting
      // recognition. quality: 1 disables JPEG compression on the capture.
      const photo = await cameraRef.current.takePictureAsync({
        base64: true,
        quality: 1,
      });
      if (!photo) return;

      if (!photo.base64) {
        Alert.alert("Photo error", "Could not encode the photo. Please try again.");
        return;
      }

      const newPage: CapturedPage = {
        uri: photo.uri,
        base64: photo.base64,
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
      // Compress pages, write them to Firestore + the "queued" marking document,
      // then return. We do NOT wait for grading — the backend queue listener
      // handles it. Pages are sent as file URIs; markingQueue downscales and
      // encodes each one.
      const inlineGenerated: GeneratedPaper | undefined = generatedPaper
        ? (JSON.parse(generatedPaper) as GeneratedPaper)
        : undefined;
      await submitPaperForGrading(
        Number(paperId),
        paperName ?? `Paper ${paperId}`,
        pages.map((p) => p.uri),
        inlineGenerated
      );
      // Clear the whole capture flow from the stack so Back can't return here,
      // then drop the teacher on the History tab, where the job shows as
      // "In queue" → "Grading…" → score, updating live. A push notification
      // arrives when it's ready.
      if (router.canDismiss()) {
        router.dismissAll();
      }
      router.replace({ pathname: "/", params: { tab: "history" } });
      Alert.alert(
        "Paper submitted",
        "Paper submitted for grading. We will notify you when it is ready."
      );
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Submission failed. Please try again.";
      Alert.alert("Submission failed", message, [{ text: "OK" }]);
      // Stay on the review screen so the teacher can retry.
      setSubmitting(false);
    }
  }, [pages, paperId, paperName, generatedPaper, router]);

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

  // ── Submitting: full-screen grading progress ────────────────────────────────

  if (submitting) {
    return (
      <View style={styles.loadingScreen}>
        <Text style={styles.loadingAppName}>GradeAI</Text>
        <Text style={styles.loadingMain}>Submitting paper</Text>
        <Text style={styles.loadingSub}>{LOADING_MESSAGES[loadingIndex]}</Text>
        <Text style={styles.loadingHelper}>This will only take a moment</Text>
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
            />
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
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,1)",
  },
  centered: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    gap: SPACING.lg,
    padding: SPACING.xxl,
    backgroundColor: COLORS.surface,
  },

  // ── Full-screen grading progress ────────────────────────────────────────────
  loadingScreen: {
    flex: 1,
    backgroundColor: COLORS.card,
    alignItems: "center",
    justifyContent: "center",
  },
  loadingAppName: {
    fontSize: 18,
    fontWeight: FONT.medium,
    color: COLORS.primary,
    marginBottom: SPACING.xxl,
  },
  loadingMain: {
    fontSize: 18,
    fontWeight: FONT.medium,
    color: COLORS.textPrimary,
    textAlign: "center",
  },
  loadingSub: {
    fontSize: 14,
    color: COLORS.textSecondary,
    textAlign: "center",
    marginTop: SPACING.sm,
  },
  loadingHelper: {
    position: "absolute",
    bottom: 40,
    fontSize: 12,
    color: COLORS.textTertiary,
    textAlign: "center",
  },

  // ── Permission ──────────────────────────────────────────────────────────────
  permissionText: {
    fontSize: 16,
    color: COLORS.textSecondary,
    textAlign: "center",
    lineHeight: 24,
  },
  permissionButton: {
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.lg,
    paddingHorizontal: SPACING.xl,
    paddingVertical: 14,
  },
  permissionButtonText: {
    color: COLORS.card,
    fontSize: 15,
    fontWeight: FONT.medium,
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
    paddingBottom: SPACING.lg,
    backgroundColor: "rgba(0,0,0,0.45)",
  },
  pageCounter: {
    color: COLORS.card,
    fontSize: 16,
    fontWeight: FONT.medium,
  },
  doneButton: {
    backgroundColor: COLORS.card,
    borderRadius: RADIUS.md,
    paddingHorizontal: SPACING.lg,
    paddingVertical: SPACING.sm,
  },
  doneButtonDisabled: {
    backgroundColor: "rgba(255,255,255,0.3)",
  },
  doneButtonText: {
    color: COLORS.primary,
    fontSize: 14,
    fontWeight: FONT.medium,
  },
  doneButtonTextDisabled: {
    color: "rgba(255,255,255,0.5)",
  },
  cancelButton: {
    backgroundColor: "rgba(255,255,255,0.2)",
    borderRadius: RADIUS.md,
    paddingHorizontal: SPACING.lg,
    paddingVertical: SPACING.sm,
  },
  cancelButtonText: {
    color: COLORS.card,
    fontSize: 14,
    fontWeight: FONT.medium,
  },
  cameraBottomBar: {
    position: "absolute",
    bottom: 0,
    left: 0,
    right: 0,
    paddingBottom: 48,
    paddingTop: SPACING.xl,
    alignItems: "center",
    backgroundColor: "rgba(0,0,0,0.45)",
  },
  shutter: {
    width: 70,
    height: 70,
    borderRadius: 35,
    backgroundColor: COLORS.card,
    borderWidth: 2,
    borderColor: COLORS.primary,
  },
  shutterCapturing: {
    opacity: 0.5,
  },

  // ── Review ──────────────────────────────────────────────────────────────────
  reviewHeader: {
    paddingHorizontal: SPACING.lg,
    paddingTop: SPACING.lg,
    paddingBottom: SPACING.md,
    backgroundColor: COLORS.surface,
    gap: SPACING.xs,
  },
  reviewTitle: {
    fontSize: 18,
    fontWeight: FONT.medium,
    color: COLORS.textPrimary,
  },
  reviewSubtitle: {
    fontSize: 13,
    color: COLORS.textSecondary,
  },
  reviewScroll: {
    flex: 1,
    backgroundColor: COLORS.surface,
  },
  reviewGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: SPACING.lg,
    padding: SPACING.lg,
  },
  thumbCard: {
    width: THUMB_SIZE,
    gap: SPACING.sm,
  },
  thumbImage: {
    width: THUMB_SIZE,
    height: THUMB_SIZE * 1.35,
    borderRadius: RADIUS.lg,
    borderWidth: 0.5,
    borderColor: COLORS.border,
    backgroundColor: COLORS.border,
  },
  thumbLabel: {
    fontSize: 12,
    color: COLORS.textSecondary,
    textAlign: "center",
    marginTop: SPACING.sm,
  },
  thumbActions: {
    flexDirection: "row",
    gap: SPACING.sm,
  },
  retakeButton: {
    flex: 1,
    backgroundColor: "transparent",
    borderWidth: 0.5,
    borderColor: COLORS.border,
    borderRadius: RADIUS.md,
    paddingVertical: SPACING.sm,
    alignItems: "center",
  },
  retakeButtonText: {
    color: COLORS.textPrimary,
    fontSize: 14,
    fontWeight: FONT.regular,
  },
  deleteButton: {
    flex: 1,
    backgroundColor: COLORS.failLight,
    borderWidth: 0,
    borderRadius: RADIUS.md,
    paddingVertical: SPACING.sm,
    alignItems: "center",
  },
  deleteButtonText: {
    color: ON.deleteText,
    fontSize: 14,
    fontWeight: FONT.medium,
  },
  reviewFooter: {
    padding: SPACING.lg,
    paddingBottom: SPACING.xxl,
    backgroundColor: COLORS.surface,
    borderTopWidth: 0.5,
    borderTopColor: COLORS.border,
  },
  addMoreButton: {
    backgroundColor: "transparent",
    borderWidth: 1.5,
    borderColor: COLORS.primary,
    borderRadius: RADIUS.lg,
    paddingVertical: 14,
    alignItems: "center",
  },
  addMoreButtonText: {
    color: COLORS.primary,
    fontSize: 15,
    fontWeight: FONT.medium,
  },
  submitButton: {
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.lg,
    paddingVertical: SPACING.lg,
    alignItems: "center",
    marginTop: SPACING.md,
  },
  submitButtonText: {
    color: COLORS.card,
    fontSize: 15,
    fontWeight: FONT.medium,
  },
});
