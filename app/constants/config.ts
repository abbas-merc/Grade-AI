/**
 * constants/config.ts — App-wide configuration constants.
 *
 * BASE_URL is derived automatically in development from Expo's Metro bundler
 * hostUri so it tracks your PC's IP without any manual edits. In production
 * builds, set EXPO_PUBLIC_API_URL in your environment.
 */

import Constants from "expo-constants";

function getBaseUrl(): string {
  // expo-constants exposes the Metro bundler host, e.g. "192.168.68.59:8081".
  // The FastAPI backend runs on the same machine on port 8000.
  const hostUri = Constants.expoConfig?.hostUri ?? "";
  if (hostUri) {
    const host = hostUri.split(":")[0];
    return `http://${host}:8000`;
  }
  // Fallback for iOS Simulator / Android Emulator (no hostUri in those envs).
  return "http://localhost:8000";
}

export const BASE_URL = getBaseUrl();
export const GRADING_TIMEOUT_MS = 60000;

/** How often (ms) the result screen polls for grading completion. */
export const POLL_INTERVAL_MS = 2000;

/** Maximum number of poll attempts before giving up. */
export const MAX_POLL_ATTEMPTS = 30;
