// app/(tabs)/pantry.tsx
import React, { useEffect, useState, ReactNode } from "react";
import {
  View,
  Text,
  FlatList,
  Pressable,
  TextInput,
  Modal,
  Platform,
  Alert,
  ActivityIndicator,
  RefreshControl,
} from "react-native";
import { router, type Href } from "expo-router";
import {
  fetchPantry,
  addPantry,
  deletePantry,
  type PantryItem,
} from "../../src/pantryApi";
import { useAuthToken } from "../../src/useAuthToken";
import { clearSession } from "../../src/auth";

/** ---- NEW: local helper + type -------------------------------------------------- */
type PantryItemWithNorm = PantryItem & {
  norm_qty?: number | string | null;
  norm_unit?: string | null;
};

function formatQty(q?: number | string | null) {
  if (q === null || q === undefined || q === "") return "";
  return typeof q === "number" ? String(q) : q;
}
/** ------------------------------------------------------------------------------- */

function isExpiringSoon(iso?: string | null): boolean {
  if (!iso) return false;
  const d = new Date(iso).getTime();
  const now = Date.now();
  const threeDays = 3 * 24 * 3600 * 1000;
  return d - now <= threeDays;
}

const ActionButton = ({
  label,
  onPress,
  tone = "#111827",
}: {
  label: string;
  onPress: () => void;
  tone?: string;
}) => (
  <Pressable
    onPress={onPress}
    style={{
      backgroundColor: tone,
      paddingVertical: 12,
      paddingHorizontal: 14,
      borderRadius: 12,
    }}
  >
    <Text style={{ color: "#fff", fontWeight: "700" }}>{label}</Text>
  </Pressable>
);

const Card = ({ children, style }: { children: ReactNode; style?: any }) => (
  <View
    style={[
      {
        backgroundColor: "#fff",
        borderRadius: 16,
        padding: 14,
        shadowColor: "#000",
        shadowOpacity: 0.06,
        shadowRadius: 10,
        elevation: 2,
      },
      style,
    ]}
  >
    {children}
  </View>
);

