// app/recipe/[id].tsx
import React from "react";
import { View, Text, ActivityIndicator, ScrollView, Pressable } from "react-native";
import { useLocalSearchParams, router, type Href } from "expo-router";
import { getRecipe, type RecipeDetail } from "../../src/recipesApi";
import { useAuthToken } from "../../src/useAuthToken";

export default function RecipeDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { token, loading: authLoading } = useAuthToken();
  const [data, setData] = React.useState<RecipeDetail | null>(null);
  const [busy, setBusy] = React.useState(true);
  const [err, setErr] = React.useState<string | null>(null);

  React.useEffect(() => {
    let alive = true;
    (async () => {
      try {
        if (!id) return;
        if (!token && !authLoading) {
          router.replace("/(auth)/login" as Href);
          return;
        }
        setBusy(true);
        const rec = await getRecipe(String(id));
        if (alive) setData(rec);
      } catch (e: any) {
        if (alive) setErr(e?.message || "Failed to load recipe");
      } finally {
        if (alive) setBusy(false);
      }
    })();
    return () => { alive = false; };
  }, [id, token, authLoading]);

  if (authLoading || busy) {
    return (
      <View style={{ flex: 1, justifyContent: "center", alignItems: "center", padding: 16 }}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  if (err) {
    return (
      <View style={{ flex: 1, padding: 16 }}>
        <Text style={{ color: "#ef4444", marginBottom: 12 }}>{err}</Text>
        <Pressable onPress={() => router.back()}>
          <Text style={{ color: "#2563eb", fontWeight: "700" }}>← Back</Text>
        </Pressable>
      </View>
    );
  }

  if (!data) return null;

  return (
    <ScrollView style={{ flex: 1, backgroundColor: "#f5f7fb" }} contentContainerStyle={{ padding: 16 }}>
      <Pressable onPress={() => router.back()} style={{ marginBottom: 10 }}>
        <Text style={{ color: "#2563eb", fontWeight: "700" }}>← Back</Text>
      </Pressable>

      <Text style={{ fontSize: 22, fontWeight: "800", marginBottom: 8 }}>
        {data.title || "(untitled recipe)"}
      </Text>
      <Text style={{ color: "#6b7280", marginBottom: 16 }}>ID: {data.id}</Text>

      <View style={{ backgroundColor: "#fff", borderRadius: 12, padding: 12, marginBottom: 14 }}>
        <Text style={{ fontWeight: "800", fontSize: 16, marginBottom: 6 }}>Ingredients</Text>
        {Array.isArray(data.ingredients) && data.ingredients.length > 0 ? (
          data.ingredients.map((t, i) => (
            <Text key={`ing-${i}`} style={{ marginBottom: 4 }}>• {t}</Text>
          ))
        ) : (
          <Text style={{ color: "#6b7280" }}>No ingredients available.</Text>
        )}
      </View>

      <View style={{ backgroundColor: "#fff", borderRadius: 12, padding: 12 }}>
        <Text style={{ fontWeight: "800", fontSize: 16, marginBottom: 6 }}>Directions</Text>
        {Array.isArray(data.directions) && data.directions.length > 0 ? (
          data.directions.map((t, i) => (
            <Text key={`step-${i}`} style={{ marginBottom: 8 }}>{i + 1}. {t}</Text>
          ))
        ) : (
          <Text style={{ color: "#6b7280" }}>No directions available.</Text>
        )}
      </View>
    </ScrollView>
  );
}
