// src/recommendApi.ts
import Config from "./config";
import { getToken } from "./auth";


export type RecipeDetail = {
  id: number;
  title?: string | null;
  text_blob?: string | null;
  ingredients?: string | null;     // raw DB text
  directions?: string | null;      // raw DB text
  ingredients_list?: string[];     // parsed on server
  directions_list?: string[];      // parsed on server
};

export async function getRecipeDetail(id: number): Promise<RecipeDetail> {
  const token = await getToken();
  if (!token) throw new Error("Missing auth token. Please sign in again.");

  const r = await fetch(`${Config.API_BASE}/api/recipe/${id}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) {
    throw new Error(j?.detail || "Failed to load recipe");
  }
  return j as RecipeDetail;
}

export type RecItem = {
  id: string;                  // <-- was number
  title?: string | null;
  dist: number;
  query_score?: number;
  overlap_score?: number;
  cover_score?: number;
  final?: number;
  used_from_pantry?: string[];
  missing?: string[];
};

export type RecommendParams = {
  query: string;
  k?: number;              // final results to return
  m?: number;              // candidate pool before rerank
  w1_query?: number;       // blend weight (vector relevance)
  w2_overlap?: number;     // blend weight (pantry Jaccard)
  w3_cover?: number;       // blend weight (coverage)
  min_cover?: number;      // optional gate (e.g., 0.2)
};

export async function recommendMeals(params: RecommendParams): Promise<RecItem[]> {
  const token = await getToken();
  if (!token) throw new Error("Missing auth token. Please sign in again.");

  const r = await fetch(`${Config.API_BASE}/api/recommend`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(params),
  });

  const j = await r.json().catch(() => ({}));
  if (!r.ok) {
    throw new Error(j?.detail || "Recommendation failed");
  }
  return (j?.items ?? []) as RecItem[];
}
