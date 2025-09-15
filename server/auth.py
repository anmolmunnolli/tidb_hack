# server/auth.py
import os, time, bcrypt, jwt
from fastapi import Header, HTTPException
from jwt import ExpiredSignatureError, InvalidTokenError
from dotenv import load_dotenv
load_dotenv()

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret")
JWT_EXP_SECONDS = 7 * 24 * 3600

def sign_token(user_row: dict) -> str:
    payload = {
        "sub": str(user_row["id"]),
        "email": user_row["email"],
        "first_name": user_row.get("first_name"),
        "last_name": user_row.get("last_name"),
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXP_SECONDS,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def bearer_user(authorization: str | None = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.split(" ", 1)[1]
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
