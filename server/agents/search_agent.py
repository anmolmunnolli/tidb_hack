# server/agents/search_agent.py
from __future__ import annotations
from typing import Any, Dict, List, Tuple
import math
import re

from db import get_conn

_WORD = re.compile(r"[a-z0-9]+")

def _tokens(s: str) -> List[str]:
    return _WORD.findall(s.lower())

def _jaccard(a: List[str], b: List[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)

def _score_query(title: str, ingredients: List[str], query: str) -> float:
    """Heuristic 0..1 score combining title & ingredient relevance."""
    q = query.lower().strip()
    if not q:
        return 0.0

    qtok = _tokens(q)
    ttok = _tokens(title)
    itok = _tokens(" ".join(ingredients))

    # Direct contains boosts
    s = 0.0
    if q in title.lower():
        s += 0.55
    if any(q in ig.lower() for ig in ingredients):
        s += 0.35

    # Token similarity fallback
    s += 0.5 * _jaccard(qtok, ttok)
    s += 0.25 * _jaccard(qtok, itok)

    return max(0.0, min(1.0, s))

def _fetch_candidates(query: str, limit: int) -> List[Tuple[int, str, str]]:
    """
    Pull candidate recipes by LIKE matching on title and ingredient names.
    Assumes schema:
      recipes(id PK, title, url)
      recipe_ingredients(recipe_id FK -> recipes.id, ingredient_name)
    """
    like = f"%{query.lower()}%"
    sql = """
        SELECT r.id, r.title, COALESCE(r.url, '') AS url,
               SUM( CASE
                        WHEN LOWER(r.title) LIKE %(like)s THEN 2
                        ELSE 0
                    END
               +   CASE
                        WHEN LOWER(ri.ingredient_name) LIKE %(like)s THEN 1
                        ELSE 0
                    END ) AS match_points
        FROM recipes r
        LEFT JOIN recipe_ingredients ri ON ri.recipe_id = r.id
        GROUP BY r.id, r.title, r.url
        HAVING match_points > 0
        ORDER BY match_points DESC, r.id ASC
        LIMIT %(limit)s
    """
    rows: List[Tuple[int, str, str]] = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"like": like, "limit": int(limit)})
            for rid, title, url, _points in cur.fetchall():
                rows.append((rid, title, url))
    return rows

def _fetch_ingredients_for(recipe_ids: List[int]) -> dict[int, List[str]]:
    if not recipe_ids:
        return {}
    sql = """
        SELECT recipe_id, ingredient_name
        FROM recipe_ingredients
        WHERE recipe_id IN %(ids)s
        ORDER BY recipe_id
    """
    ing_map: dict[int, List[str]] = {rid: [] for rid in recipe_ids}
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Many MySQL drivers accept IN %(ids)s when given a tuple
            cur.execute(sql, {"ids": tuple(recipe_ids)})
            for rid, name in cur.fetchall():
                if rid in ing_map:
                    if isinstance(name, str) and name.strip():
                        ing_map[rid].append(name.strip())
    return ing_map

def search_recipes(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Returns list of dicts:
      { id, title, url, ingredients: [str], query_score: float }
    """
    # 1) SQL candidates
    base = _fetch_candidates(query, limit * 3)  # over-fetch then score
    if not base:
        return []

    # 2) Ingredients
    ids = [rid for (rid, _title, _url) in base]
    ing_map = _fetch_ingredients_for(ids)

    # 3) Score & trim
    items: List[Dict[str, Any]] = []
    for rid, title, url in base:
        ingredients = ing_map.get(rid, [])
        qscore = _score_query(title, ingredients, query)
        items.append({
            "id": rid,
            "title": title,
            "url": url,
            "ingredients": ingredients,
            "query_score": round(qscore, 4),
        })

    # Sort by our score; fall back to id
    items.sort(key=lambda x: (x["query_score"], x["id"]), reverse=True)
    return items[:limit]
