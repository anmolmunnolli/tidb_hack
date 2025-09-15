// app/(tabs)/plan.tsx
import React, { useMemo, useState } from "react";
import {
  View, Text, TextInput, Pressable, ActivityIndicator, FlatList, Alert, ScrollView, Modal,
} from "react-native";
import { router, type Href } from "expo-router";
import { recommendMeals, type RecItem } from "../../src/recommendApi";
import { useAuthToken } from "../../src/useAuthToken";
import { addToMealPlan } from "../../src/planApi";

const Pill = ({ text, tone = "#111827" }: { text: string; tone?: string }) => (
  <View style={{ backgroundColor: tone, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999 }}>
    <Text style={{ color: "#fff", fontWeight: "700" }}>{text}</Text>
  </View>
);

type PendingAdd = {
  id: string;
  title?: string | null;
};

function todayYYYYMMDD() {
  const d = new Date();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

export default function PlanScreen() {
  const { token, loading: authLoading } = useAuthToken();
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [items, setItems] = useState<RecItem[]>([]);

  // modal state
  const [showConfirm, setShowConfirm] = useState(false);
  const [pending, setPending] = useState<PendingAdd | null>(null);
  const [servings, setServings] = useState<string>("2");
  const [plannedFor, setPlannedFor] = useState<string>(todayYYYYMMDD());
  const [slot, setSlot] = useState<string>("dinner");
  const [notes, setNotes] = useState<string>("");

  const canSubmit = useMemo(() => {
    return !!pending?.id && /^\d{4}-\d{2}-\d{2}$/.test(plannedFor);
  }, [pending, plannedFor]);

  async function onRun() {
    const q = query.trim();
    if (!q) {
      Alert.alert("Enter something", "Try: ‘light indian potato dinner’");
      return;
    }
    try {
      setBusy(true);
      const res = await recommendMeals({
        query: q,
        k: 10,
        m: 100,
        w1_query: 0.55,
        w2_overlap: 0.25,
        w3_cover: 0.20,
        min_cover: 0.0,
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

  function openConfirm(rec: RecItem) {
    setPending({ id: String(rec.id), title: rec.title });
    setServings("2");
    setPlannedFor(todayYYYYMMDD());
    setSlot("dinner");
    setNotes("");
    setShowConfirm(true);
  }

  async function confirmAdd() {
    if (!canSubmit || !pending) return;
    try {
      const s = servings.trim() ? parseInt(servings.trim(), 10) : undefined;
      await addToMealPlan({
        recipe_id: pending.id,
        servings: Number.isFinite(s as any) ? s : undefined,
        planned_for: plannedFor,
        slot,
        notes: notes.trim() || undefined,
      });
      setShowConfirm(false);
      Alert.alert("Saved", "Added to your meal plan!", [
        { text: "View plan", onPress: () => router.push("/meal-plan" as Href) },
        { text: "OK" },
      ]);
    } catch (e: any) {
      Alert.alert("Oops", e?.message ?? "Could not save");
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
        returnKeyType="search"
        onSubmitEditing={onRun}
      />

      <View style={{ flexDirection: "row", gap: 10, marginTop: 10 }}>
        <Pressable
          onPress={onRun}
          disabled={busy}
          style={{ backgroundColor: "#111827", paddingVertical: 12, paddingHorizontal: 16, borderRadius: 12, opacity: busy ? 0.6 : 1 }}
        >
          <Text style={{ color: "#fff", fontWeight: "700" }}>{busy ? "Searching…" : "Get ideas"}</Text>
        </Pressable>

        <Pressable
          onPress={() => router.push("/meal-plan" as Href)}
          style={{ backgroundColor: "#2563eb", paddingVertical: 12, paddingHorizontal: 16, borderRadius: 12 }}
        >
          <Text style={{ color: "#fff", fontWeight: "700" }}>My Meal Plan</Text>
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
          contentContainerStyle={{ paddingBottom: 80 }}
          renderItem={({ item }) => {
            const title = item.title || "(untitled recipe)";
            const onView = () =>
              router.push({ pathname: "/recipe/[id]", params: { id: String(item.id) } } as Href);

            return (
              <Pressable
                onPress={onView}
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
                {/* Header row: title + actions */}
                <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                  <Text style={{ fontWeight: "800", fontSize: 16, flexShrink: 1, marginRight: 8 }} numberOfLines={2}>
                    {title}
                  </Text>
                  <View style={{ flexDirection: "row", gap: 8 }}>
                    <Pressable
                      onPress={onView}
                      style={{ backgroundColor: "#2563eb", paddingVertical: 8, paddingHorizontal: 12, borderRadius: 10 }}
                    >
                      <Text style={{ color: "#fff", fontWeight: "700" }}>View</Text>
                    </Pressable>
                    <Pressable
                      onPress={() => openConfirm(item)}
                      style={{ backgroundColor: "#10b981", paddingVertical: 8, paddingHorizontal: 12, borderRadius: 10 }}
                    >
                      <Text style={{ color: "#fff", fontWeight: "700" }}>Add to plan</Text>
                    </Pressable>
                  </View>
                </View>

                {/* Scores row */}
                <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 10, marginBottom: 8 }}>
                  <Pill text={`score ${item.final?.toFixed(2) ?? "-"}`} tone="#111827" />
                  <Pill text={`query ${item.query_score?.toFixed(2) ?? "-"}`} tone="#2563eb" />
                  <Pill text={`overlap ${item.overlap_score?.toFixed(2) ?? "-"}`} tone="#059669" />
                  <Pill text={`cover ${item.cover_score?.toFixed(2) ?? "-"}`} tone="#7c3aed" />
                </View>

                {/* Pantry explainers */}
                {(item.used_from_pantry?.length || item.missing?.length) ? (
                  <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: 4 }} contentContainerStyle={{ paddingRight: 2 }}>
                    <View style={{ flexDirection: "row", gap: 6 }}>
                      {item.used_from_pantry?.map((t, i) => <Pill key={`u-${item.id}-${i}`} text={t} tone="#16a34a" />)}
                      {item.missing?.map((t, i) => <Pill key={`m-${item.id}-${i}`} text={t} tone="#9ca3af" />)}
                    </View>
                  </ScrollView>
                ) : null}

                {/* Distance (debug) */}
                <Text style={{ color: "#6b7280", marginTop: 8 }}>
                  dist: {typeof item.dist === "number" ? item.dist.toFixed(4) : String(item.dist)}
                </Text>
              </Pressable>
            );
          }}
          ListEmptyComponent={<Text style={{ color: "#6b7280", textAlign: "center", marginTop: 20 }}>No ideas yet — try a different prompt.</Text>}
        />
      )}

      {/* Confirm modal */}
      <Modal visible={showConfirm} animationType="slide" transparent onRequestClose={() => setShowConfirm(false)}>
        <View style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.35)", justifyContent: "flex-end" }}>
          <View style={{ backgroundColor: "#fff", padding: 16, borderTopLeftRadius: 16, borderTopRightRadius: 16 }}>
            <Text style={{ fontSize: 16, fontWeight: "800", marginBottom: 12 }}>
              Add to meal plan{pending?.title ? `: ${pending.title}` : ""}
            </Text>

            <Text style={{ fontWeight: "700" }}>Servings</Text>
            <TextInput
              value={servings}
              onChangeText={setServings}
              keyboardType="numeric"
              placeholder="2"
              style={{ borderWidth: 1, borderColor: "#e5e7eb", borderRadius: 10, padding: 10, marginTop: 6, marginBottom: 10 }}
            />

            <Text style={{ fontWeight: "700" }}>Date (YYYY-MM-DD)</Text>
            <TextInput
              value={plannedFor}
              onChangeText={setPlannedFor}
              placeholder="2025-09-01"
              style={{ borderWidth: 1, borderColor: "#e5e7eb", borderRadius: 10, padding: 10, marginTop: 6, marginBottom: 10 }}
            />

            <Text style={{ fontWeight: "700" }}>Meal</Text>
            <TextInput
              value={slot}
              onChangeText={setSlot}
              placeholder="dinner"
              style={{ borderWidth: 1, borderColor: "#e5e7eb", borderRadius: 10, padding: 10, marginTop: 6, marginBottom: 10 }}
            />

            <Text style={{ fontWeight: "700" }}>Notes</Text>
            <TextInput
              value={notes}
              onChangeText={setNotes}
              placeholder="optional"
              multiline
              style={{ borderWidth: 1, borderColor: "#e5e7eb", borderRadius: 10, padding: 10, marginTop: 6, marginBottom: 16, minHeight: 70 }}
            />

            <View style={{ flexDirection: "row", justifyContent: "flex-end", gap: 10 }}>
              <Pressable onPress={() => setShowConfirm(false)} style={{ paddingVertical: 10, paddingHorizontal: 14 }}>
                <Text style={{ fontWeight: "700" }}>Cancel</Text>
              </Pressable>
              <Pressable
                onPress={confirmAdd}
                disabled={!canSubmit}
                style={{ backgroundColor: canSubmit ? "#111827" : "#9ca3af", paddingVertical: 10, paddingHorizontal: 14, borderRadius: 10 }}
              >
                <Text style={{ color: "#fff", fontWeight: "700" }}>Add</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}
