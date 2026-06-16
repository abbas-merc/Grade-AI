/**
 * components/LoadingOverlay.tsx — Full-screen grading progress view.
 *
 * No longer a modal: while `visible` is true it renders an absolutely
 * positioned, full-screen layer and cycles a sub-status line every 8 seconds.
 */

import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet } from "react-native";
import { COLORS, SPACING, FONT } from "../constants/theme";

interface Props {
  visible: boolean;
  message: string;
}

const SUB_MESSAGES = [
  "Uploading pages…",
  "Analysing handwriting…",
  "Applying mark scheme…",
];

export default function LoadingOverlay({ visible, message }: Props) {
  const [subIndex, setSubIndex] = useState(0);

  // Cycle the sub-status line every 8 seconds while visible.
  useEffect(() => {
    if (!visible) {
      setSubIndex(0);
      return;
    }
    const id = setInterval(() => {
      setSubIndex((i) => (i + 1) % SUB_MESSAGES.length);
    }, 8000);
    return () => clearInterval(id);
  }, [visible]);

  if (!visible) return null;

  return (
    <View style={styles.fullScreen}>
      <Text style={styles.appName}>GradeAI</Text>
      <Text style={styles.mainStatus}>{message}</Text>
      <Text style={styles.subStatus}>{SUB_MESSAGES[subIndex]}</Text>
      <Text style={styles.helper}>This usually takes 30–60 seconds</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  fullScreen: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: COLORS.card,
    alignItems: "center",
    justifyContent: "center",
    zIndex: 1000,
    elevation: 1000,
  },
  appName: {
    fontSize: 18,
    fontWeight: FONT.medium,
    color: COLORS.primary,
    marginBottom: SPACING.xxl,
  },
  mainStatus: {
    fontSize: 18,
    fontWeight: FONT.medium,
    color: COLORS.textPrimary,
    textAlign: "center",
  },
  subStatus: {
    fontSize: 14,
    color: COLORS.textSecondary,
    textAlign: "center",
    marginTop: SPACING.sm,
  },
  helper: {
    position: "absolute",
    bottom: 40,
    fontSize: 12,
    color: COLORS.textTertiary,
    textAlign: "center",
  },
});
