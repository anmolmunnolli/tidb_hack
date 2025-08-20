// app/(auth)/register.tsx
import React, { useState } from "react";
import { View, Text, TextInput, Pressable, Alert } from "react-native";
import { useRouter, Link } from "expo-router";
import * as SecureStore from "expo-secure-store";
import { registerUser } from "../../src/api";

export default function Register() {
  const router = useRouter();
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const onSubmit = async () => {
    const first_name = first.trim();
    const last_name = last.trim();
    const email_trim = email.trim();

    if (!first_name || !last_name || !email_trim || !password) {
      Alert.alert("Missing info", "Please fill all fields.");
      return;
    }

    try {
      setBusy(true);

      // Call your API to create the account
      await registerUser({ first_name, last_name, email: email_trim, password });

      // Make sure no stale token keeps the app in an authenticated state
      try {
        await SecureStore.deleteItemAsync("token");
        await SecureStore.deleteItemAsync("user");
      } catch {}

      Alert.alert("Account created", "Please sign in with your new credentials.", [
        {
          text: "Go to Login",
          onPress: () => router.replace("/(auth)/login"),
        },
      ]);

      // Fallback in case the user dismisses the alert without tapping the button
      setTimeout(() => router.replace("/(auth)/login"), 300);
    } catch (e: any) {
      Alert.alert("Registration failed", e?.message ?? "Please try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={{ flex: 1, padding: 20, justifyContent: "center", gap: 12 }}>
      <Text style={{ fontSize: 24, fontWeight: "600", textAlign: "center" }}>
        Create account
      </Text>

      <TextInput
        placeholder="First name"
        value={first}
        onChangeText={setFirst}
        autoCapitalize="words"
        style={{ borderWidth: 1, borderColor: "#ccc", borderRadius: 8, padding: 12 }}
      />
      <TextInput
        placeholder="Last name"
        value={last}
        onChangeText={setLast}
        autoCapitalize="words"
        style={{ borderWidth: 1, borderColor: "#ccc", borderRadius: 8, padding: 12 }}
      />
      <TextInput
        placeholder="Email"
        autoCapitalize="none"
        keyboardType="email-address"
        value={email}
        onChangeText={setEmail}
        style={{ borderWidth: 1, borderColor: "#ccc", borderRadius: 8, padding: 12 }}
      />
      <TextInput
        placeholder="Password"
        secureTextEntry
        value={password}
        onChangeText={setPassword}
        style={{ borderWidth: 1, borderColor: "#ccc", borderRadius: 8, padding: 12 }}
      />

      <Pressable
        onPress={onSubmit}
        disabled={busy}
        style={{
          backgroundColor: "#111827",
          padding: 14,
          borderRadius: 8,
          opacity: busy ? 0.6 : 1,
        }}
      >
        <Text style={{ color: "#fff", textAlign: "center", fontWeight: "600" }}>
          {busy ? "Creating..." : "Register"}
        </Text>
      </Pressable>

      <Link href="/(auth)/login" style={{ textAlign: "center", color: "#2563eb", marginTop: 8 }}>
        Back to login
      </Link>
    </View>
  );
}
