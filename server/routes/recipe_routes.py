from fastapi import APIRouter, Depends, HTTPException
from auth import bearer_user
from db import get_conn
from config import REC_TABLE
import json, re

router = APIRouter()

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

@router.get("/api/recipe/{rid}")
def get_recipe_detail(rid: str, user=Depends(bearer_user)):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT id, title, ingredients, directions FROM {REC_TABLE} WHERE id=%s LIMIT 1", (rid,))
        row = cur.fetchone()
        if not row: raise HTTPException(status_code=404, detail="Recipe not found")
        return {
            "id": str(row["id"]),
            "title": row.get("title"),
            "ingredients": _to_list_jsonish(row.get("ingredients")),
            "directions": _to_list_jsonish(row.get("directions")),
        }
