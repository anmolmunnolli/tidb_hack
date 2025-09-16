// app/(tabs)/index.tsx
import React, { useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  FlatList,
} from "react-native";
import { router, type Href } from "expo-router";
import { useAuthToken } from "../../src/useAuthToken";
import { fetchPantry, type PantryItem } from "../../src/pantryApi";
import { listMealPlan, type MealPlanItem } from "../../src/mealPlanApi";

const COLORS = {
  bg: "#E5E2F5",
  card: "#fff",
  text: "#0f172a",
  subtle: "#6b7280",
  border: "rgba(15,23,42,0.06)",
  primary: "#595085",   // matches your buttons
  secondary: "#46444E",
  accent: "#2563EB",
  success: "#10B981",
  warn: "#B45309",
  danger: "#B91C1C",
};

export default function TabsHome() {
  const { token, loading: authLoading } = useAuthToken();
  const [loading, setLoading] = useState(true);
  const [pantry, setPantry] = useState<PantryItem[]>([]);
  const [plan, setPlan] = useState<MealPlanItem[]>([]);

  useEffect(() => {
    if (!authLoading && token) {
      (async () => {
        try {
          setLoading(true);
          const [p, m] = await Promise.all([fetchPantry(), listMealPlan()]);
          setPantry(p);
          setPlan(m);
        } catch (e) {
          // keep home resilient—just show hero even if stats fail
        } finally {
          setLoading(false);
        }
      })();
    }
  }, [authLoading, token]);

  const stats = useMemo(() => {
    const totalPantry = pantry.length;
    const expiringSoon = pantry.filter((x) => {
      if (!x.expires_on) return false;
      const d = new Date(x.expires_on).getTime();
      const now = Date.now();
      const threeDays = 3 * 24 * 3600 * 1000;
      return d - now <= threeDays;
    }).length;

    // upcoming meals = items that have a planned_for >= today
    const todayYMD = new Date().toISOString().slice(0, 10);
    const upcomingMeals = (plan || []).filter(
      (r) => r.planned_for && r.planned_for >= todayYMD
    ).length;

    // silly but fun “impact” metric: expiring-soon items * 2.5$ saved if used
    const potentialSavings = Math.max(0, expiringSoon * 2.5);

    return { totalPantry, expiringSoon, upcomingMeals, potentialSavings };
  }, [pantry, plan]);

  if (authLoading) {
    return (
      <View style={[styles.screen, styles.center]}>
        <ActivityIndicator size="large" />
      </View>
    );
  }
  if (!token) {
    // If not signed in, just show friendly splash
    return (
      <View style={[styles.screen, styles.center]}>
        <Text style={styles.title}>Foodie Vault</Text>
        <Text style={[styles.body, { textAlign: "center", marginTop: 8 }]}>
          Sign in to start saving ingredients and discovering pantry-aware recipes.
        </Text>
      </View>
    );
  }

  return (
    <FlatList
      style={styles.screen}
      contentContainerStyle={{ padding: 16, paddingBottom: 100 }}
      data={[{ key: "hero" }, { key: "cta" }, { key: "stats" }, { key: "how" }]}
      renderItem={({ item }) => {
        switch (item.key) {
          case "hero":
            return (
              <View style={styles.heroCard}>
                <Text style={styles.kicker}>Welcome back 👋</Text>
                <Text style={styles.title}>Foodie Vault</Text>
                <Text style={styles.subtitle}>
                  We help you <Text style={{ fontWeight: "bold" }}>use what you already have</Text> reducing food waste and
                  stretching your budget with a little AI magic.
                </Text>
                <View style={styles.badgesRow}>
                  <Badge text="Pantry aware" tone="#2563EB" />
                  <Badge text="Vector search" tone="#7C3AED" />
                  <Badge text="Meal plans" tone="#10B981" />
                  <Badge text="Multi-agent" tone="#F59E0B" textColor="#111827" />
                </View>
              </View>
            );

          case "cta":
            return (
              <View style={styles.ctaRow}>
                <CTA
                  title="My Pantry"
                  subtitle="What’s in the vault"
                  color={COLORS.secondary}
                  onPress={() => router.push("/pantry" as Href)}
                  icon="🧺"
                />
                <CTA
                  title="Get Ideas"
                  subtitle="Pantry-aware recipes"
                  color={COLORS.primary}
                  onPress={() => router.push("/plan" as Href)}
                  icon="✨"
                />
                <CTA
                  title="Meal Plan"
                  subtitle="This week at a glance"
                  color={COLORS.accent}
                  onPress={() => router.push("/meal-plan" as Href)}
                  icon="🍽️"
                />
              </View>
            );

          case "stats":
            return (
              <View style={styles.card}>
                <Text style={styles.sectionTitle}>Your week, at a glance</Text>
                {loading ? (
                  <View style={[styles.center, { paddingVertical: 16 }]}>
                    <ActivityIndicator />
                  </View>
                ) : (
                  <View style={styles.statsGrid}>
                    <Stat
                      label="Pantry items"
                      value={`${stats.totalPantry}`}
                      tone="#111827"
                    />
                    <Stat
                      label="Expiring soon"
                      value={`${stats.expiringSoon}`}
                      tone={stats.expiringSoon > 0 ? COLORS.warn : COLORS.subtle}
                    />
                    <Stat
                      label="Upcoming meals"
                      value={`${stats.upcomingMeals}`}
                      tone={COLORS.success}
                    />
                    <Stat
                      label="Potential savings"
                      value={`$${stats.potentialSavings.toFixed(2)}`}
                      tone={COLORS.accent}
                    />
                  </View>
                )}
                <Text style={[styles.body, { marginTop: 10 }]}>
                  Tip: turn today’s expiring items into dinner with{" "}
                  <Text
                    onPress={() => router.push("/plan" as Href)}
                    style={styles.inlineLink}
                  >
                    pantry-aware search
                  </Text>
                  .
                </Text>
              </View>
            );

          case "how":
            return (
              <View style={styles.card}>
                <Text style={styles.sectionTitle}>How it works</Text>
                <Bullet
                  title="Pantry powers everything"
                  body="Add what you’ve got. We normalize quantities (hello, cups → grams) so your pantry is structured and smart."
                />
                <Bullet
                  title="Vector search for recipes"
                  body="We embed your pantry and recipe corpus so results match what you actually have on hand."
                />
                <Bullet
                  title="Plan → Cook → Auto-deduct"
                  body="Build a meal plan, then cook. Our multi-agent flow confirms shortages and updates your pantry automatically."
                />
                <Bullet
                  title="Waste less, save more"
                  body="Use it up before it expires. Every rescued carrot is a tiny win for your wallet and the planet 🥕🌎."
                />
              </View>
            );

          default:
            return null;
        }
      }}
    />
  );
}

