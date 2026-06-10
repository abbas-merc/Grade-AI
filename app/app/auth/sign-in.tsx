/**
 * app/auth/sign-in.tsx — Email/password sign in.
 *
 * On success the root layout's onAuthStateChanged listener (app/_layout.tsx)
 * detects the new user and redirects into the app, so no manual navigation
 * is needed here.
 */

import { useState } from "react";
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
} from "react-native";
import { Link } from "expo-router";

import { auth, authErrorMessage } from "../../services/firebase";

export default function SignInScreen() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSignIn = async () => {
    setError(null);
    if (!email.trim() || !password) {
      setError("Please enter both your email and password.");
      return;
    }
    setLoading(true);
    try {
      await auth().signInWithEmailAndPassword(email.trim(), password);
      // Auth listener in app/_layout.tsx redirects into the app on success.
    } catch (e) {
      setError(authErrorMessage(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <View style={styles.inner}>
        <Text style={styles.title}>Welcome back</Text>
        <Text style={styles.subtitle}>Sign in to continue to GradeAI</Text>

        <TextInput
          style={styles.input}
          placeholder="Email"
          placeholderTextColor="#9CA3AF"
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="email-address"
          autoComplete="email"
          value={email}
          onChangeText={setEmail}
          editable={!loading}
        />
        <TextInput
          style={styles.input}
          placeholder="Password"
          placeholderTextColor="#9CA3AF"
          secureTextEntry
          autoCapitalize="none"
          autoComplete="password"
          value={password}
          onChangeText={setPassword}
          editable={!loading}
        />

        {error ? <Text style={styles.error}>{error}</Text> : null}

        <TouchableOpacity
          style={[styles.button, loading && styles.buttonDisabled]}
          onPress={handleSignIn}
          disabled={loading}
          activeOpacity={0.85}
        >
          {loading ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <Text style={styles.buttonText}>Sign In</Text>
          )}
        </TouchableOpacity>

        <View style={styles.footer}>
          <Text style={styles.footerText}>Don&apos;t have an account? </Text>
          <Link href="/auth/sign-up" style={styles.link}>
            Sign up
          </Link>
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#F9FAFB",
  },
  inner: {
    flex: 1,
    justifyContent: "center",
    paddingHorizontal: 24,
    gap: 14,
  },
  title: {
    fontSize: 26,
    fontWeight: "700",
    color: "#1F2937",
  },
  subtitle: {
    fontSize: 15,
    color: "#6B7280",
    marginBottom: 8,
  },
  input: {
    backgroundColor: "#fff",
    borderWidth: 1,
    borderColor: "#E5E7EB",
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 16,
    color: "#1F2937",
  },
  error: {
    color: "#DC2626",
    fontSize: 14,
  },
  button: {
    backgroundColor: "#4F46E5",
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: "center",
    marginTop: 4,
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  buttonText: {
    color: "#fff",
    fontSize: 16,
    fontWeight: "700",
  },
  footer: {
    flexDirection: "row",
    justifyContent: "center",
    marginTop: 8,
  },
  footerText: {
    color: "#6B7280",
    fontSize: 14,
  },
  link: {
    color: "#4F46E5",
    fontSize: 14,
    fontWeight: "600",
  },
});
