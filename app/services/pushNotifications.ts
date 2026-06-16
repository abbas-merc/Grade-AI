/**
 * services/pushNotifications.ts — Expo push token registration.
 *
 * Requests notification permission, obtains the Expo push token, and stores it
 * at teachers/{uid}.pushToken so the backend can notify the teacher when a
 * grading job completes. All failures are logged and swallowed — push is a
 * convenience, never a blocker for using the app.
 */

import { Platform } from "react-native";
import Constants from "expo-constants";
import * as Notifications from "expo-notifications";
import firestore from "@react-native-firebase/firestore";

/**
 * Request permission, fetch the Expo push token, and persist it to Firestore
 * under teachers/{uid}.pushToken. No-op (logged) if permission is denied or a
 * token can't be obtained.
 */
export async function registerForPushNotifications(uid: string): Promise<void> {
  try {
    // Android requires a channel for notifications to be delivered.
    if (Platform.OS === "android") {
      await Notifications.setNotificationChannelAsync("default", {
        name: "default",
        importance: Notifications.AndroidImportance.DEFAULT,
      });
    }

    const existing = await Notifications.getPermissionsAsync();
    let granted = existing.granted;
    if (!granted) {
      const requested = await Notifications.requestPermissionsAsync();
      granted = requested.granted;
    }
    if (!granted) {
      console.log("[push] notification permission not granted");
      return;
    }

    const projectId =
      Constants.expoConfig?.extra?.eas?.projectId ??
      (Constants as any)?.easConfig?.projectId;

    const tokenResponse = await Notifications.getExpoPushTokenAsync(
      projectId ? { projectId } : undefined
    );
    const token = tokenResponse.data;
    if (!token) {
      console.log("[push] no Expo push token returned");
      return;
    }

    await firestore()
      .collection("teachers")
      .doc(uid)
      .set({ pushToken: token }, { merge: true });
    console.log("[push] push token saved for uid", uid);
  } catch (err) {
    console.error("[push] registration failed", err);
  }
}
