import os, time, bcrypt, jwt, pymysql
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from dotenv import load_dotenv
from pydantic import BaseModel, condecimal
from typing import Optional, List
from fastapi import Request
import jwt
from typing import Optional
from fastapi import Header, HTTPException
from jwt import ExpiredSignatureError, InvalidTokenError
import re, json
from typing import List, Dict, Any, Tuple, Set
import numpy as np
from sentence_transformers import SentenceTransformer
import pymysql
import numpy as np
from sentence_transformers import SentenceTransformer
import ssl as _ssl
from pydantic import BaseModel

# --- model/config for recommendations (match your CLI) ---
REC_MODEL_NAME = "BAAI/bge-large-en-v1.5"   # 1024-d
REC_MAX_LEN    = 512
REC_USE_COSINE = True
REC_TABLE      = os.getenv("DB_TABLE", "recipe.vector_db")
REC_QUERY_TMPL = "Represent this sentence for searching relevant passages: {}"                    # cosine => normalize=True

from typing import List
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
import numpy as np




load_dotenv()

DB_CFG = dict(
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT", "4000")),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    database=os.getenv("DB_DATABASE"),
    ssl={"ssl": {}}  # TiDB Cloud requires TLS; local TiDB will also accept this.
)

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret")
JWT_EXP_SECONDS = 7 * 24 * 3600

app = FastAPI(title="TiDB Auth API (FastAPI)")


    

@app.middleware("http")
async def log_auth_header(request: Request, call_next):
    if request.url.path.startswith("/api/pantry"):
        print("AUTH HDR:", request.headers.get("authorization"))
    return await call_next(request)

# ⚠️ In production, restrict origins to your domain
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Models ----------

class PantryIn(BaseModel):
    name: str
    qty: Optional[condecimal(max_digits=10, decimal_places=2)] = None
    unit: Optional[str] = None
    expires_on: Optional[str] = None  # "YYYY-MM-DD"

class PantryOut(BaseModel):
    id: int
    name: str
    qty: Optional[float] = None
    unit: Optional[str] = None
    expires_on: Optional[str] = None
    added_at: str


class RegisterIn(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    password: str

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class UserOut(BaseModel):
    id: int
    email: EmailStr
    first_name: str
    last_name: str

class AuthOut(BaseModel):
    token: str
    user: UserOut

# ---------- Helpers ----------
def get_conn():
    return pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **DB_CFG)

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")

def check_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False

# main.py

_rec_model = None
def get_rec_model():
    global _rec_model
    if _rec_model is None:
        m = SentenceTransformer(REC_MODEL_NAME)
        m.max_seq_length = REC_MAX_LEN
        _rec_model = m
    return _rec_model

def vec_literal(v: np.ndarray) -> str:
    v = np.asarray(v, dtype=np.float32)
    return "[" + ", ".join(f"{x:.7f}" for x in v) + "]"





# very common “filler” items so they don’t dominate overlap
# ---------- Pantry + ingredient normalization helpers ----------
import re, json

_MEASURE_WORDS = r"(?:c\.|cup|cups|tsp|tbsp|teaspoon|tablespoon|stick|sticks|pkg|package|can|cans|oz|ounce|ounces|lb|lbs|pound|pounds|large|small|medium)"

def _norm_token(s: str) -> str:
    """Normalize an ingredient/pantry name to a simple comparable token."""
    if not s:
        return ""
    s = s.lower()
    # remove amounts & fractions (e.g., "1 1/2", "¾", "3")
    s = re.sub(r"\d+\/\d+|\d+(?:\.\d+)?|¼|½|¾|⅓|⅔|⅛|⅜|⅝|⅞", " ", s)
    # drop common measure words
    s = re.sub(rf"\b{_MEASURE_WORDS}\b", " ", s)
    # keep only letters/spaces
    s = re.sub(r"[^a-z ]", " ", s)
    # collapse spaces
    s = re.sub(r"\s+", " ", s).strip()
    return s

