// src/planApi.ts
import Config from "./config";
import { getToken } from "./auth";

export type MealPlanItem = {
  id: number | string;
  user_id?: number | string;
  recipe_id: string;              // keep string to match BIGINT safely
  title?: string | null;
  ingredients?: string[];         // server already parses to list
  directions?: string[];
  servings?: number | null;
  planned_for?: string | null;    // "YYYY-MM-DD"
  slot?: "breakfast" | "lunch" | "dinner" | "snack" | string | null;
  notes?: string | null;
  created_at?: string | null;
};

export type AddMealPlanParams = {
  recipe_id: string;
  servings?: number;
  planned_for?: string; // "YYYY-MM-DD"
  slot?: string;
  notes?: string;
};

// What the cook endpoint returns (as implemented on server)
export type CookResponse = {
  cooked_id: number | string;
  pantry_changes: Array<{
    name: string;
    before_qty?: number | null;
    after_qty?: number | null;
    delta?: number | null;
    unit?: string | null;
  }>;
};

async function authFetch<T = any>(path: string, init?: RequestInit): Promise<T> {
  const token = await getToken();
  if (!token) throw new Error("Missing auth token");
  const r = await fetch(`${Config.API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(init?.headers || {}),
    },
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j?.detail || `Request failed: ${r.status}`);
  return j as T;
}

export async function listMealPlan(): Promise<MealPlanItem[]> {
  const j = await authFetch<{ items?: MealPlanItem[] } | MealPlanItem[]>("/api/mealplan");
  // server returns { items: [...] }, but accept array too
  return Array.isArray(j) ? j : (j.items ?? []);
}

// NOTE: server returns the full PlanItemOut, so return that
export async function addToMealPlan(p: AddMealPlanParams): Promise<MealPlanItem> {
  const j = await authFetch<MealPlanItem>("/api/mealplan", {
    method: "POST",
    body: JSON.stringify(p),
  });
  return j;
}

export async function deleteMealPlanItem(id: string | number): Promise<{ ok: true }> {
  return authFetch<{ ok: true }>(`/api/mealplan/${id}`, { method: "DELETE" });
}

// Align with server cook response (not just { ok: boolean })
export async function cookMealPlanItem(planId: string | number): Promise<CookResponse> {
  return authFetch<CookResponse>(`/api/mealplan/${planId}/cook`, { method: "POST" });
}
