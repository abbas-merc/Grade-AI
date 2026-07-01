/**
 * constants/config.ts — App-wide configuration constants.
 *
 * BASE_URL resolves to the always-on Railway backend by DEFAULT, in every mode
 * (dev, Expo Go, preview, production). This is deliberate: the app must load
 * reliably any time it is opened — cold start, after a kill, on cellular, days
 * later — with zero dependency on the developer's PC being awake, on the same
 * WiFi, or running a local server. A LAN address can never satisfy that, so it
 * is no longer the default; it is an explicit opt-in for backend development.
 *
 * Resolution order:
 *   1. EXPO_PUBLIC_API_URL env var — highest priority. EAS preview/production
 *      builds inject the Railway URL here; a developer can also point it at a
 *      local backend (e.g. "http://192.168.x.x:8001") when testing.
 *   2. EXPO_PUBLIC_USE_LAN=1 — opt-in dev convenience: derive the PC's IP from
 *      Expo's Metro host and talk to the local FastAPI on port 8001.
 *   3. Default: the deployed Railway backend. Works anywhere with internet.
 */

import Constants from "expo-constants";

const BACKEND_PORT = 8001;

/**
 * The deployed, always-on backend. This is the reliable default so the app
 * NEVER falls back to an unreachable LAN IP (the historical cause of the
 * intermittent "network error — is the server running?" on cold start).
 */
export const PRODUCTION_API_URL = "https://grade-ai-production.up.railway.app";

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
  //    builds, so it must take priority. A developer can also set it locally to
  //    a "http://<pc-ip>:8001" URL to test against a local backend.
  const envUrl = process.env.EXPO_PUBLIC_API_URL;
  if (envUrl && envUrl.trim()) return withScheme(envUrl);

  // 2. Opt-in local backend for on-device backend development: derive the PC's
  //    IP from Expo's Metro host (same machine runs Metro + FastAPI). Only used
  //    when EXPO_PUBLIC_USE_LAN=1 is set, so it can never silently break a demo.
  if (process.env.EXPO_PUBLIC_USE_LAN === "1") {
    const hostUri = Constants.expoConfig?.hostUri;
    const ip = hostUri?.split(":")[0];
    if (ip) return `http://${ip}:${BACKEND_PORT}`;
  }

  // 3. Default: the always-on Railway backend. Reachable from anywhere with
  //    internet, with no dependency on the dev PC — so the app loads reliably
  //    every time it is opened.
  return PRODUCTION_API_URL;
}

export const BASE_URL = getBaseUrl();
export const GRADING_TIMEOUT_MS = 60000;

/** How often (ms) the result screen polls for grading completion. */
export const POLL_INTERVAL_MS = 2000;

/** Maximum number of poll attempts before giving up.
 *  120 × 2000ms = 4 minutes — enough for the largest paper-grading jobs. */
export const MAX_POLL_ATTEMPTS = 120;