def parse_ingredients(cell) -> list[str]:
    """
    Ingredients in DB can be a JSON list (preferred) or a raw string.
    Return a list of normalized tokens.
    """
    if not cell:
        return []
    raw_list = []
    if isinstance(cell, (list, tuple)):
        raw_list = list(cell)
    else:
        try:
            j = json.loads(cell)
            if isinstance(j, list):
                raw_list = j
            else:
                raw_list = [str(cell)]
        except Exception:
            raw_list = [str(cell)]

    out = []
    for t in raw_list:
        tok = _norm_token(str(t))
        if tok:
            out.append(tok)
    return out

def tokenize_recipe_ingredients(cell) -> set[str]:
    """Unique normalized tokens for a recipe’s ingredients."""
    return set(parse_ingredients(cell))

def pantry_name_set_for_user(cur, user_id: int) -> set[str]:
    """
    Load the user’s pantry item names and normalize them.
    Works with DictCursor or tuple cursor.
    """
    cur.execute("SELECT name FROM pantry_items WHERE user_id=%s", (user_id,))
    rows = cur.fetchall() or []
    out = set()
    for row in rows:
        name = row["name"] if isinstance(row, dict) else row[0]
        tok = _norm_token(name)
        if tok:
            out.add(tok)
    return out


def overlap_count(ingredients_cell: str, pantry_set: set[str]) -> tuple[int, list[str]]:
    """Count matches and return which pantry items were used."""
    ing_tokens = parse_ingredients(ingredients_cell)
    if not ing_tokens or not pantry_set:
        return 0, []

    matched = []
    score = 0
    for p in pantry_set:
        # regex word boundary search across each ingredient token
        pat = re.compile(rf"\b{re.escape(p)}\b", re.IGNORECASE)
        for ing in ing_tokens:
            if pat.search(ing) or p in ing or ing in p:
                score += 1
                matched.append(p)
                break  # count pantry item once
    return score, matched

def _pantry_token_set(cur, user_id: int) -> Set[str]:
    """Fetch pantry names and normalize to comparable tokens."""
    cur.execute("SELECT name FROM pantry_items WHERE user_id=%s", (user_id,))
    out = set()
    for row in cur.fetchall() or []:
        name = row["name"] if isinstance(row, dict) else row[0]
        tok = _norm_token(name or "")
        if tok and tok not in STOP_TOKENS:
            out.add(tok)
    return out

def tokenize_recipe_ingredients(cell: str) -> set[str]:
    # normalized unique tokens for Jaccard/coverage
    return set(parse_ingredients(cell))

def _jaccard(a: Set[str], b: Set[str]) -> float:
    return 0.0 if not a and not b else len(a & b) / len(a | b)

def _coverage(recipe_tokens: Set[str], pantry: Set[str]) -> float:
    return 0.0 if not recipe_tokens else len(recipe_tokens & pantry) / len(recipe_tokens)

def _normalize_dist_scores(dists: List[float]) -> List[float]:
    """Convert distances to 0..1, higher is better (smaller distance = better)."""
    if not dists:
        return []
    lo, hi = min(dists), max(dists)
    if hi <= lo:
        return [1.0] * len(dists)
    return [1 - (d - lo) / (hi - lo) for d in dists]

# ---------- Request/Response models ----------
from pydantic import BaseModel

class RecommendIn(BaseModel):
    query: str
    k: int = 5          # final results to return
    m: int = 50         # candidate pool before rerank
    w1_query: float = 0.70
    w2_overlap: float = 0.20
    w3_cover: float = 0.10
    min_cover: float | None = None  # optional gate, e.g. 0.2

class RecItem(BaseModel):
    id: int
    title: str | None = None
    dist: float
    # extras (align with your TS type)
    query_score: float | None = None
    overlap_score: float | None = None
    cover_score: float | None = None
    final: float | None = None
    used_from_pantry: list[str] = []
    missing: list[str] = []

class RecommendOut(BaseModel):
    items: list[RecItem]


