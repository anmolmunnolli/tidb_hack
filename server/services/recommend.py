from sentence_transformers import SentenceTransformer
import numpy as np, re, json
from config import REC_TABLE
from db import get_conn
from schemas import RecommendIn, RecommendOut, RecItem

REC_MODEL_NAME = "BAAI/bge-large-en-v1.5"
REC_USE_COSINE = True
REC_QUERY_TMPL = "Represent this sentence for searching relevant passages: {}"
_model = None

def get_model():
    global _model
    if _model is None:
        m = SentenceTransformer(REC_MODEL_NAME)
        m.max_seq_length = 512
        _model = m
    return _model

def _to_list_jsonish(val):
    if val is None: return []
    if isinstance(val,(list,tuple)): return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val,(bytes,bytearray)): val = val.decode("utf-8","ignore")
    s = str(val).strip()
    if not s: return []
    try:
        j = json.loads(s)
        if isinstance(j,list): return [str(x).strip() for x in j if str(x).strip()]
    except Exception: pass
    parts = re.split(r"(?:\r?\n|\.\s+|;|,)", s)
    return [p.strip() for p in parts if p.strip()]

def _tokenize(cell) -> set[str]:
    return set(_to_list_jsonish(cell))

def recommend(user_id: int, body: RecommendIn) -> RecommendOut:
    q = body.query.strip()
    if not q: return RecommendOut(items=[])
    model = get_model()
    q_text = REC_QUERY_TMPL.format(q)
    q_vec  = model.encode([q_text], normalize_embeddings=REC_USE_COSINE, convert_to_numpy=True)[0]
    q_lit = "[" + ", ".join(f"{x:.7f}" for x in np.asarray(q_vec, dtype=np.float32)) + "]"
    dist_fn = "VEC_COSINE_DISTANCE" if REC_USE_COSINE else "VEC_L2_DISTANCE"
    TOP_N = max(10, body.m or 50)

    with get_conn() as conn, conn.cursor() as cur:
        # pantry set
        cur.execute("SELECT name FROM pantry_items WHERE user_id=%s", (user_id,))
        pantry = set([re.sub(r"[^a-z0-9\s]"," ", (r["name"] or "").lower()).strip() for r in (cur.fetchall() or []) if r and r.get("name")])

        cur.execute(f"""
            SELECT id, title, ingredients, {dist_fn}(embedding, %s) AS dist
            FROM {REC_TABLE}
            ORDER BY dist ASC
            LIMIT %s
        """, (q_lit, TOP_N))
        rows = cur.fetchall() or []

    results = []
    for r in rows:
        rid   = str(r["id"])
        title = r.get("title")
        dist  = float(r["dist"])
        ings  = r.get("ingredients")
        recipe_tokens = _tokenize(ings)
        query_score = 1.0 / (1.0 + dist)
        inter = len(recipe_tokens & pantry)
        union = len(recipe_tokens | pantry) if (recipe_tokens or pantry) else 1
        overlap_score = inter / union
        cover_score = inter / (len(recipe_tokens) or 1)
        final = body.w1_query * query_score + body.w2_overlap * overlap_score + body.w3_cover * cover_score

        used = [p for p in pantry if any(p in t or t in p for t in recipe_tokens)][:10]
        missing = []
        for t in recipe_tokens:
            if not any(u in t or t in u for u in used):
                missing.append(t)
            if len(missing) >= 5: break

        results.append(dict(id=rid, title=title, dist=dist, query_score=query_score,
                            overlap_score=overlap_score, cover_score=cover_score,
                            final=final, used_from_pantry=used, missing=missing))
    results.sort(key=lambda x: x["final"], reverse=True)
    topk = results[: (body.k or 5)]
    return RecommendOut(items=[RecItem(**it) for it in topk])
