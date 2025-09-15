# routes/recommend_routes.py
from __future__ import annotations

import os
import re
import json
from typing import List, Set, Tuple

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

# Project-level deps (existing in your repo)
from auth import bearer_user          # auth dependency (reads Bearer JWT)
from db import get_conn               # returns pymysql connection (DictCursor)

# ---------- Config ----------
REC_TABLE = os.getenv("DB_TABLE", "recipe.vector_db")
REC_MODEL_NAME = os.getenv("REC_MODEL", "BAAI/bge-large-en-v1.5")
REC_USE_COSINE = True  # if False, uses L2

# BGE: use the "search" instruction template for queries
REC_QUERY_TMPL = "Represent this sentence for searching relevant passages: {}"

# ---------- Router ----------
router = APIRouter()

# ---------- Models ----------
class RecommendIn(BaseModel):
    query: str
    k: int = 5          # final results to return
    m: int = 50         # candidate pool before rerank
    w1_query: float = 0.70
    w2_overlap: float = 0.20
    w3_cover: float = 0.10
    min_cover: float | None = None    # optional coverage gate

class RecItem(BaseModel):
    id: str
    title: str | None = None
    dist: float
    query_score: float | None = None
    overlap_score: float | None = None
    cover_score: float | None = None
    final: float | None = None
    used_from_pantry: List[str] | None = None
    missing: List[str] | None = None

class RecommendOut(BaseModel):
    items: List[RecItem]
    # when debug=1 we add these:
    debug_query_vec: List[float] | None = None
    debug_pantry_tokens: List[str] | None = None


# ---------- Embedding (lazy load) ----------
_rec_model = None

def get_rec_model():
    """Lazy load the sentence-transformers model once."""
    global _rec_model
    if _rec_model is None:
        from sentence_transformers import SentenceTransformer
        m = SentenceTransformer(REC_MODEL_NAME)
        # shorter sequences are fine; tuning optional
        m.max_seq_length = 512
        _rec_model = m
    return _rec_model

def vec_literal(v: np.ndarray) -> str:
    """Format vector for TiDB JSON/array literal comparison."""
    v = np.asarray(v, dtype=np.float32)
    return "[" + ", ".join(f"{x:.7f}" for x in v) + "]"


# ---------- Pantry + ingredient helpers ----------
_TOKEN_RE = re.compile(r"[^a-z0-9 ]")

def _norm_token(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"\d+/?\d*\s*", " ", s)
    s = re.sub(r"\b(c\.|cup|cups|tsp|tbsp|teaspoon|tablespoon|stick|sticks|pkg|package|cans?|oz|lb|lbs|large|small)\b", " ", s)
    s = _TOKEN_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()

def _to_list_jsonish(val) -> List[str]:
    """Tolerant → always returns list[str] (handles JSON/text/list)."""
    if val is None:
        return []
    if isinstance(val, (list, tuple)):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, (bytes, bytearray)):
        val = val.decode("utf-8", "ignore")
    s = str(val).strip()
    if not s:
        return []
    try:
        j = json.loads(s)
        if isinstance(j, list):
            return [str(x).strip() for x in j if str(x).strip()]
    except Exception:
        pass
    # fallback split on common delimiters
    parts = re.split(r"(?:\r?\n|\.\s+|;|,)", s)
    return [p.strip() for p in parts if p.strip()]

def parse_ingredients(cell) -> List[str]:
    """Return normalized ingredient tokens (per-line)."""
    raws = _to_list_jsonish(cell)
    out = []
    for t in raws:
        tok = _norm_token(str(t))
        if tok:
            out.append(tok)
    return out

def tokenize_recipe_ingredients(cell) -> Set[str]:
    return set(parse_ingredients(cell))

def pantry_name_set_for_user(cur, user_id: int) -> Set[str]:
    cur.execute("SELECT name FROM pantry_items WHERE user_id=%s", (user_id,))
    rows = cur.fetchall() or []
    out = set()
    for r in rows:
        name = r["name"]
        tok = _norm_token(name)
        if tok:
            out.add(tok)
    return out


