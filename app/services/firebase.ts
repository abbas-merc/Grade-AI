/**
 * services/firebase.ts — Firebase initialization for GradeAI.
 *
 * @react-native-firebase initializes the default app NATIVELY at startup from
 * google-services.json (Android) / GoogleService-Info.plist (iOS). There is no
 * web-style initializeApp({ apiKey, ... }) call — that config is baked into the
 * native build. Here we just retrieve the already-initialized app and export
 * ready-to-use service instances.
 *
 * Use the @react-native-firebase modules for all auth/firestore work — never
 * the web `firebase` SDK, which is not compatible with these native modules.
 */

import { getApp } from "@react-native-firebase/app";
import auth from "@react-native-firebase/auth";
import firestore from "@react-native-firebase/firestore";

/** The default Firebase app (initialized natively from google-services.json). */
export const app = getApp();

/** Singleton Auth instance. */
export const authInstance = auth();

/** Singleton Firestore instance. */
export const firestoreInstance = firestore();

// Re-export the module factories so screens can also use the namespaced style,
// e.g. `auth().signOut()` or `firestore().collection(...)`.
export { auth, firestore };

/**
 * Map a Firebase auth error to a short, user-friendly message.
 * Firebase errors carry a `.code` like "auth/invalid-credential".
 */
export function authErrorMessage(error: unknown): string {
  const code = (error as { code?: string })?.code ?? "";
  switch (code) {
    case "auth/invalid-email":
      return "That email address is not valid.";
    case "auth/user-disabled":
      return "This account has been disabled.";
    case "auth/user-not-found":
    case "auth/wrong-password":
    case "auth/invalid-credential":
      return "Incorrect email or password.";
    case "auth/email-already-in-use":
      return "An account already exists for that email.";
    case "auth/weak-password":
      return "Password should be at least 6 characters.";
    case "auth/network-request-failed":
      return "Network error. Check your connection and try again.";
    case "auth/too-many-requests":
      return "Too many attempts. Please try again in a moment.";
    default:
      return (
        (error as { message?: string })?.message ??
        "Something went wrong. Please try again."
      );
  }
}
