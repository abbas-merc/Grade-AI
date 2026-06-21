/**
 * app/paper-preview.tsx — Native preview of a generated paper (no PDF render).
 *
 * Renders the generate-paper response directly: a summary card, then one card
 * per question with its number, total marks, intro text, and parsed sub-parts
 * (each indented with its own mark allocation). The header download icon and
 * the two bottom buttons both fetch a PDF from the backend, write it to the
 * cache as base64, and hand it to the OS share sheet.
 */

import React, { useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  Image,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  StyleSheet,
  Modal,
  Alert,
} from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import * as FileSystem from "expo-file-system/legacy";
import * as Sharing from "expo-sharing";

import { parseQuestionParts } from "../utils/parseQuestion";
import { downloadQuestionPaperPdf, downloadMarkSchemePdf } from "../services/api";
import type { GeneratedPaper, GeneratedQuestion } from "../types/paperGenerator";
import { COLORS, RADIUS, SPACING, FONT } from "../constants/theme";
import { BASE_URL } from "../constants/config";

/**
 * DiagramImage — render an extracted question figure at the card's width while
 * preserving aspect ratio. imageUrl is host-agnostic ("/diagrams/<id>.png"), so
 * we prepend BASE_URL. Image.getSize gives the natural dimensions, which we turn
 * into an aspectRatio so the height tracks the (full) card width.
 */
function DiagramImage({ imageUrl }: { imageUrl: string }) {
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
      style={[styles.diagram, aspect ? { aspectRatio: aspect } : { height: 180 }]}
    />
  );
}

type DownloadKind = "qp" | "ms";

/** totalMarks * 1.5, rounded to the nearest 15 minutes. */
function estimatedMinutes(totalMarks: number): number {
  return Math.max(15, Math.round((totalMarks * 1.5) / 15) * 15);
}

function formatTime(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h && m) return `${h} h ${m} min`;
  if (h) return `${h} h`;
  return `${m} min`;
}

function QuestionCard({ question }: { question: GeneratedQuestion }) {
  const parsed = useMemo(
    () => parseQuestionParts(question.questionText),
    [question.questionText]
  );

  return (
    <View style={styles.questionCard}>
      <View style={styles.questionHeader}>
        <Text style={styles.questionNumber}>{question.assignedNumber}</Text>
        <Text style={styles.questionMarks}>[{question.marks} marks]</Text>
      </View>

      {parsed.intro ? <Text style={styles.introText}>{parsed.intro}</Text> : null}

      {question.hasImage && question.imageUrl ? (
        <DiagramImage imageUrl={question.imageUrl} />
      ) : null}

      {parsed.parts.map((part, idx) => (
        <View key={`${part.label}-${idx}`} style={styles.partRow}>
          <Text style={styles.partText}>
            <Text style={styles.partLabel}>({part.label}) </Text>
            {part.text}
          </Text>
          {part.marks != null ? (
            <Text style={styles.partMarks}>[{part.marks}]</Text>
          ) : null}
        </View>
      ))}
    </View>
  );
}

