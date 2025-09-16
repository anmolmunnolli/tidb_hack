// src/planApi.ts
import Config from "./config";
import { getToken } from "./auth";

/** ---------- Types (match server responses) ---------- */
export type CookLine = {
  ingredient: string;
  matched_pantry?: string;
  used?: string;
  remaining?: string;
  reason?: string;
  match_conf?: number;
};

export type CookResponse = {
  ok: boolean;
  plan_id: number;
  deducted: CookLine[];
  shortages: CookLine[];
  requires_confirmation: boolean;
};

export type MealPlanItem = {
  id: number | string;               // meal_plan.id  (use this for /cook)
  user_id?: string;
  recipe_id: number | string;
  title?: string | null;
  ingredients?: string[];
  directions?: string[];
  servings?: number | null;
  planned_for?: string | null;       // "YYYY-MM-DD" | null
  slot?: string | null;
  notes?: string | null;
  created_at?: string;               // ISO
};

/** ---------- tiny helpers ---------- */
async function apiFetchAuthed<T>(path: string, init?: RequestInit): Promise<T> {
  const token = await getToken();
  if (!token) throw new Error("Missing auth token");

  const res = await fetch(`${Config.API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(init?.headers || {}),
    },
    ...init,
  });

  const text = await res.text();
  let data: unknown = {};
  if (text) {
    try { data = JSON.parse(text); } catch { data = {}; }
  }

  if (!res.ok) {
    const msg =
      (data as any)?.detail ||
      (data as any)?.error ||
      res.statusText ||
      "Request failed";
    throw new Error(msg);
  }
  return data as T;
}

/** ---------- API calls ---------- */
export async function listMealPlan(): Promise<MealPlanItem[]> {
  // server returns { items: [...] }
  const r = await apiFetchAuthed<{ items: MealPlanItem[] }>("/api/mealplan");
  return r.items || [];
}

export async function deleteMealPlanItem(planId: number | string): Promise<{ ok: boolean }> {
  return apiFetchAuthed<{ ok: boolean }>(`/api/mealplan/${planId}`, { method: "DELETE" });
}

/**
 * Preview or confirm a cook action.
 * - confirm=false : preview only (no DB writes); server returns shortages/deducted preview
 * - confirm=true  : actually deduct from pantry
 */
export async function cookMealPlanItem(
  planId: number | string,
  confirm: boolean
): Promise<CookResponse> {
  const token = await getToken();
  if (!token) throw new Error("Missing auth token");

  return apiFetchAuthed<CookResponse>(
    `/api/mealplan/${planId}/cook?confirm=${confirm ? "true" : "false"}`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`, // pass token here since apiFetchAuthed takes only (path, init?)
      },
    }
  );
}
