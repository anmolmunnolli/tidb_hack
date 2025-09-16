// hooks/useCookPlan.ts
import { useCallback, useState } from "react";
import { Alert } from "react-native";
import { cookMealPlanItem } from "../src/mealPlanApi";
import type { CookResponse } from "../src/api";

type Options = {
  onDone?: (final: CookResponse) => void;
};

export function useCookPlan(planId: number, opts?: Options) {
  const [loading, setLoading] = useState(false);

  const cook = useCallback(async () => {
    try {
      setLoading(true);

      // 1) PREVIEW (no DB writes)
      const preview = await cookMealPlanItem(planId, false);

      const shortages = preview.shortages ?? [];
      const needsConfirm =
        preview.requires_confirmation === true || shortages.length > 0;

      // Helper to summarize for the alert body
      const summarize = (res: CookResponse) => {
        const d = res.deducted?.length ?? 0;
        const s = res.shortages?.length ?? 0;
        const dLines = (res.deducted || [])
          .slice(0, 3)
          .map((x) => `• ${x.ingredient}${x.used ? ` — used ${x.used}` : ""}`)
          .join("\n");
        const sLines = (res.shortages || [])
          .slice(0, 3)
          .map((x) => `• ${x.ingredient}${x.reason ? ` — ${x.reason}` : ""}`)
          .join("\n");
        return {
          title: s > 0 ? `Shortages (${s})` : `Deducted (${d})`,
          message:
            (d ? `Deducted:\n${dLines}\n\n` : "") +
            (s ? `Shortages:\n${sLines}` : ""),
        };
      };

      if (!needsConfirm) {
        const { title, message } = summarize(preview);
        Alert.alert(title || "Cooked ✅", message || "Pantry deducted.");
        opts?.onDone?.(preview);
        return;
      }

      // 2) Ask user to proceed
      const { title, message } = summarize(preview);
      Alert.alert(
        title || "Shortages detected",
        (message || "Some ingredients are short.") + "\n\nProceed anyway?",
        [
          { text: "Cancel", style: "cancel" },
          {
            text: "Proceed",
            style: "destructive",
            onPress: async () => {
              try {
                setLoading(true);
                // 3) COMMIT (writes to DB)
                const committed = await cookMealPlanItem(planId, true);
                const sum = summarize(committed);
                Alert.alert(sum.title || "Cooked ✅", sum.message || "Pantry deducted.");
                opts?.onDone?.(committed);
              } catch (e: any) {
                Alert.alert("Error", e?.message ?? "Could not commit cook.");
              } finally {
                setLoading(false);
              }
            },
          },
        ]
      );
    } catch (e: any) {
      Alert.alert("Error", e?.message ?? "Cook failed.");
    } finally {
      setLoading(false);
    }
  }, [planId, opts]);

  return { cook, loading };
}
