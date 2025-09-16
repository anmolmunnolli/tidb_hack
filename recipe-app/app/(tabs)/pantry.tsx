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
  StyleSheet,
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

/** ---- Local helper + type -------------------------------------------------- */
type PantryItemWithNorm = PantryItem & {
  norm_qty?: number | string | null;
  norm_unit?: string | null;
};

function formatQty(q?: number | string | null) {
  if (q === null || q === undefined || q === "") return "";
  return typeof q === "number" ? String(q) : q;
}
/** -------------------------------------------------------------------------- */

function isExpiringSoon(iso?: string | null): boolean {
  if (!iso) return false;
  const d = new Date(iso).getTime();
  const now = Date.now();
  const threeDays = 3 * 24 * 3600 * 1000;
  return d - now <= threeDays;
}

/* ---------- Small UI helpers (keep) ---------- */
const ActionButton = ({
  label,
  onPress,
  tone = "#111827",
}: {
  label: string;
  onPress: () => void;
  tone?: string;
}) => (
  <Pressable onPress={onPress} style={[styles.btn, { backgroundColor: tone }]}>
    <Text style={styles.btnText}>{label}</Text>
  </Pressable>
);

const Card = ({ children, style }: { children: ReactNode; style?: any }) => (
  <View style={[styles.card, style]}>{children}</View>
);

/* ==================== Screen ==================== */
export default function PantryScreen() {
  const { token, loading: authLoading } = useAuthToken();

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
      <View style={[styles.screen, styles.center]}>
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
    <View style={styles.screen}>
      {/* Header / Quick Actions */}
      <View style={styles.headerRow}>
        <Text style={styles.headerTitle}>🧺 My Pantry</Text>
        <View style={styles.headerActions}>
          <ActionButton label="Add item" tone="#46444E" onPress={() => setShowAdd(true)} />
          <ActionButton label="Logout" tone="#595085" onPress={onLogout} />
        </View>
      </View>

      {/* Content */}
      {loading ? (
        <Card style={[styles.center, { paddingVertical: 24 }]}>
          <ActivityIndicator />
          <Text style={{ marginTop: 8, color: "#6b7280" }}>Loading…</Text>
        </Card>
      ) : empty ? (
        <Card style={[styles.center, { gap: 10, paddingVertical: 24 }]}>
          <Text style={{ fontSize: 18, fontWeight: "700", color: "#0f172a" }}>
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
          numColumns={2}
          columnWrapperStyle={gridStyles.gridRow}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
          }
          contentContainerStyle={gridStyles.gridList}
          renderItem={({ item: pi }) => {
            // Prefer normalized values if present
            const displayQty =
              pi.norm_qty ?? (pi as any).normQty ?? pi.qty ?? null;
            const displayUnit =
              pi.norm_unit ?? (pi as any).normUnit ?? pi.unit ?? null;
            const isNormalized =
              pi.norm_qty !== undefined ||
              (pi as any).normQty !== undefined ||
              pi.norm_unit !== undefined ||
              (pi as any).normUnit !== undefined;

              return (
              <Card style={gridStyles.gridCard}>
                <View style={gridStyles.cardContent}>
                  {/* Top row: name + chips + delete */}
                  <View style={gridStyles.topRow}>
                    <View style={{ flex: 1 }}>
                      <Text numberOfLines={2} style={gridStyles.name}>
                        {pi.name}
                      </Text>
                      <View style={gridStyles.chipRow}>
                        {!!displayQty && (
                          <View style={[gridStyles.chip, gridStyles.qtyChip]}>
                            <Text style={[gridStyles.chipText, { color: "#2563EB" }]}>
                              {formatQty(displayQty)} {displayUnit ?? ""}
                            </Text>
                          </View>
                        )}
                        {isNormalized && (
                          <View style={[gridStyles.chip, gridStyles.normChip]}>
                            <Text style={[gridStyles.chipText, { color: "#065f46" }]}>
                              normalized
                            </Text>
                          </View>
                        )}
                      </View>
                    </View>

                    <Pressable
                      onPress={() => onDelete(pi.id)}
                      style={gridStyles.iconBtn}
                      android_ripple={{ color: "rgba(239,68,68,0.15)" }}
                    >
                      <Text style={gridStyles.iconBtnText}>✕</Text>
                    </Pressable>
                  </View>

                  {/* Footer: expiry only */}
                  <View style={gridStyles.footerRow}>
                    {!!pi.expires_on ? (
                      <Text
                        style={[
                          gridStyles.expiry,
                          { color: isExpiringSoon(pi.expires_on) ? "#b91c1c" : "#6b7280" },
                        ]}
                      >
                        {new Date(pi.expires_on).toLocaleDateString()}
                        {isExpiringSoon(pi.expires_on) ? " · soon" : ""}
                      </Text>
                    ) : (
                      <Text style={[gridStyles.expiry, { color: "#9CA3AF" }]}></Text>
                    )}
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
        <View style={styles.dim}>
          <View style={styles.sheet}>
            <Text style={styles.sheetTitle}>Add item</Text>

            <TextInput
              placeholder="Name (e.g., Potatoes)"
              value={name}
              onChangeText={setName}
              style={styles.input}
            />

            <View style={styles.sheetRow}>
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
                    borderRadius: 5,
                    padding: 3,
                  }}
              />
              <TextInput
                placeholder="Unit (pcs, g, ml)"
                value={unit}
                onChangeText={setUnit}
                style={[styles.input, { flex: 1 }]}
              />
            </View>

            <TextInput
              placeholder="Expires (YYYY-MM-DD)"
              value={expiresOn}
              onChangeText={setExpiresOn}
              style={styles.input}
            />

            <View style={[styles.sheetRow, { justifyContent: "space-between" }]}>
              <Pressable onPress={() => setShowAdd(false)} style={{ padding: 12 }}>
                <Text style={{ fontWeight: "400", color: "#0f172a" }}>Cancel</Text>
              </Pressable>
              <Pressable onPress={onAdd} style={[styles.btn, { backgroundColor: "#111827" }]}>
                <Text style={styles.btnText}>Add</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

/* ==================== Styles ==================== */
const styles = StyleSheet.create({

  
  screen: {
    flex: 1,
    backgroundColor: "#E5E2F5", // light blue background
    padding: 16,
  },
  center: {
    alignItems: "center",
    justifyContent: "center",
  },
  headerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 12,
  },
  headerTitle: {
    fontSize: 22,
    fontWeight: "800",
    color: "#0f172a",
  },
  headerActions: { flexDirection: "row", gap: 8 },
  card: {
    backgroundColor: "#fff",
    borderRadius: 16,
    padding: 14,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: "rgba(15,23,42,0.06)",
    shadowColor: "#0f172a",
    shadowOpacity: 0.06,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 6 },
    elevation: 3,
  },
  btn: {
    paddingVertical: 12,
    paddingHorizontal: 14,
    borderRadius: 12,
  },
  btnText: { color: "#fff", fontWeight: "700" },
  dim: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.25)",
    justifyContent: "flex-end",
  },
  sheet: {
    backgroundColor: "#fff",
    padding: 16,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    gap: 10,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderColor: "rgba(60, 144, 152, 0.06)",
  },
  sheetTitle: { fontSize: 18, fontWeight: "800", color: "#0f172a" },
  sheetRow: { flexDirection: "row", columnGap: 8 },
  input: {
    borderWidth: 1,
    borderColor: "rgba(15,23,42,0.06)",
    borderRadius: 10,
    padding: 12,
    backgroundColor: "#fff",
  },
});

