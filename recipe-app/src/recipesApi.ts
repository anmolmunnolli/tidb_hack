// src/recipesApi.ts
import Config from "./config";
import { getToken } from "./auth";

export type RecipeDetail = {
  id: string;
  title?: string | null;
  ingredients?: string[];   // normalized by backend
  directions?: string[];    // normalized by backend
};

export async function getRecipe(id: string): Promise<RecipeDetail> {
  const token = await getToken();
  if (!token) throw new Error("Missing auth token");

  const r = await fetch(`${Config.API_BASE}/api/recipe/${encodeURIComponent(id)}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j?.detail || "Failed to load recipe");
  return j as RecipeDetail;
}
