// app/(tabs)/meal-plan.tsx
import React, { useCallback, useMemo, useState } from "react";
import { View, Text, ActivityIndicator, FlatList, Pressable, Alert } from "react-native";
import { useFocusEffect, router, type Href } from "expo-router";
import { deleteMealPlanItem, listMealPlan, type MealPlanItem, cookMealPlanItem } from "../../src/planApi";

type Row = MealPlanItem;

export default function MealPlanScreen() {
  const [items, setItems] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const raw = await listMealPlan();

      // Deduplicate by recipe_id (keep most recent)
      const byRecipe = new Map<string, Row>();
      for (const r of raw) {
        const key = String(r.recipe_id);
        const prev = byRecipe.get(key);
        if (!prev) byRecipe.set(key, r);
        else {
          const pa = new Date(prev.created_at ?? 0).getTime();
          const pb = new Date(r.created_at ?? 0).getTime();
          if (pb >= pa) byRecipe.set(key, r);
        }
      }
      const deduped = Array.from(byRecipe.values());

      // Sort: planned_for desc, then created_at desc
      deduped.sort((a, b) => {
        if ((a.planned_for ?? "") !== (b.planned_for ?? "")) {
          return (a.planned_for ?? "") < (b.planned_for ?? "") ? 1 : -1;
        }
        return new Date(b.created_at ?? 0).getTime() - new Date(a.created_at ?? 0).getTime();
      });

      setItems(deduped);
    } catch (e: any) {
      Alert.alert("Error", e?.message ?? "Failed to load meal plan");
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const grouped = useMemo(() => {
    const map = new Map<string, Row[]>();
    for (const r of items) {
      const key = r.planned_for || "Unscheduled";
      const arr = map.get(key) || [];
      arr.push(r);
      map.set(key, arr);
    }
    const keys = Array.from(map.keys()).sort((a, b) => {
      if (a === "Unscheduled") return 1;
      if (b === "Unscheduled") return -1;
      return a < b ? 1 : -1;
    });
    return keys.map((k) => ({ date: k, rows: map.get(k)! }));
  }, [items]);

  async function onDelete(id: string | number) {
    try {
      await deleteMealPlanItem(id);
      await load();
    } catch (e: any) {
      Alert.alert("Oops", e?.message ?? "Could not delete");
    }
  }

  async function onCook(planId: string | number) {
    try {
      console.log("[cook] calling /api/mealplan/%s/cook", planId);
      const res = await cookMealPlanItem(planId); // <— MUST be the meal_plan.id
      console.log("[cook] result", res);
      Alert.alert("Cooked ✅", "Pantry deducted for this recipe.");
      await load();
    } catch (e: any) {
      console.warn("[cook] error", e);
      Alert.alert("Cook failed", e?.message ?? "Could not deduct pantry");
    }
  }

  if (loading) {
    return (
      <View style={{ flex: 1, justifyContent: "center", alignItems: "center" }}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  return (
    <FlatList
      contentContainerStyle={{ padding: 16 }}
      data={grouped}
      keyExtractor={(g) => g.date}
      renderItem={({ item: group }) => (
        <View style={{ marginBottom: 24 }}>
          <Text style={{ fontSize: 18, fontWeight: "800", marginBottom: 8 }}>{group.date}</Text>

          {group.rows.map((r) => (
            <View key={`${group.date}-${r.id}`} style={{
              backgroundColor: "#fff", borderRadius: 16, padding: 14, marginBottom: 10,
              shadowColor: "#000", shadowOpacity: 0.06, shadowRadius: 10, elevation: 2,
            }}>
              <Text style={{ fontWeight: "800", fontSize: 16, marginBottom: 6 }}>
                {r.title || "(untitled recipe)"}
              </Text>

              <Text style={{ color: "#6b7280", marginBottom: 8 }}>
                {r.slot ? `${r.slot} · ` : ""}{r.servings ? `${r.servings} servings` : ""}
              </Text>

              <View style={{ flexDirection: "row", gap: 8 }}>
                <Pressable
                  onPress={() =>
                    router.push({ pathname: "/recipe/[id]", params: { id: String(r.recipe_id) } } as Href)
                  }
                  style={{ backgroundColor: "#2563eb", paddingVertical: 8, paddingHorizontal: 12, borderRadius: 10 }}
                >
                  <Text style={{ color: "#fff", fontWeight: "700" }}>View</Text>
                </Pressable>

                <Pressable
                  onPress={() => onCook(r.id)}  // <-- Use meal_plan.id here
                  style={{ backgroundColor: "#10b981", paddingVertical: 8, paddingHorizontal: 12, borderRadius: 10 }}
                >
                  <Text style={{ color: "#fff", fontWeight: "700" }}>Cook</Text>
                </Pressable>

                <Pressable
                  onPress={() => onDelete(r.id)}
                  style={{ backgroundColor: "#ef4444", paddingVertical: 8, paddingHorizontal: 12, borderRadius: 10 }}
                >
                  <Text style={{ color: "#fff", fontWeight: "700" }}>Delete</Text>
                </Pressable>
              </View>
            </View>
          ))}
        </View>
      )}
      ListEmptyComponent={
        <Text style={{ color: "#6b7280", textAlign: "center", marginTop: 40 }}>
          Nothing in your meal plan yet.
        </Text>
      }
    />
  );
}
