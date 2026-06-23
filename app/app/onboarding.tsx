/**
 * app/onboarding.tsx — One-time onboarding shown after a teacher's first login.
 *
 * Three steps explain the core loop: generate a paper, download & print, mark
 * student responses. "Get Started" persists ONBOARDING_COMPLETE_KEY in
 * AsyncStorage (so it never shows again — even after sign-out/in) and enters the
 * app at the Papers tab ("/").
 *
 * The gate that decides whether to route here lives in app/_layout.tsx, which
 * also owns ONBOARDING_COMPLETE_KEY and the OnboardingContext used below to keep
 * the layout's cached flag in sync so it doesn't bounce the user back here.
 */

import React, { useContext } from "react";
import {
  View,
  Text,
  TouchableOpacity,
  ScrollView,
  StyleSheet,
} from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import AsyncStorage from "@react-native-async-storage/async-storage";

import { ONBOARDING_COMPLETE_KEY, OnboardingContext } from "./_layout";
import { COLORS, RADIUS, SPACING, FONT, ON } from "../constants/theme";

interface Step {
  glyph: string;
  title: string;
  description: string;
}

// Simple brand-coloured glyphs instead of an icon library (the app ships none):
// "+" = generate/add, "↓" = download, "✓" = mark. Crisp and cross-platform.
const STEPS: Step[] = [
  {
    glyph: "+",
    title: "Generate a Paper",
    description:
      "Choose topics and total marks. Grade AI compiles questions from real IGCSE past papers into a custom practice paper.",
  },
  {
    glyph: "↓",
    title: "Download and Print",
    description:
      "Download your question paper and mark scheme as PDFs. Print and distribute to your students.",
  },
  {
    glyph: "✓",
    title: "Mark Student Responses",
    description:
      "Photograph completed student scripts. Grade AI marks them instantly against your custom mark scheme.",
  },
];

export default function OnboardingScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { complete } = useContext(OnboardingContext);

  const onGetStarted = async () => {
    try {
      await AsyncStorage.setItem(ONBOARDING_COMPLETE_KEY, "true");
    } catch {
      // Non-fatal: worst case onboarding shows again on the next launch.
    }
    // Update the layout's cached flag BEFORE navigating so its redirect effect
    // doesn't send us straight back to /onboarding.
    complete();
    router.replace("/");
  };

  return (
    <View style={[styles.screen, { paddingTop: insets.top + SPACING.xxl }]}>
      <View style={styles.brand}>
        <Text style={styles.wordmark}>
          <Text style={styles.wordmarkLight}>Grade</Text>
          <Text style={styles.wordmarkBold}>AI</Text>
        </Text>
      </View>

      <Text style={styles.heading}>How it works</Text>

      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.steps}
        showsVerticalScrollIndicator={false}
      >
        {STEPS.map((step, i) => (
          <View key={step.title} style={styles.card}>
            <View style={styles.badge}>
              <Text style={styles.badgeGlyph}>{step.glyph}</Text>
            </View>
            <View style={styles.cardBody}>
              <Text style={styles.stepNumber}>STEP {i + 1}</Text>
              <Text style={styles.cardTitle}>{step.title}</Text>
              <Text style={styles.cardDescription}>{step.description}</Text>
            </View>
          </View>
        ))}
      </ScrollView>

      <TouchableOpacity
        style={[styles.button, { marginBottom: insets.bottom + SPACING.lg }]}
        onPress={onGetStarted}
        activeOpacity={0.85}
      >
        <Text style={styles.buttonText}>Get Started</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: COLORS.surface,
    paddingHorizontal: SPACING.xl,
  },
  brand: {
    alignItems: "center",
    marginBottom: SPACING.xl,
  },
  wordmark: {
    fontSize: 24,
  },
  wordmarkLight: {
    color: COLORS.textPrimary,
    fontSize: 24,
    fontWeight: FONT.regular,
  },
  wordmarkBold: {
    color: COLORS.primary,
    fontSize: 24,
    fontWeight: "700",
  },
  heading: {
    fontSize: 22,
    fontWeight: FONT.medium,
    color: COLORS.textPrimary,
    marginBottom: SPACING.lg,
  },
  scroll: {
    flex: 1,
  },
  steps: {
    gap: SPACING.md,
    paddingBottom: SPACING.lg,
  },
  card: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: SPACING.lg,
    backgroundColor: COLORS.card,
    borderRadius: RADIUS.xl,
    borderWidth: 1,
    borderColor: COLORS.border,
    padding: SPACING.lg,
  },
  badge: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: COLORS.primaryLight,
    alignItems: "center",
    justifyContent: "center",
  },
  badgeGlyph: {
    color: COLORS.primary,
    fontSize: 26,
    fontWeight: "700",
    lineHeight: 30,
  },
  cardBody: {
    flex: 1,
    gap: SPACING.xs,
  },
  stepNumber: {
    fontSize: 11,
    fontWeight: FONT.medium,
    color: COLORS.textTertiary,
    letterSpacing: 0.8,
  },
  cardTitle: {
    fontSize: 17,
    fontWeight: FONT.medium,
    color: COLORS.textPrimary,
  },
  cardDescription: {
    fontSize: 14,
    color: COLORS.textSecondary,
    lineHeight: 20,
  },
  button: {
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.lg,
    paddingVertical: SPACING.lg,
    alignItems: "center",
    marginTop: SPACING.md,
  },
  buttonText: {
    color: COLORS.card,
    fontSize: 16,
    fontWeight: FONT.medium,
  },
});