def sign_token(user_row: dict) -> str:
    payload = {
        "sub": str(user_row["id"]),   # ← make it a string
        "email": user_row["email"],
        "first_name": user_row["first_name"],
        "last_name": user_row["last_name"],
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXP_SECONDS,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def bearer_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        print("AUTH: missing/format")
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        # Debug: see who we decoded
        print("DECODE OK:", payload.get("sub"), payload.get("email"))
        return payload
    except ExpiredSignatureError:
        print("DECODE FAIL: expired")
        raise HTTPException(status_code=401, detail="Token expired")
    except InvalidTokenError as e:
        # bad signature / wrong secret / malformed / etc.
        print("DECODE FAIL:", type(e).__name__, str(e))
        raise HTTPException(status_code=401, detail="Invalid token")

# ---------- Routes ----------
@app.post("/api/register", response_model=AuthOut)
def register(body: RegisterIn):
    email = body.email.lower().strip()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE email=%s", (email,))
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="Email already registered")

        pw_hash = hash_password(body.password)
        cur.execute(
            "INSERT INTO users (email, first_name, last_name, password_hash) VALUES (%s, %s, %s, %s)",
            (email, body.first_name.strip(), body.last_name.strip(), pw_hash),
        )
        conn.commit()
        user_id = cur.lastrowid

        user = {"id": user_id, "email": email, "first_name": body.first_name.strip(), "last_name": body.last_name.strip()}
        token = sign_token(user)
        return {"token": token, "user": user}

@app.post("/api/login", response_model=AuthOut)
def login(body: LoginIn):
    email = body.email.lower().strip()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE email=%s", (email,))
        row = cur.fetchone()
        if not row or not check_password(body.password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        user = {"id": row["id"], "email": row["email"], "first_name": row["first_name"], "last_name": row["last_name"]}
        token = sign_token(user)
        return {"token": token, "user": user}

@app.get("/api/me")
def me(user=Depends(bearer_user)):
    return {"user": user}

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/api/pantry", response_model=List[PantryOut])
def list_pantry(user=Depends(bearer_user)):
    uid = int(user["sub"])
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, name, qty, unit,
                      DATE_FORMAT(expires_on, '%%Y-%%m-%%d') AS expires_on,
                      DATE_FORMAT(added_at, '%%Y-%%m-%%d %%H:%%i:%%s') AS added_at
               FROM pantry_items
               WHERE user_id=%s
               ORDER BY added_at DESC, id DESC""",
            (uid,),
        )
        rows = cur.fetchall()
        return rows

@app.post("/api/pantry", response_model=PantryOut)
def create_pantry_item(body: PantryIn, user=Depends(bearer_user)):
    uid = int(user["sub"])
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO pantry_items (user_id, name, qty, unit, expires_on)
               VALUES (%s, %s, %s, %s, %s)""",
            (uid, body.name.strip(), body.qty, body.unit, body.expires_on),
        )
        conn.commit()
        new_id = cur.lastrowid
        cur.execute(
            """SELECT id, name, qty, unit,
                      DATE_FORMAT(expires_on, '%%Y-%%m-%%d') AS expires_on,
                      DATE_FORMAT(added_at, '%%Y-%%m-%%d %%H:%%i:%%s') AS added_at
               FROM pantry_items
               WHERE id=%s AND user_id=%s""",
            (new_id, uid),
        )
        row = cur.fetchone()
        return row

@app.delete("/api/pantry/{item_id}")
def delete_pantry_item(item_id: int, user=Depends(bearer_user)):
    uid = int(user["sub"])
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM pantry_items WHERE id=%s AND user_id=%s", (item_id, uid))
        conn.commit()
    return {"ok": True}

