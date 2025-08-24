// app/(tabs)/plan.tsx
import React, { useState } from "react";
import { View, Text, TextInput, Pressable, FlatList, ActivityIndicator, Alert } from "react-native";
import { recommendMeals, type RecItem } from "../../src/recommendApi";

export default function PlanScreen() {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [items, setItems] = useState<RecItem[]>([]);

  const onSearch = async () => {
    const query = q.trim();
    if (!query) {
      Alert.alert("Enter a query", "e.g., 'indian potato curry less spicy'");
      return;
    }
    try {
      setBusy(true);
      const res = await recommendMeals(query, 5);
      setItems(res);
    } catch (e: any) {
      Alert.alert("Error", e?.message ?? "Failed to get recommendations");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={{ flex:1, padding:16, gap:12, backgroundColor:"#fff" }}>
      <Text style={{ fontSize:22, fontWeight:"800" }}>🍽️ Meal recommendations</Text>
      <TextInput
        placeholder='Try: "indian potato curry less spicy"'
        value={q}
        onChangeText={setQ}
        autoCapitalize="none"
        style={{ borderWidth:1, borderColor:"#e5e7eb", borderRadius:10, padding:12 }}
      />
      <Pressable onPress={onSearch} style={{ backgroundColor:"#111827", padding:14, borderRadius:10 }}>
        <Text style={{ color:"#fff", textAlign:"center", fontWeight:"700" }}>
          {busy ? "Searching…" : "Search"}
        </Text>
      </Pressable>

      {busy && <ActivityIndicator size="large" style={{ marginTop:10 }} />}

      <FlatList
        data={items}
        keyExtractor={(x) => String(x.id)}
        contentContainerStyle={{ gap:10, paddingVertical:8 }}
        renderItem={({ item }) => (
          <View style={{ borderWidth:1, borderColor:"#e5e7eb", borderRadius:12, padding:12 }}>
            <Text style={{ fontWeight:"800", fontSize:16 }}>{item.title || "(untitled)"}</Text>
            <Text style={{ color:"#6b7280" }}>distance: {item.dist.toFixed(4)}</Text>
          </View>
        )}
        ListEmptyComponent={!busy ? (
          <Text style={{ color:"#6b7280", marginTop:8 }}>
            No results yet. Enter a query and tap Search.
          </Text>
        ) : null}
      />
    </View>
  );
}
