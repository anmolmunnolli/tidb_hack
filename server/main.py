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


# ---------- Request/Response models ----------
from pydantic import BaseModel

class RecommendIn(BaseModel):
    query: str
    k: int = 5

class RecItem(BaseModel):
    id: int
    title: str | None = None
    dist: float

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
def recommend(body: RecommendIn):
    q = body.query.strip()
    if not q:
        raise HTTPException(status_code=400, detail="Empty query")

    # 1) embed with BGE + template
    model = get_rec_model()
    q_text = REC_QUERY_TMPL.format(q)
    q_vec  = model.encode(
        [q_text],
        normalize_embeddings=REC_USE_COSINE,
        convert_to_numpy=True,
        show_progress_bar=False
    )[0]
    q_lit = vec_literal(q_vec)

    # 2) distance fn
    dist_fn = "VEC_COSINE_DISTANCE" if REC_USE_COSINE else "VEC_L2_DISTANCE"

    # 3) query TiDB
    with get_conn() as conn, conn.cursor() as cur:
        sql = f"""
            SELECT id, title, {dist_fn}(embedding, %s) AS dist
            FROM {REC_TABLE}
            ORDER BY dist ASC
            LIMIT %s
        """
        cur.execute(sql, (q_lit, body.k))
        rows = cur.fetchall()

    items = []
    for row in rows:
        # row can be dict if DictCursor; map safely
        rid   = row.get("id") if isinstance(row, dict) else row[0]
        title = row.get("title") if isinstance(row, dict) else row[1]
        dist  = row.get("dist") if isinstance(row, dict) else row[2]
        try:
            dist = float(dist)
        except Exception:
            pass
        items.append(RecItem(id=rid, title=title, dist=dist))
    return RecommendOut(items=items)
