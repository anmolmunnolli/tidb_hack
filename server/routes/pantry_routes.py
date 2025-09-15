# routes/pantry_routes.py
from fastapi import APIRouter, Depends, HTTPException
from decimal import Decimal
from models import PantryIn, PantryOut
from auth import bearer_user
from db import get_conn
from agents.normalizer_agent import normalize_line_llm, NormalizedLine  # ← import the type


router = APIRouter()

@router.get("/api/pantry")
def list_pantry(user=Depends(bearer_user)):
    uid = int(user["sub"])
    with get_conn() as conn, conn.cursor() as cur:
        print("[PANTRY] list for user_id:", uid)
        cur.execute(
            """SELECT id, name, qty, unit,
                      DATE_FORMAT(expires_on,'%%Y-%%m-%%d') AS expires_on,
                      DATE_FORMAT(added_at,'%%Y-%%m-%%d %%H:%%i:%%s') AS added_at
               FROM pantry_items
               WHERE user_id=%s
               ORDER BY added_at DESC, id DESC""",
            (uid,),
        )
        rows = cur.fetchall() or []
        print("[PANTRY] list rows:", len(rows))
        return rows

def _to_float(x):
    if x is None: return None
    if isinstance(x, Decimal): return float(x)
    try:
        return float(x)
    except Exception:
        return None

@router.post("/api/pantry", response_model=PantryOut)
def create_item(body: PantryIn, user=Depends(bearer_user)):
    uid = int(user["sub"])

    # 1) Normalize (always return NormalizedLine to avoid dict/obj mismatch)
    try:
        norm: NormalizedLine = normalize_line_llm(
            f"{body.qty or ''} {body.unit or ''} {body.name or ''}".strip()
        )
    except Exception as e:
        print("[PANTRY] normalize_line_llm error:", repr(e))
        # fallback that still returns a NormalizedLine instance
        norm = NormalizedLine(
            name=(body.name or "").strip().lower(),
            qty=_to_float(body.qty),
            unit=(body.unit or None if body.unit else None)
        )

    print("[PANTRY] user_id:", uid,
          "raw:", body.model_dump(),
          "norm:", norm.model_dump())

    sql_ins = """
        INSERT INTO pantry_items (
            user_id, name, qty, unit, expires_on,
            canonical_name, norm_qty, norm_unit, norm_conf, norm_source
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,0.9,'llm')
    """

    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute(sql_ins, (
                uid,
                (body.name or "").strip(),
                _to_float(body.qty),
                body.unit,
                body.expires_on,
                norm.name or None,         # ← attribute access (not .get)
                _to_float(norm.qty),       # ← convert Decimal → float
                norm.unit,                 # ← attribute access
            ))
            print("[PANTRY] insert rowcount:", cur.rowcount)
            if cur.rowcount != 1:
                conn.rollback()
                raise HTTPException(status_code=500, detail="Insert failed (rowcount != 1)")

            new_id = cur.lastrowid
            print("[PANTRY] new_id:", new_id)
            conn.commit()

            cur.execute(
                """SELECT id, name, qty, unit,
                          DATE_FORMAT(expires_on,'%%Y-%%m-%%d') AS expires_on,
                          DATE_FORMAT(added_at,'%%Y-%%m-%%d %%H:%%i:%%s') AS added_at
                   FROM pantry_items
                   WHERE id=%s AND user_id=%s""",
                (new_id, uid),
            )
            row = cur.fetchone()
            print("[PANTRY] selected row:", row)
            if not row:
                raise HTTPException(status_code=500, detail="Inserted but could not re-select")

            return row

        except HTTPException:
            raise
        except Exception as e:
            conn.rollback()
            print("[PANTRY] DB error:", repr(e))
            raise HTTPException(status_code=500, detail=f"DB insert error: {type(e).__name__}")
        
@router.put("/api/pantry/{item_id}", response_model=PantryOut)
def update_item(item_id: int, body: PantryIn, user=Depends(bearer_user)):
    uid = int(user["sub"])
    norm = normalize_line_llm(f"{body.qty or ''} {body.unit or ''} {body.name or ''}".strip())
    norm_name = norm.name if isinstance(norm, NormalizedLine) else norm.get("name")
    norm_qty  = norm.qty  if isinstance(norm, NormalizedLine) else norm.get("qty")
    norm_unit = norm.unit if isinstance(norm, NormalizedLine) else norm.get("unit")

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE pantry_items
            SET name=%s, qty=%s, unit=%s, expires_on=%s,
                canonical_name=%s, norm_qty=%s, norm_unit=%s, norm_conf=0.9, norm_source='llm'
            WHERE id=%s AND user_id=%s""",
            (body.name.strip(), body.qty, body.unit, body.expires_on,
            norm_name, norm_qty, norm_unit, item_id, uid),
        )
        conn.commit()
        cur.execute(
            """SELECT id, name, qty, unit,
                      DATE_FORMAT(expires_on,'%%Y-%%m-%%d') AS expires_on,
                      DATE_FORMAT(added_at,'%%Y-%%m-%%d %%H:%%i:%%s') AS added_at
               FROM pantry_items WHERE id=%s AND user_id=%s""",
            (item_id, uid),
        )
        row = cur.fetchone()
        if not row: raise HTTPException(status_code=404, detail="Not found")
        return row

@router.delete("/api/pantry/{item_id}")
def delete_item(item_id: int, user=Depends(bearer_user)):
    uid = int(user["sub"])
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM pantry_items WHERE id=%s AND user_id=%s", (item_id, uid))
        conn.commit()
    return {"ok": True}