@app.put("/api/pantry/{item_id}", response_model=PantryOut)
def update_pantry_item(item_id: int, body: PantryIn, user=Depends(bearer_user)):
    uid = int(user["sub"])
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE pantry_items
               SET name=%s, qty=%s, unit=%s, expires_on=%s
               WHERE id=%s AND user_id=%s""",
            (body.name.strip(), body.qty, body.unit, body.expires_on, item_id, uid),
        )
        conn.commit()
        cur.execute(
            """SELECT id, name, qty, unit,
                      DATE_FORMAT(expires_on, '%%Y-%%m-%%d') AS expires_on,
                      DATE_FORMAT(added_at, '%%Y-%%m-%%d %%H:%%i:%%s') AS added_at
               FROM pantry_items
               WHERE id=%s AND user_id=%s""",
            (item_id, uid),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        return row
    

@app.post("/api/recommend", response_model=RecommendOut)
def recommend(body: RecommendIn, user=Depends(bearer_user)):
    q = body.query.strip()
    if not q:
        raise HTTPException(status_code=400, detail="Empty query")

    # 1) embed query (BGE + template)
    model = get_rec_model()
    q_text = REC_QUERY_TMPL.format(q)
    q_vec  = model.encode(
        [q_text],
        normalize_embeddings=REC_USE_COSINE,
        convert_to_numpy=True,
        show_progress_bar=False
    )[0]
    q_lit = vec_literal(q_vec)

    dist_fn = "VEC_COSINE_DISTANCE" if REC_USE_COSINE else "VEC_L2_DISTANCE"
    TOP_N = max(10, body.m or 50)

    with get_conn() as conn, conn.cursor() as cur:
        # pantry set
        uid = int(user["sub"])
        pantry_set = pantry_name_set_for_user(cur, uid)

        # grab vector top-N (now include ingredients)
        sql = f"""
            SELECT id, title, ingredients, {dist_fn}(embedding, %s) AS dist
            FROM {REC_TABLE}
            ORDER BY dist ASC
            LIMIT %s
        """
        cur.execute(sql, (q_lit, TOP_N))
        rows = cur.fetchall() or []

    # weights / gate
    w1 = float(body.w1_query)
    w2 = float(body.w2_overlap)
    w3 = float(body.w3_cover)
    min_cover = body.min_cover

    # 2) score & rerank
    results = []
    for r in rows:
        rid   = r["id"]
        title = r.get("title")
        dist  = float(r["dist"])
        ings  = r.get("ingredients")

        # query component (smaller dist -> bigger score)
        query_score = 1.0 / (1.0 + dist)

        # pantry overlap signals
        recipe_tokens = tokenize_recipe_ingredients(ings)
        used = []
        if pantry_set and recipe_tokens:
            # exact/substring regex pass (same as you added before)
            # count matches & build used list
            matched = []
            for p in pantry_set:
                pat = re.compile(rf"\b{re.escape(p)}\b", re.IGNORECASE)
                if any(pat.search(t) or p in t or t in p for t in recipe_tokens):
                    matched.append(p)

            used = matched
            inter = len(matched)
            union = len(recipe_tokens | pantry_set)
            overlap_score = (inter / union) if union else 0.0
            cover_score   = (inter / len(recipe_tokens)) if recipe_tokens else 0.0
        else:
            overlap_score = 0.0
            cover_score   = 0.0

        # optional gate
        if min_cover is not None and cover_score < float(min_cover):
            continue

        final = w1 * query_score + w2 * overlap_score + w3 * cover_score

        # a short “missing” preview (handy in UI)
        missing = []
        if recipe_tokens and pantry_set:
            # choose up to 5 tokens that didn't match
            # simple heuristic: tokens not in ‘used’ substrings
            used_set = set(used)
            for t in recipe_tokens:
                if not any(u in t or t in u for u in used_set):
                    missing.append(t)
                if len(missing) >= 5:
                    break

        results.append({
            "id": rid,
            "title": title,
            "dist": dist,
            "query_score": query_score,
            "overlap_score": overlap_score,
            "cover_score": cover_score,
            "final": final,
            "used_from_pantry": used[:10],
            "missing": missing,
        })

    results.sort(key=lambda x: x["final"], reverse=True)
    topk = results[: (body.k or 5)]

    return RecommendOut(items=[RecItem(**it) for it in topk])
