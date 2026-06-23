/**
 * app/_layout.tsx — Root layout for expo-router.
 *
 * Wires Firebase auth state into navigation:
 *   - Subscribes to onAuthStateChanged on mount (fires immediately with the
 *     current state, then again on every sign-in / sign-out) and unsubscribes
 *     on unmount.
 *   - While the first auth check is in flight, shows a splash spinner so we
 *     don't flash the wrong screen.
 *   - Signed-out users are redirected to /auth/sign-in; signed-in users who
 *     are sitting on an auth screen are bounced back into the app.
 */

import { createContext, useCallback, useEffect, useState } from "react";
import { ActivityIndicator, View, StyleSheet } from "react-native";
import { Stack, useRouter, useSegments } from "expo-router";
import { StatusBar } from "expo-status-bar";
import * as Notifications from "expo-notifications";
import AsyncStorage from "@react-native-async-storage/async-storage";
import auth, { FirebaseAuthTypes } from "@react-native-firebase/auth";

import { COLORS, FONT } from "../constants/theme";
import { registerForPushNotifications } from "../services/pushNotifications";

/** AsyncStorage key recording that the one-time onboarding has been completed. */
export const ONBOARDING_COMPLETE_KEY = "onboarding_complete";

/**
 * Lets the onboarding screen notify the root layout that onboarding is done, so
 * the layout's cached flag updates immediately and its redirect effect doesn't
 * send the user straight back to /onboarding after "Get Started".
 */
export const OnboardingContext = createContext<{ complete: () => void }>({
  complete: () => {},
});

// Show notifications even while the app is foregrounded.
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: false,
    shouldSetBadge: false,
  }),
});

export default function RootLayout() {
  const [initializing, setInitializing] = useState(true);
  const [user, setUser] = useState<FirebaseAuthTypes.User | null>(null);
  const [onboardingComplete, setOnboardingComplete] = useState<boolean | null>(null);
  const segments = useSegments();
  const router = useRouter();

  // Subscribe once on mount. onAuthStateChanged returns an unsubscribe fn.
  useEffect(() => {
    const unsubscribe = auth().onAuthStateChanged((nextUser) => {
      setUser(nextUser);
      setInitializing(false);
    });
    return unsubscribe;
  }, []);

  // Load the one-time onboarding flag once on mount. Fail-open (treat as done)
  // so a storage error can never trap the user on the onboarding screen.
  useEffect(() => {
    AsyncStorage.getItem(ONBOARDING_COMPLETE_KEY)
      .then((value) => setOnboardingComplete(value === "true"))
      .catch(() => setOnboardingComplete(true));
  }, []);

  const completeOnboarding = useCallback(() => setOnboardingComplete(true), []);

  // Redirect whenever auth state, onboarding state, or the active route changes.
  useEffect(() => {
    if (initializing || onboardingComplete === null) return;
    const inAuthGroup = segments[0] === "auth";
    const onOnboarding = segments[0] === "onboarding";

    if (!user) {
      // Signed out → auth flow (unless already there).
      if (!inAuthGroup) router.replace("/auth/sign-in");
      return;
    }
    // Signed in but hasn't seen onboarding → show it once.
    if (!onboardingComplete) {
      if (!onOnboarding) router.replace("/onboarding");
      return;
    }
    // Signed in and onboarded → bounce out of auth/onboarding into the app.
    if (inAuthGroup || onOnboarding) router.replace("/");
  }, [user, initializing, onboardingComplete, segments, router]);

  // Once authenticated, register this device for push notifications so the
  // backend can alert the teacher when a grading job finishes.
  useEffect(() => {
    if (!user) return;
    registerForPushNotifications(user.uid);
  }, [user]);

  // Tapping a "Marking Complete" notification takes the teacher to the History
  // tab, where the finished result is now visible.
  useEffect(() => {
    const sub = Notifications.addNotificationResponseReceivedListener(() => {
      router.push({ pathname: "/", params: { tab: "history" } });
    });
    return () => sub.remove();
  }, [router]);

  if (initializing || onboardingComplete === null) {
    return (
      <View style={styles.splash}>
        <ActivityIndicator size="large" color={COLORS.primary} />
      </View>
    );
  }

  return (
    <OnboardingContext.Provider value={{ complete: completeOnboarding }}>
      <StatusBar style="auto" />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: COLORS.primary },
          headerTintColor: COLORS.card,
          headerTitleStyle: { fontWeight: FONT.medium, fontSize: 18 },
        }}
      >
        <Stack.Screen name="index" options={{ headerShown: false }} />
        <Stack.Screen name="paper/[id]" options={{ title: "Paper" }} />
        <Stack.Screen name="question/[id]" options={{ title: "Question" }} />
        <Stack.Screen name="result/[sessionId]" options={{ title: "Your Result" }} />
        <Stack.Screen name="capture/[paperId]" options={{ title: "Capture Pages" }} />
        <Stack.Screen name="results/paper" options={{ title: "Your Results" }} />
        <Stack.Screen name="generate-paper" options={{ title: "Create Paper" }} />
        <Stack.Screen name="generated-paper" options={{ title: "Your Paper" }} />
        <Stack.Screen name="paper-preview" options={{ headerShown: false }} />
        <Stack.Screen name="onboarding" options={{ headerShown: false }} />
        <Stack.Screen name="auth/sign-in" options={{ headerShown: false }} />
        <Stack.Screen name="auth/sign-up" options={{ headerShown: false }} />
      </Stack>
    </OnboardingContext.Provider>
  );
}

const styles = StyleSheet.create({
  splash: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: COLORS.surface,
  },
});
