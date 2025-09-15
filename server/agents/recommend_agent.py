# server/agents/recommend_agent.py
from __future__ import annotations
from typing import List, Dict, Any, Set, Tuple
import re, json, numpy as np
from db import get_conn

# ---------- config & encoder ----------
import os
from sentence_transformers import SentenceTransformer

REC_TABLE       = os.getenv("REC_TABLE", "recipe.vector_db")
REC_USE_COSINE  = True
REC_QUERY_TMPL  = "Represent this sentence for searching relevant passages: {}"
REC_MODEL_NAME  = os.getenv("REC_MODEL_NAME", "BAAI/bge-large-en-v1.5")
REC_MAX_LEN     = 512

_model = None
def get_rec_model():
    global _model
    if _model is None:
        m = SentenceTransformer(REC_MODEL_NAME)
        m.max_seq_length = REC_MAX_LEN
        _model = m
    return _model

def vec_literal(v: np.ndarray) -> str:
    v = np.asarray(v, dtype=np.float32)
    return "[" + ", ".join(f"{x:.7f}" for x in v) + "]"

# ---------- tokenization identical to your original ----------
_TOKEN_RE = re.compile(r"[^a-z ]")

def _norm_token(s: str) -> str:
    s = s.lower()
    s = re.sub(r"\d+/?\d*\s*", " ", s)
    s = re.sub(r"\b(c\.|cup|cups|tsp|tbsp|teaspoon|tablespoon|stick|sticks|pkg|package|cans?|oz|lb|lbs|large|small)\b", " ", s)
    s = _TOKEN_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()

def _to_list_jsonish(val) -> List[str]:
    if val is None: return []
    if isinstance(val, (list, tuple)): return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, (bytes, bytearray)): val = val.decode("utf-8", "ignore")
    s = str(val).strip()
    if not s: return []
    try:
        j = json.loads(s)
        if isinstance(j, list): return [str(x).strip() for x in j if str(x).strip()]
    except Exception:
        pass
    parts = re.split(r"(?:\r?\n|\.\s+|;|,)", s)
    return [p.strip() for p in parts if p.strip()]

def tokenize_recipe_ingredients(cell) -> Set[str]:
    toks = []
    for t in _to_list_jsonish(cell):
        tt = _norm_token(t)
        if tt: toks.append(tt)
    return set(toks)

def pantry_name_set_for_user(cur, user_id: int) -> Set[str]:
    cur.execute("SELECT COALESCE(canonical_name, name) AS n FROM pantry_items WHERE user_id=%s", (user_id,))
    out = set()
    for row in cur.fetchall() or []:
        tok = _norm_token(row["n"] or "")
        if tok: out.add(tok)
    return out

def _match_used(recipe_tokens: Set[str], pantry_set: Set[str]) -> Tuple[List[str], float, float]:
    if not recipe_tokens or not pantry_set:
        return [], 0.0, 0.0
    used = []
    for p in pantry_set:
        if any(p in t or t in p for t in recipe_tokens):
            used.append(p)
    inter = len(used)
    union = len(recipe_tokens | pantry_set)
    overlap = (inter / union) if union else 0.0
    cover   = (inter / len(recipe_tokens)) if recipe_tokens else 0.0
    return used, overlap, cover

def _ingredient_tags(cell, pantry_set: Set[str]) -> List[Dict[str, Any]]:
    tags = []
    toks = _to_list_jsonish(cell)
    for t in toks:
        norm = _norm_token(t)
        have = False
        if norm:
            have = any(norm == p or norm in p or p in norm for p in pantry_set)
        tags.append({"text": t, "have": bool(have)})
    return tags

def recommend_with_agents(
    *, user_id: int, query: str, k: int, m: int,
    w1: float, w2: float, w3: float, min_cover: float | None,
):
    model = get_rec_model()
    q_text = REC_QUERY_TMPL.format(query.strip())
    q_vec  = model.encode([q_text], normalize_embeddings=REC_USE_COSINE,
                          convert_to_numpy=True, show_progress_bar=False)[0]
    q_lit = vec_literal(q_vec)
    dist_fn = "VEC_COSINE_DISTANCE" if REC_USE_COSINE else "VEC_L2_DISTANCE"
    TOP_N = max(10, m)

    with get_conn() as conn, conn.cursor() as cur:
        pantry_set = pantry_name_set_for_user(cur, user_id)
        sql = f"""
            SELECT id, title, ingredients, {dist_fn}(embedding, %s) AS dist
            FROM {REC_TABLE}
            ORDER BY dist ASC
            LIMIT %s
        """
        cur.execute(sql, (q_lit, TOP_N))
        cands = cur.fetchall() or []

    items = []
    for r in cands:
        rid, title, dist, ings = str(r["id"]), r.get("title"), float(r["dist"]), r.get("ingredients")
        query_score = 1.0 / (1.0 + dist)
        recipe_tokens = tokenize_recipe_ingredients(ings)
        used, overlap_score, cover_score = _match_used(recipe_tokens, pantry_set)

        if min_cover is not None and cover_score < float(min_cover):
            continue

        final = w1*query_score + w2*overlap_score + w3*cover_score
        missing = []
        if recipe_tokens:
            used_set = set(used)
            for t in recipe_tokens:
                if not any(u in t or t in u for u in used_set):
                    missing.append(t)
                if len(missing) >= 5: break

        items.append({
            "id": rid,
            "title": title,
            "dist": dist,
            "query_score": query_score,
            "overlap_score": overlap_score,
            "cover_score": cover_score,
            "final": final,
            "used_from_pantry": used[:10],
            "missing": missing,
            # "tags": _ingredient_tags(ings, pantry_set),  # uncomment if your UI highlights per-line
        })

    items.sort(key=lambda x: x["final"], reverse=True)
    return items[:k]
