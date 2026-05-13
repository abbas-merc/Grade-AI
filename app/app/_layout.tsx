/**
 * app/_layout.tsx — Root layout for expo-router.
 * Sets up the Stack navigator used across all screens.
 */

import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";

export default function RootLayout() {
  return (
    <>
      <StatusBar style="auto" />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: "#4F46E5" },
          headerTintColor: "#fff",
          headerTitleStyle: { fontWeight: "bold" },
        }}
      >
        <Stack.Screen name="index" options={{ title: "GradeAI" }} />
        <Stack.Screen name="paper/[id]" options={{ title: "Paper" }} />
        <Stack.Screen name="question/[id]" options={{ title: "Question" }} />
        <Stack.Screen name="result/[sessionId]" options={{ title: "Your Result" }} />
        <Stack.Screen name="capture/[paperId]" options={{ title: "Capture Pages" }} />
        <Stack.Screen name="results/paper" options={{ title: "Your Results" }} />
      </Stack>
    </>
  );
}
