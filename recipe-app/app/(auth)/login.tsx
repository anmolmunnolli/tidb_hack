// app/(auth)/login.tsx
import React, { useState } from "react";
import { View, Text, TextInput, Pressable, Alert } from "react-native";
import { useRouter, Link, type Href } from "expo-router";
import { loginUser } from "../../src/api";
import { setSession } from "../../src/auth";

export default function Login() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const onSubmit = async () => {
    const emailTrim = email.trim();
    if (!emailTrim || !password) {
      Alert.alert("Missing info", "Please enter email and password.");
      return;
    }

    try {
      setBusy(true);
      const { token, user } = await loginUser(emailTrim, password);

      // ✅ Save session in a cross-platform way (SecureStore on native, AsyncStorage on web)
      await setSession(token, user);
      const check = await (await import("../../src/auth")).getToken();
      console.log("[after-login] token len:", check?.length);
      // ✅ Go straight to Pantry
      router.replace("/(tabs)/pantry" as Href);
    } catch (e: any) {
      Alert.alert("Login failed", e?.message ?? "Try again");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={{ flex: 1, padding: 20, justifyContent: "center", gap: 12 }}>
      <Text style={{ fontSize: 24, fontWeight: "600", textAlign: "center" }}>
        Sign in
      </Text>

      <TextInput
        placeholder="Email"
        autoCapitalize="none"
        keyboardType="email-address"
        value={email}
        onChangeText={setEmail}
        autoCorrect={false}
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
          {busy ? "Signing in…" : "Login"}
        </Text>
      </Pressable>

      <Link
        href="/(auth)/register"
        style={{ textAlign: "center", color: "#2563eb", marginTop: 8 }}
      >
        Create an account
      </Link>
    </View>
  );
}