export default function PaperPreviewScreen() {
  const { paper: paperParam } = useLocalSearchParams<{ paper: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();

  const paper: GeneratedPaper | null = useMemo(() => {
    if (!paperParam) return null;
    try {
      return JSON.parse(paperParam) as GeneratedPaper;
    } catch {
      return null;
    }
  }, [paperParam]);

  const [sheetOpen, setSheetOpen] = useState(false);
  const [downloading, setDownloading] = useState<DownloadKind | null>(null);

  if (!paper) {
    return (
      <View style={styles.centered}>
        <Text style={styles.errorTitle}>Paper unavailable</Text>
        <TouchableOpacity style={styles.bottomButtonFilled} onPress={() => router.back()}>
          <Text style={styles.bottomButtonFilledText}>Go Back</Text>
        </TouchableOpacity>
      </View>
    );
  }

  const handleDownload = async (kind: DownloadKind) => {
    // Ignore taps while a download is already in flight (the bottom-sheet
    // options aren't disabled, so guard here too — Section 9.2 debounce).
    if (downloading) return;
    setSheetOpen(false);
    setDownloading(kind);
    try {
      const base64 =
        kind === "qp"
          ? await downloadQuestionPaperPdf(paper)
          : await downloadMarkSchemePdf(paper);
      const filename =
        kind === "qp" ? "custom_math_paper.pdf" : "custom_math_mark_scheme.pdf";
      const fileUri = `${FileSystem.cacheDirectory}${filename}`;
      await FileSystem.writeAsStringAsync(fileUri, base64, {
        encoding: FileSystem.EncodingType.Base64,
      });
      if (await Sharing.isAvailableAsync()) {
        await Sharing.shareAsync(fileUri, {
          mimeType: "application/pdf",
          UTI: "com.adobe.pdf",
          dialogTitle: kind === "qp" ? "Question Paper" : "Mark Scheme",
        });
      } else {
        Alert.alert("Saved", `PDF saved to:\n${fileUri}`);
      }
    } catch (err) {
      Alert.alert(
        "Download failed",
        err instanceof Error ? err.message : "Could not download the PDF."
      );
    } finally {
      setDownloading(null);
    }
  };

  // Hand the generated paper to the existing capture/marking flow. There's no
  // stored paper_id (paperId="0"); the mark scheme rides along as a serialised
  // route param and is written inline on the marking job at submit time.
  const handleMarkResponses = () => {
    router.push({
      pathname: "/capture/[paperId]",
      params: {
        paperId: "0",
        paperName: "Custom Paper",
        generatedPaper: JSON.stringify(paper),
      },
    });
  };

  const minutes = estimatedMinutes(paper.totalMarks);

  return (
    <View style={styles.screen}>
      {/* Custom header */}
      <View style={[styles.header, { paddingTop: insets.top + SPACING.sm }]}>
        <TouchableOpacity style={styles.headerIcon} onPress={() => router.back()} hitSlop={10}>
          <Text style={styles.headerIconText}>←</Text>
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Paper Preview</Text>
        <TouchableOpacity style={styles.headerIcon} onPress={() => setSheetOpen(true)} hitSlop={10}>
          <Text style={styles.headerIconText}>⬇</Text>
        </TouchableOpacity>
      </View>

      <ScrollView style={styles.scroll} contentContainerStyle={styles.scrollContent}>
        {/* Summary card */}
        <View style={styles.summaryCard}>
          <SummaryRow label="Subject" value="Mathematics (0580)" />
          <SummaryRow label="Total Marks" value={String(paper.totalMarks)} />
          <SummaryRow label="Number of Questions" value={String(paper.numQuestions)} />
          <SummaryRow label="Estimated Time" value={formatTime(minutes)} />
        </View>

        {/* Questions */}
        {paper.questions.map((q) => (
          <QuestionCard key={q.assignedNumber} question={q} />
        ))}

        {/* Primary action: mark student responses against this paper */}
        <TouchableOpacity
          style={styles.markButton}
          onPress={handleMarkResponses}
          activeOpacity={0.8}
        >
          <Text style={styles.markButtonText}>Mark Student Responses</Text>
        </TouchableOpacity>

        {/* Bottom action buttons */}
        <TouchableOpacity
          style={[styles.bottomButtonFilled, downloading && styles.buttonDisabled]}
          onPress={() => handleDownload("qp")}
          disabled={downloading !== null}
          activeOpacity={0.8}
        >
          {downloading === "qp" ? (
            <ActivityIndicator color={COLORS.card} />
          ) : (
            <Text style={styles.bottomButtonFilledText}>Download Question Paper</Text>
          )}
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.bottomButtonOutlined, downloading && styles.buttonDisabled]}
          onPress={() => handleDownload("ms")}
          disabled={downloading !== null}
          activeOpacity={0.8}
        >
          {downloading === "ms" ? (
            <ActivityIndicator color={COLORS.primary} />
          ) : (
            <Text style={styles.bottomButtonOutlinedText}>Download Mark Scheme</Text>
          )}
        </TouchableOpacity>
      </ScrollView>

      {/* Download bottom sheet */}
      <Modal visible={sheetOpen} transparent animationType="slide" onRequestClose={() => setSheetOpen(false)}>
        <TouchableOpacity style={styles.sheetBackdrop} activeOpacity={1} onPress={() => setSheetOpen(false)}>
          <View style={[styles.sheet, { paddingBottom: insets.bottom + SPACING.lg }]}>
            <View style={styles.sheetHandle} />
            <Text style={styles.sheetTitle}>Download</Text>
            <TouchableOpacity style={styles.sheetOption} onPress={() => handleDownload("qp")} activeOpacity={0.8}>
              <Text style={styles.sheetOptionText}>Download Question Paper</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.sheetOption} onPress={() => handleDownload("ms")} activeOpacity={0.8}>
              <Text style={styles.sheetOptionText}>Download Mark Scheme</Text>
            </TouchableOpacity>
          </View>
        </TouchableOpacity>
      </Modal>
    </View>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.summaryRow}>
      <Text style={styles.summaryLabel}>{label}</Text>
      <Text style={styles.summaryValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: COLORS.surface,
  },
  centered: {
    flex: 1,
    backgroundColor: COLORS.surface,
    justifyContent: "center",
    alignItems: "center",
    padding: SPACING.lg,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: SPACING.lg,
    paddingBottom: SPACING.md,
    backgroundColor: COLORS.primary,
  },
  headerIcon: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: "center",
    justifyContent: "center",
  },
  headerIconText: {
    color: COLORS.card,
    fontSize: 22,
    fontWeight: FONT.medium,
  },
  headerTitle: {
    color: COLORS.card,
    fontSize: 18,
    fontWeight: FONT.medium,
  },
  scroll: {
    flex: 1,
  },
  scrollContent: {
    padding: SPACING.lg,
    paddingBottom: SPACING.xxl,
  },
  summaryCard: {
    backgroundColor: COLORS.card,
    borderRadius: RADIUS.xl,
    borderWidth: 1,
    borderColor: COLORS.border,
    padding: SPACING.lg,
    marginBottom: SPACING.lg,
  },
  summaryRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingVertical: SPACING.xs,
  },
  summaryLabel: {
    fontSize: 14,
    color: COLORS.textSecondary,
  },
  summaryValue: {
    fontSize: 14,
    fontWeight: FONT.medium,
    color: COLORS.textPrimary,
  },
  questionCard: {
    backgroundColor: COLORS.card,
    borderRadius: RADIUS.xl,
    borderWidth: 1,
    borderColor: COLORS.border,
    padding: SPACING.lg,
    marginBottom: SPACING.md, // 12px gap between cards
    // subtle shadow
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.06,
    shadowRadius: 3,
    elevation: 2,
  },
  questionHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  questionNumber: {
    fontSize: 22,
    fontWeight: "700",
    color: COLORS.textPrimary,
  },
  questionMarks: {
    fontSize: 14,
    color: COLORS.textSecondary,
  },
  introText: {
    fontSize: 15,
    lineHeight: 22,
    color: COLORS.textPrimary,
    marginTop: SPACING.md,
  },
  diagram: {
    width: "100%",
    marginTop: SPACING.md,
    borderRadius: RADIUS.md,
    backgroundColor: "#FFFFFF",
  },
  partRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    marginTop: SPACING.md,
    paddingLeft: SPACING.md, // indent sub-parts
  },
  partText: {
    flex: 1,
    fontSize: 15,
    lineHeight: 22,
    color: COLORS.textPrimary,
  },
  partLabel: {
    fontWeight: FONT.medium,
    color: COLORS.textPrimary,
  },
  partMarks: {
    fontSize: 14,
    color: COLORS.textSecondary,
    marginLeft: SPACING.sm,
  },
  markButton: {
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.lg,
    paddingVertical: SPACING.lg,
    alignItems: "center",
    marginTop: SPACING.lg,
  },
  markButtonText: {
    color: COLORS.card,
    fontSize: 16,
    fontWeight: FONT.medium,
  },
  bottomButtonFilled: {
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.lg,
    paddingVertical: SPACING.lg,
    alignItems: "center",
    marginTop: SPACING.lg,
  },
  bottomButtonFilledText: {
    color: COLORS.card,
    fontSize: 16,
    fontWeight: FONT.medium,
  },
  bottomButtonOutlined: {
    backgroundColor: COLORS.card,
    borderRadius: RADIUS.lg,
    borderWidth: 1.5,
    borderColor: COLORS.primary,
    paddingVertical: SPACING.lg,
    alignItems: "center",
    marginTop: SPACING.md,
  },
  bottomButtonOutlinedText: {
    color: COLORS.primary,
    fontSize: 16,
    fontWeight: FONT.medium,
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  errorTitle: {
    fontSize: 18,
    fontWeight: FONT.medium,
    color: COLORS.textPrimary,
    marginBottom: SPACING.lg,
  },
  sheetBackdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.4)",
    justifyContent: "flex-end",
  },
  sheet: {
    backgroundColor: COLORS.card,
    borderTopLeftRadius: RADIUS.xl,
    borderTopRightRadius: RADIUS.xl,
    padding: SPACING.lg,
  },
  sheetHandle: {
    alignSelf: "center",
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: COLORS.border,
    marginBottom: SPACING.lg,
  },
  sheetTitle: {
    fontSize: 16,
    fontWeight: FONT.medium,
    color: COLORS.textPrimary,
    marginBottom: SPACING.md,
  },
  sheetOption: {
    paddingVertical: SPACING.lg,
    paddingHorizontal: SPACING.md,
    borderRadius: RADIUS.lg,
    backgroundColor: COLORS.surface,
    marginBottom: SPACING.sm,
  },
  sheetOptionText: {
    fontSize: 16,
    color: COLORS.primary,
    fontWeight: FONT.medium,
    textAlign: "center",
  },
});