export default function PantryScreen() {
  const { token, loading: authLoading } = useAuthToken();

  /** ---- CHANGED: typed as PantryItemWithNorm[] so TS allows norm_* keys ------ */
  const [items, setItems] = useState<PantryItemWithNorm[]>([]);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const [showAdd, setShowAdd] = useState(false);
  const [name, setName] = useState("");
  const [qty, setQty] = useState<string>("");
  const [unit, setUnit] = useState("");
  const [expiresOn, setExpiresOn] = useState("");

  async function load() {
    try {
      setLoading(true);
      /** Keep fetchPantry as-is; if your API already returns norm_* they’ll flow through */
      const data = (await fetchPantry()) as unknown as PantryItemWithNorm[];
      setItems(data);
    } catch (e: any) {
      if (/not authenticated|unauthorized|401/i.test(String(e?.message))) {
        router.replace("/(auth)/login" as Href);
        return;
      }
      Alert.alert("Error", e?.message ?? "Failed to load pantry");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!authLoading && token) load();
  }, [authLoading, token]);

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

  const empty = items.length === 0;

  async function onAdd() {
    if (!name.trim()) {
      Alert.alert("Missing name", "Please enter an item name.");
      return;
    }
    const parsedQty = qty ? Number(qty) : undefined;
    if (qty && Number.isNaN(parsedQty)) {
      Alert.alert("Invalid quantity", "Please enter a numeric quantity.");
      return;
    }

    try {
      await addPantry({
        name: name.trim(),
        qty: parsedQty,
        unit: unit.trim() || undefined,
        expires_on: expiresOn.trim() || undefined,
      });
      setShowAdd(false);
      setName("");
      setQty("");
      setUnit("");
      setExpiresOn("");
      load();
    } catch (e: any) {
      if (/not authenticated|unauthorized|401|token/i.test(String(e?.message))) {
        router.replace("/(auth)/login" as Href);
        return;
      }
      Alert.alert("Error", e?.message ?? "Failed to add item");
    }
  }

  async function onDelete(id: number) {
    try {
      await deletePantry(id);
      load();
    } catch (e: any) {
      if (/not authenticated|unauthorized|401/i.test(String(e?.message))) {
        router.replace("/(auth)/login" as Href);
        return;
      }
      Alert.alert("Error", e?.message ?? "Failed to delete item");
    }
  }

  async function onRefresh() {
    try {
      setRefreshing(true);
      await load();
    } finally {
      setRefreshing(false);
    }
  }

  async function onLogout() {
    await clearSession();
    router.replace("/(auth)/login" as Href);
  }

  return (
    <View style={{ flex: 1, backgroundColor: "#f5f7fb", padding: 16 }}>
      {/* Header / Quick Actions */}
      <View
        style={{
          flexDirection: "row",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 12,
        }}
      >
        <Text style={{ fontSize: 22, fontWeight: "800" }}>🧺 My Pantry</Text>
        <View style={{ flexDirection: "row", gap: 8 }}>
          <ActionButton label="Add item" onPress={() => setShowAdd(true)} />
          <ActionButton
            label="Shopping"
            tone="#2563eb"
            onPress={() => router.push("/(tabs)/index" as Href)}
          />
          <ActionButton label="Logout" tone="#ef4444" onPress={onLogout} />
        </View>
      </View>

      {/* Empty state / List */}
      {loading ? (
        <Card style={{ alignItems: "center", paddingVertical: 24 }}>
          <ActivityIndicator />
          <Text style={{ marginTop: 8 }}>Loading…</Text>
        </Card>
      ) : empty ? (
        <Card style={{ alignItems: "center", gap: 10, paddingVertical: 24 }}>
          <Text style={{ fontSize: 18, fontWeight: "700" }}>
            Your pantry is empty
          </Text>
          <Text style={{ color: "#6b7280", textAlign: "center" }}>
            Start by adding what’s in your fridge—or create a shopping list to
            fill it up.
          </Text>
          <View style={{ flexDirection: "row", gap: 10, marginTop: 8 }}>
            <ActionButton label="➕ Add items" onPress={() => setShowAdd(true)} />
            <ActionButton
              label="📝 Create shopping list"
              tone="#2563eb"
              onPress={() => router.push("/(tabs)/index" as Href)}
            />
          </View>
          <Text style={{ fontSize: 36, marginTop: 6 }}>🥦🧀🥔🥛</Text>
        </Card>
      ) : (
        <FlatList
          data={items}
          keyExtractor={(x) => String(x.id)}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
          }
          contentContainerStyle={{ paddingBottom: 80, gap: 12 }}
          renderItem={({ item: pi }) => {
            /** ---- NEW: prefer normalized values if present ------------------- */
            const displayQty =
              pi.norm_qty ?? (pi as any).normQty ?? pi.qty ?? null;
            const displayUnit =
              pi.norm_unit ?? (pi as any).normUnit ?? pi.unit ?? null;
            const isNormalized =
              pi.norm_qty !== undefined ||
              (pi as any).normQty !== undefined ||
              pi.norm_unit !== undefined ||
              (pi as any).normUnit !== undefined;
            /** ---------------------------------------------------------------- */

            return (
              <Card>
                <View
                  style={{
                    flexDirection: "row",
                    justifyContent: "space-between",
                    alignItems: "center",
                  }}
                >
                  <View style={{ flexShrink: 1 }}>
                    <Text style={{ fontWeight: "700" }}>
                      {pi.name}
                      {displayQty
                        ? ` · ${formatQty(displayQty)}${
                            displayUnit ? ` ${displayUnit}` : ""
                          }`
                        : ""}
                    </Text>

                    {!!pi.expires_on && (
                      <Text
                        style={{
                          color: isExpiringSoon(pi.expires_on)
                            ? "#b91c1c"
                            : "#6b7280",
                        }}
                      >
                        Expires {new Date(pi.expires_on).toLocaleDateString()}
                        {isExpiringSoon(pi.expires_on) ? " · soon!" : ""}
                      </Text>
                    )}

                    {/* Optional: show a tiny tag if normalized */}
                    {isNormalized && (
                      <Text
                        style={{
                          marginTop: 2,
                          color: "#065f46",
                          fontSize: 12,
                          fontWeight: "700",
                        }}
                      >
                        normalized
                      </Text>
                    )}
                  </View>

                  <View style={{ flexDirection: "row", gap: 8 }}>
                    <ActionButton
                      label="✕"
                      tone="#ef4444"
                      onPress={() => onDelete(pi.id)}
                    />
                  </View>
                </View>
              </Card>
            );
          }}
        />
      )}

      {/* Add Item Modal */}
      <Modal
        visible={showAdd}
        animationType="slide"
        transparent
        onRequestClose={() => setShowAdd(false)}
      >
        <View
          style={{
            flex: 1,
            backgroundColor: "rgba(0,0,0,0.25)",
            justifyContent: "flex-end",
          }}
        >
          <View
            style={{
              backgroundColor: "#fff",
              padding: 16,
              borderTopLeftRadius: 20,
              borderTopRightRadius: 20,
              gap: 10,
            }}
          >
            <Text style={{ fontSize: 18, fontWeight: "800" }}>Add item</Text>

            <TextInput
              placeholder="Name (e.g., Potatoes)"
              value={name}
              onChangeText={setName}
              style={{
                borderWidth: 1,
                borderColor: "#e5e7eb",
                borderRadius: 10,
                padding: 12,
              }}
            />

            <View style={{ flexDirection: "row", gap: 8 }}>
              <TextInput
                placeholder="Qty"
                keyboardType={Platform.select({
                  ios: "numbers-and-punctuation",
                  default: "numeric",
                })}
                value={qty}
                onChangeText={setQty}
                style={{
                  flex: 1,
                  borderWidth: 1,
                  borderColor: "#e5e7eb",
                  borderRadius: 10,
                  padding: 12,
                }}
              />
              <TextInput
                placeholder="Unit (pcs, g, ml)"
                value={unit}
                onChangeText={setUnit}
                style={{
                  flex: 1,
                  borderWidth: 1,
                  borderColor: "#e5e7eb",
                  borderRadius: 10,
                  padding: 12,
                }}
              />
            </View>

            <TextInput
              placeholder="Expires (YYYY-MM-DD)"
              value={expiresOn}
              onChangeText={setExpiresOn}
              style={{
                borderWidth: 1,
                borderColor: "#e5e7eb",
                borderRadius: 10,
                padding: 12,
              }}
            />

            <View
              style={{
                flexDirection: "row",
                justifyContent: "space-between",
                marginTop: 8,
              }}
            >
              <Pressable onPress={() => setShowAdd(false)} style={{ padding: 12 }}>
                <Text style={{ fontWeight: "700" }}>Cancel</Text>
              </Pressable>
              <Pressable
                onPress={onAdd}
                style={{
                  backgroundColor: "#111827",
                  paddingVertical: 12,
                  paddingHorizontal: 16,
                  borderRadius: 10,
                }}
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