/* ---------- Small presentational bits ---------- */
function Badge({ text, tone, textColor = "#fff" }: { text: string; tone: string; textColor?: string }) {
  return (
    <View style={[styles.badge, { backgroundColor: tone }]}>
      <Text style={[styles.badgeText, { color: textColor }]}>{text}</Text>
    </View>
  );
}

function CTA({
  title,
  subtitle,
  color,
  onPress,
  icon,
}: {
  title: string;
  subtitle: string;
  color: string;
  icon: string;
  onPress: () => void;
}) {
  return (
    <Pressable onPress={onPress} style={[styles.cta, { backgroundColor: color }]}>
      <Text style={styles.ctaIcon}>{icon}</Text>
      <Text style={styles.ctaTitle}>{title}</Text>
      <Text style={styles.ctaSubtitle}>{subtitle}</Text>
    </Pressable>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <View style={styles.stat}>
      <Text style={[styles.statValue, { color: tone }]}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

function Bullet({ title, body }: { title: string; body: string }) {
  return (
    <View style={{ marginTop: 10 }}>
      <Text style={styles.bulletTitle}>• {title}</Text>
      <Text style={styles.body}>{body}</Text>
    </View>
  );
}

/* -------------------- Styles -------------------- */
const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: COLORS.bg,
  },

  // Hero
  heroCard: {
    backgroundColor: COLORS.card,
    borderRadius: 16,
    padding: 16,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: COLORS.border,
    shadowColor: COLORS.text,
    shadowOpacity: 0.06,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 6 },
    elevation: 3,
    marginBottom: 12,
  },
  kicker: {
    color: COLORS.subtle,
    fontWeight: "700",
    marginBottom: 4,
  },
  title: {
    fontSize: 28,
    fontWeight: "900",
    color: COLORS.text,
  },
  subtitle: {
    marginTop: 6,
    color: COLORS.text,
    opacity: 0.9,
  },
  badgesRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    marginTop: 12,
  },
  badge: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 999,
  },
  badgeText: {
    color: "#fff",
    fontWeight: "800",
    fontSize: 12,
  },

  // CTAs
  ctaRow: {
    flexDirection: "row",
    gap: 12,
    marginBottom: 12,
  },
  cta: {
    flex: 1,
    borderRadius: 14,
    padding: 14,
  },
  ctaIcon: { fontSize: 22, marginBottom: 6 },
  ctaTitle: { color: "#fff", fontWeight: "900", fontSize: 16 },
  ctaSubtitle: { color: "#fff", opacity: 0.9, marginTop: 2 },

  // Stats
  card: {
    backgroundColor: COLORS.card,
    borderRadius: 16,
    padding: 16,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: COLORS.border,
    shadowColor: COLORS.text,
    shadowOpacity: 0.06,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 6 },
    elevation: 3,
    marginBottom: 12,
  },
  sectionTitle: {
    fontWeight: "900",
    color: COLORS.text,
    fontSize: 18,
  },
  statsGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    marginTop: 12,
    gap: 12,
  },
  stat: {
    backgroundColor: "#F8FAFF",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: COLORS.border,
    borderRadius: 12,
    paddingVertical: 12,
    paddingHorizontal: 14,
    minWidth: "47%",
    flexGrow: 1,
  },
  statValue: {
    fontSize: 20,
    fontWeight: "900",
  },
  statLabel: {
    marginTop: 2,
    color: COLORS.subtle,
    fontWeight: "700",
  },
  inlineLink: {
    color: COLORS.accent,
    fontWeight: "800",
    textDecorationLine: "underline",
  },

  // Text
  body: {
    color: COLORS.subtle,
  },

  bulletTitle: {
    color: COLORS.text,
    fontWeight: "800",
  },

  // Center helper
  center: { alignItems: "center", justifyContent: "center" },
});