/* ===== Grid-specific styles (2 columns) ===== */
const gridStyles = StyleSheet.create({

  cardContent: {
    flex: 1,
    justifyContent: "space-between",
    gap: 8,
  },

  topRow: {
    flexDirection: "row",
    alignItems: "flex-start", // align name + chips + delete nicely at top
    columnGap: 8,
  },

  chipRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
    marginTop: 4,
  },

  chip: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 999,
    borderWidth: StyleSheet.hairlineWidth,
  },
  qtyChip: {
    backgroundColor: "#E8F0FF",
    borderColor: "transparent",
  },
  normChip: {
    backgroundColor: "#ECFDF5",
    borderColor: "rgba(5,150,105,0.25)",
  },
  chipText: {
    fontSize: 11,
    fontWeight: "600",
  },

  iconBtn: {
    backgroundColor: "#FEE2E2",
    borderRadius: 10,
    paddingVertical: 6,
    paddingHorizontal: 10,
    alignSelf: "flex-start",
  },
  iconBtnText: {
    color: "#B91C1C",
    fontWeight: "800",
  },

  footerRow: {
    flexDirection: "row",
    alignItems: "center",
    marginTop: 4,
  },
  expiry: {
    fontSize: 12,
    fontWeight: "600",
  },

  
  gridList: {
    paddingBottom: 80,
    paddingHorizontal: 4,
    rowGap: 12, // vertical gap
  },
  gridRow: {
    columnGap: 12, // horizontal gap between columns
    paddingHorizontal: 4,
  },
  gridCard: {
    flex: 1,          // take half the row width (with column gap)
    borderRadius: 16, // keep rounded shape from Card
    aspectRatio: 1.4, // control consistent height; tweak 1.3–1.5 if needed
    overflow: "hidden",
  },

  name: {
    fontSize: 15,
    fontWeight: "700",
    color: "#111827",
  },

  deleteBtn: {
    backgroundColor: "#FEE2E2", // red-100
    borderRadius: 10,
    paddingVertical: 6,
    paddingHorizontal: 10,
  },
  deleteText: {
    color: "#B91C1C", // red-700
    fontWeight: "800",
  },
});
