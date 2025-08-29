// app/(tabs)/plan.tsx
import React, { useState } from "react";
import {
  View,
  Text,
  TextInput,
  Pressable,
  ActivityIndicator,
  FlatList,
  Alert,
  ScrollView,
} from "react-native";
import { router, type Href } from "expo-router";
import { recommendMeals, type RecItem } from "../../src/recommendApi";
import { useAuthToken } from "../../src/useAuthToken";

const Pill = ({ text, tone = "#111827" }: { text: string; tone?: string }) => (
  <View style={{ backgroundColor: tone, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999 }}>
    <Text style={{ color: "#fff", fontWeight: "700" }}>{text}</Text>
  </View>
);

export default function PlanScreen() {
  const { token, loading: authLoading } = useAuthToken();
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [items, setItems] = useState<RecItem[]>([]);

  async function onRun() {
    const q = query.trim();
    if (!q) {
      Alert.alert("Enter something", "Try: ‘light indian potato dinner’");
      return;
    }
    try {
      setBusy(true);
      // sensible defaults: pull 100, re-rank, return 10
      const res = await recommendMeals({
        query: q,
        k: 10,
        m: 100,
        w1_query: 0.55,
        w2_overlap: 0.25,
        w3_cover: 0.20,
        min_cover: 0.0, // set to e.g. 0.2 to require at least 20% coverage
      });
      setItems(res);
    } catch (e: any) {
      if (String(e?.message).toLowerCase().includes("token")) {
        Alert.alert("Please sign in", "Your session expired. Sign in again.", [
          { text: "OK", onPress: () => router.replace("/(auth)/login" as Href) },
        ]);
        return;
      }
      Alert.alert("Error", e?.message ?? "Failed to get recommendations");
    } finally {
      setBusy(false);
    }
  }

  if (authLoading) {
    return (
      <View style={{ flex: 1, justifyContent: "center", alignItems: "center" }}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  if (!token) {
    router.replace("/(auth)/login" as Href);
    return null;
  }

  return (
    <View style={{ flex: 1, backgroundColor: "#f5f7fb", padding: 16 }}>
      <Text style={{ fontSize: 22, fontWeight: "800", marginBottom: 10 }}>🍽️ Meal Planner</Text>

      <TextInput
        placeholder="Describe what you want (e.g., 'quick indian veg for 2 with potatoes')"
        value={query}
        onChangeText={setQuery}
        style={{ borderWidth: 1, borderColor: "#e5e7eb", borderRadius: 12, padding: 12, backgroundColor: "#fff" }}
      />

      <View style={{ flexDirection: "row", gap: 10, marginTop: 10 }}>
        <Pressable
          onPress={onRun}
          disabled={busy}
          style={{ backgroundColor: "#111827", paddingVertical: 12, paddingHorizontal: 16, borderRadius: 12, opacity: busy ? 0.6 : 1 }}
        >
          <Text style={{ color: "#fff", fontWeight: "700" }}>{busy ? "Searching…" : "Get ideas"}</Text>
        </Pressable>
      </View>

      {busy ? (
        <View style={{ marginTop: 20 }}>
          <ActivityIndicator />
        </View>
      ) : (
        <FlatList
          style={{ marginTop: 14 }}
          data={items}
          keyExtractor={(x) => String(x.id)}
          renderItem={({ item }) => (
            <View
              style={{
                backgroundColor: "#fff",
                borderRadius: 16,
                padding: 14,
                marginBottom: 12,
                shadowColor: "#000",
                shadowOpacity: 0.06,
                shadowRadius: 10,
                elevation: 2,
              }}
            >
              <Text style={{ fontWeight: "800", fontSize: 16, marginBottom: 6 }}>
                {item.title || "(untitled recipe)"}
              </Text>

              {/* Scores row */}
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
                <Pill text={`score ${item.final?.toFixed(2) ?? "-"}`} tone="#111827" />
                <Pill text={`query ${item.query_score?.toFixed(2) ?? "-"}`} tone="#2563eb" />
                <Pill text={`overlap ${item.overlap_score?.toFixed(2) ?? "-"}`} tone="#059669" />
                <Pill text={`cover ${item.cover_score?.toFixed(2) ?? "-"}`} tone="#7c3aed" />
              </View>

              {/* Pantry explainers */}
              {(item.used_from_pantry?.length || item.missing?.length) ? (
                <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: 4 }}>
                  <View style={{ flexDirection: "row", gap: 6 }}>
                    {item.used_from_pantry?.map((t, i) => (
                      <Pill key={`u-${item.id}-${i}`} text={t} tone="#16a34a" />
                    ))}
                    {item.missing?.map((t, i) => (
                      <Pill key={`m-${item.id}-${i}`} text={t} tone="#9ca3af" />
                    ))}
                  </View>
                </ScrollView>
              ) : null}

              {/* Distance for debugging */}
              <Text style={{ color: "#6b7280", marginTop: 6 }}>dist: {item.dist?.toFixed?.(4) ?? String(item.dist)}</Text>
            </View>
          )}
          ListEmptyComponent={
            <Text style={{ color: "#6b7280", textAlign: "center", marginTop: 20 }}>
              No ideas yet — try a different prompt.
            </Text>
          }
        />
      )}
    </View>
  );
}
