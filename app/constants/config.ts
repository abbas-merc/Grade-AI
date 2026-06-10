/**
 * constants/config.ts — App-wide configuration constants.
 *
 * BASE_URL resolution (deliberately does NOT use Constants.isDevice, which is
 * unreliable on Android in SDK 54 and often returns undefined):
 *
 *   Android (emulator OR real device) → localhost, tunneled to the PC by
 *     `adb reverse tcp:8000 tcp:8000`. adb reverse works for both, so the same
 *     URL is correct in every Android case. No firewall or same-WiFi needed.
 *   iOS → the dev PC's LAN IP (no adb reverse on iOS). For the iOS simulator
 *     localhost would also work, but the LAN IP works for both simulator and
 *     a real iOS device, so we use it uniformly.
 *
 * Requirement for Android: run `adb reverse tcp:8000 tcp:8000` once per device
 * connection (it is cleared on unplug/reboot/adb restart).
 */

import { Platform } from "react-native";

/**
 * LAN IP of the development PC running the FastAPI backend. Used by iOS.
 * Update this if the PC's IP changes (run `ipconfig` and read the IPv4 address).
 */
const DEV_PC_LAN_IP = "192.168.68.53";
const BACKEND_PORT = 8000;

function getBaseUrl(): string {
  // Android: localhost reaches the PC's backend via `adb reverse`, which works
  // identically for emulators and USB-tethered real devices.
  if (Platform.OS === "android") {
    return `http://localhost:${BACKEND_PORT}`;
  }

  // iOS (simulator or real device): reach the PC over WiFi via its LAN IP.
  return `http://${DEV_PC_LAN_IP}:${BACKEND_PORT}`;
}

export const BASE_URL = getBaseUrl();
export const GRADING_TIMEOUT_MS = 60000;

/** How often (ms) the result screen polls for grading completion. */
export const POLL_INTERVAL_MS = 2000;

/** Maximum number of poll attempts before giving up.
 *  120 × 2000ms = 4 minutes — enough for the largest paper-grading jobs. */
export const MAX_POLL_ATTEMPTS = 120;
