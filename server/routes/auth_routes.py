from fastapi import APIRouter, HTTPException
from schemas import RegisterIn, LoginIn, AuthOut, UserOut
from auth import sign_token
from db import get_conn
import bcrypt

router = APIRouter()

def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
def check_password(p: str, h: str) -> bool:
    try: return bcrypt.checkpw(p.encode("utf-8"), h.encode("utf-8"))
    except Exception: return False

@router.post("/api/register", response_model=AuthOut)
def register(body: RegisterIn):
    email = body.email.lower().strip()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE email=%s", (email,))
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="Email already registered")
        cur.execute(
            "INSERT INTO users (email, first_name, last_name, password_hash) VALUES (%s,%s,%s,%s)",
            (email, body.first_name.strip(), body.last_name.strip(), hash_password(body.password)),
        )
        conn.commit()
        uid = cur.lastrowid
        user = {"id": uid, "email": email, "first_name": body.first_name.strip(), "last_name": body.last_name.strip()}
        return {"token": sign_token(user), "user": user}

@router.post("/api/login", response_model=AuthOut)
def login(body: LoginIn):
    email = body.email.lower().strip()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE email=%s", (email,))
        row = cur.fetchone()
        if not row or not check_password(body.password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        user = {"id": row["id"], "email": row["email"], "first_name": row["first_name"], "last_name": row["last_name"]}
        return {"token": sign_token(user), "user": user}