# ---------- Overlap scoring ----------
def _regex_or_substring_match(pantry_token: str, ing_token: str) -> bool:
    pat = re.compile(rf"\b{re.escape(pantry_token)}\b", re.IGNORECASE)
    return bool(pat.search(ing_token) or pantry_token in ing_token or ing_token in pantry_token)

def pantry_overlap_scores(ingredients_cell, pantry_set: Set[str]) -> Tuple[float, float, List[str], List[str]]:
    """
    Returns (overlap_score, cover_score, used_from_pantry, missing_tokens)
      overlap_score = |ingredients ∩ pantry| / |ingredients ∪ pantry|   (Jaccard-like)
      cover_score   = |ingredients ∩ pantry| / |ingredients|
    """
    recipe_tokens = tokenize_recipe_ingredients(ingredients_cell)
    if not recipe_tokens or not pantry_set:
        return 0.0, 0.0, [], []

    used = []
    inter = 0

    for p in pantry_set:
        # consider it "used" if it matches any ingredient token
        if any(_regex_or_substring_match(p, t) for t in recipe_tokens):
            used.append(p)
            inter += 1

    union = len(recipe_tokens | pantry_set)
    overlap = (inter / union) if union else 0.0
    cover   = (inter / len(recipe_tokens)) if recipe_tokens else 0.0

    # a short list of "missing" tokens from the recipe (for UI)
    used_set = set(used)
    missing = []
    for t in recipe_tokens:
        if not any(u in t or t in u for u in used_set):
            missing.append(t)
        if len(missing) >= 5:
            break

    return overlap, cover, used[:10], missing


# ---------- Endpoint ----------
@router.post("/api/recommend", response_model=RecommendOut)
def recommend(
    body: RecommendIn,
    user=Depends(bearer_user),
    debug: int = Query(0, description="Return matching internals if 1"),
):
    q = (body.query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Empty query")

    # 1) Embed query
    model = get_rec_model()
    q_text = REC_QUERY_TMPL.format(q)
    q_vec = model.encode(
        [q_text],
        normalize_embeddings=REC_USE_COSINE,
        convert_to_numpy=True,
        show_progress_bar=False,
    )[0]
    q_lit = vec_literal(q_vec)

    dist_fn = "VEC_COSINE_DISTANCE" if REC_USE_COSINE else "VEC_L2_DISTANCE"
    TOP_N = max(10, body.m or 50)

    # 2) DB query for top-N vector matches (id, title, ingredients, dist)
    with get_conn() as conn, conn.cursor() as cur:
        uid = int(user["sub"])
        pantry_set = pantry_name_set_for_user(cur, uid)

        sql = f"""
            SELECT id, title, ingredients, {dist_fn}(embedding, %s) AS dist
            FROM {REC_TABLE}
            ORDER BY dist ASC
            LIMIT %s
        """
        cur.execute(sql, (q_lit, TOP_N))
        rows = cur.fetchall() or []

    # 3) Combine scores and re-rank
    w1, w2, w3 = float(body.w1_query), float(body.w2_overlap), float(body.w3_cover)
    min_cover = body.min_cover

    items = []
    for r in rows:
        rid = str(r["id"])
        title = r.get("title")
        dist = float(r["dist"])
        ings = r.get("ingredients")

        query_score = 1.0 / (1.0 + dist)  # smaller dist → larger score

        overlap_score, cover_score, used, missing = pantry_overlap_scores(ings, pantry_set)

        if min_cover is not None and cover_score < float(min_cover):
            continue

        final = w1 * query_score + w2 * overlap_score + w3 * cover_score

        items.append(
            dict(
                id=rid,
                title=title,
                dist=dist,
                query_score=query_score,
                overlap_score=overlap_score,
                cover_score=cover_score,
                final=final,
                used_from_pantry=used,
                missing=missing,
            )
        )

    items.sort(key=lambda x: x["final"], reverse=True)
    topk = items[: (body.k or 5)]

    out = RecommendOut(items=[RecItem(**it) for it in topk])
    if debug:
        out.debug_query_vec = [float(x) for x in q_vec.tolist()]
        # side-channel: what pantry tokens we used
        out.debug_pantry_tokens = sorted(list(pantry_set))
    return out
