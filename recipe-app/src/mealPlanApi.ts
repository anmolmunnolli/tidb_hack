import Config from "./config";
import { getToken } from "./auth";

export type CookResult = {
  plan_id: number;
  servings_used?: number;
  deductions: any[];
  unfilled: any[];
};

export async function cookPlanItem(planId: number, servingsOverride?: number): Promise<CookResult> {
  const token = await getToken();
  if (!token) throw new Error("Missing auth token");

  const r = await fetch(`${Config.API_BASE}/api/mealplan/${planId}/cook`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      servings_override: servingsOverride ?? null,
    }),
  });

  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j?.detail || "Cook failed");
  return j as CookResult;
}
