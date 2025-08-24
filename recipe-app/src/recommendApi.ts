// src/recommendApi.ts
import Config from "./config";

export type RecItem = {
  id: number;
  title?: string | null;
  dist: number;
};

export async function recommendMeals(query: string, k = 5): Promise<RecItem[]> {
  const r = await fetch(`${Config.API_BASE}/api/recommend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, k }),
  });
  const j = await r.json();
  if (!r.ok) {
    // backend sends {detail: "..."} on error
    throw new Error(j?.detail || "Recommendation failed");
  }
  return (j?.items ?? []) as RecItem[];
}
