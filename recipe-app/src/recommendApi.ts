// src/recommendApi.ts
import Config from "./config";
import { getToken } from "./auth";

export type RecItem = {
  id: number;
  title?: string | null;
  dist: number;

  // Pantry-aware extras from backend (all optional to display)
  query_score?: number;       // 0..1 (higher is better)
  overlap_score?: number;     // Jaccard pantry vs recipe tokens
  cover_score?: number;       // fraction of recipe tokens covered by pantry
  final?: number;             // blended score used for ranking
  used_from_pantry?: string[]; // a few tokens that matched
  missing?: string[];          // a few tokens you don't have
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
