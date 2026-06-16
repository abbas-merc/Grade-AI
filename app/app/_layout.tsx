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

import { useEffect, useState } from "react";
import { ActivityIndicator, View, StyleSheet } from "react-native";
import { Stack, useRouter, useSegments } from "expo-router";
import { StatusBar } from "expo-status-bar";
import * as Notifications from "expo-notifications";
import auth, { FirebaseAuthTypes } from "@react-native-firebase/auth";

import { COLORS, FONT } from "../constants/theme";
import { registerForPushNotifications } from "../services/pushNotifications";

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

  // Redirect whenever auth state or the active route group changes.
  useEffect(() => {
    if (initializing) return;
    const inAuthGroup = segments[0] === "auth";
    if (!user && !inAuthGroup) {
      router.replace("/auth/sign-in");
    } else if (user && inAuthGroup) {
      router.replace("/");
    }
  }, [user, initializing, segments, router]);

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

  if (initializing) {
    return (
      <View style={styles.splash}>
        <ActivityIndicator size="large" color={COLORS.primary} />
      </View>
    );
  }

  return (
    <>
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
        <Stack.Screen name="auth/sign-in" options={{ headerShown: false }} />
        <Stack.Screen name="auth/sign-up" options={{ headerShown: false }} />
      </Stack>
    </>
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
