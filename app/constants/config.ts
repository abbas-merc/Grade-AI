/**
 * constants/config.ts — App-wide configuration constants.
 *
 * BASE_URL is derived automatically from Expo's dev-server host so it never
 * needs manual updates when the PC's DHCP IP changes.
 *
 * Strategy:
 *   Expo's dev server always runs on the PC at the same IP the backend uses.
 *   Constants.expoConfig.hostUri gives "<ip>:<metro-port>" (e.g. "192.168.68.63:8081").
 *   We extract the IP part and point it at the backend port (8001).
 *
 *   Fallback: if hostUri is unavailable (production build, standalone app),
 *   we fall back to EXPO_PUBLIC_API_URL env var, then a hardcoded IP.
 */

import Constants from "expo-constants";

const BACKEND_PORT = 8001;

/**
 * Ensure a URL has an explicit scheme. EAS env vars are sometimes set without
 * one (e.g. "grade-ai-production.up.railway.app"), which axios treats as an
 * invalid/relative URL and every request silently fails. Default to https.
 */
function withScheme(url: string): string {
  const trimmed = url.trim().replace(/\/+$/, ""); // drop trailing slashes
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  return `https://${trimmed}`;
}

function getBaseUrl(): string {
  // 1. Explicit override via env var. Set in eas.json for preview/production
  //    builds, so it must take priority — a release build has no Metro host to
  //    fall back on. Checked first so production never accidentally uses a LAN IP.
  const envUrl = process.env.EXPO_PUBLIC_API_URL;
  if (envUrl && envUrl.trim()) return withScheme(envUrl);

  // 2. Dev convenience: derive the IP from Expo's dev-server host (the same
  //    machine runs both Metro + FastAPI), so the LAN IP never needs editing.
  const hostUri = Constants.expoConfig?.hostUri;
  if (hostUri) {
    const ip = hostUri.split(":")[0];
    if (ip) return `http://${ip}:${BACKEND_PORT}`;
  }

  // 3. Last-resort hardcoded fallback — update if the above mechanisms fail.
  return `http://192.168.68.62:${BACKEND_PORT}`;
}

export const BASE_URL = getBaseUrl();
export const GRADING_TIMEOUT_MS = 60000;

/** How often (ms) the result screen polls for grading completion. */
export const POLL_INTERVAL_MS = 2000;

/** Maximum number of poll attempts before giving up.
 *  120 × 2000ms = 4 minutes — enough for the largest paper-grading jobs. */
export const MAX_POLL_ATTEMPTS = 120;
