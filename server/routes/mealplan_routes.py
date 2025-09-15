# routes/mealplan_routes.py
from __future__ import annotations

import json
import os
import re
from typing import List

from fastapi import APIRouter, Depends, HTTPException

from auth import bearer_user           # your existing auth dep (Bearer JWT)
from db import get_conn                # your existing DB connector (DictCursor)

router = APIRouter()

# Which recipe table to read from (same one you use for vector search)
REC_TABLE = os.getenv("DB_TABLE", "recipe.vector_db")

# ---------- helpers ----------
def _to_list_jsonish(val) -> List[str]:
    """Always return list[str] from JSON/text/list/bytes."""
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
    parts = re.split(r"(?:\r?\n|\.\s+|;|,)", s)
    return [p.strip() for p in parts if p.strip()]

# ---------- models ----------
from pydantic import BaseModel, Field
from typing import Literal, Optional

class PlanCreate(BaseModel):
    recipe_id: str
    planned_for: Optional[str] = Field(None, description="YYYY-MM-DD")
    slot: Optional[Literal["breakfast", "lunch", "dinner", "snack"]] = None
    servings: Optional[int] = None
    notes: Optional[str] = None

class PlanItemOut(BaseModel):
    id: int
    recipe_id: str
    title: str | None = None
    ingredients: list[str] = []
    directions: list[str] = []
    planned_for: str | None = None
    slot: str | None = None
    servings: int | None = None
    notes: str | None = None
    created_at: str

# ---------- endpoints ----------

@router.post("/api/mealplan", response_model=PlanItemOut)
def add_to_mealplan(body: PlanCreate, user=Depends(bearer_user)):
    """
    Copy a recipe (title/ingredients/directions) into the user's meal_plan.
    """
    uid = int(user["sub"])
    rid = (body.recipe_id or "").strip()
    if not rid:
        raise HTTPException(status_code=400, detail="Missing recipe_id")

    with get_conn() as conn, conn.cursor() as cur:
        # 1) fetch recipe from vector table
        cur.execute(
            f"SELECT id, title, ingredients, directions FROM {REC_TABLE} WHERE id=%s LIMIT 1",
            (rid,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Recipe not found")

        # 2) insert a copy into meal_plan
        cur.execute(
            """INSERT INTO meal_plan
               (user_id, recipe_id, title, ingredients, directions, planned_for, slot, servings, notes, source)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'recommend')""",
            (
                uid, str(row["id"]), row.get("title"),
                row.get("ingredients"), row.get("directions"),
                body.planned_for, body.slot, body.servings, body.notes
            ),
        )
        conn.commit()
        pid = cur.lastrowid

        # 3) reselect for clean output
        cur.execute(
            """SELECT id, recipe_id, title, ingredients, directions,
                      DATE_FORMAT(planned_for, '%%Y-%%m-%%d') AS planned_for,
                      slot, servings, notes,
                      DATE_FORMAT(created_at, '%%Y-%%m-%%d %%H:%%i:%%s') AS created_at
               FROM meal_plan WHERE id=%s AND user_id=%s""",
            (pid, uid),
        )
        out = cur.fetchone()
        if not out:
            raise HTTPException(status_code=500, detail="Failed to create plan item")

    return PlanItemOut(
        id=out["id"],
        recipe_id=str(out["recipe_id"]),
        title=out.get("title"),
        ingredients=_to_list_jsonish(out.get("ingredients")),
        directions=_to_list_jsonish(out.get("directions")),
        planned_for=out.get("planned_for"),
        slot=out.get("slot"),
        servings=out.get("servings"),
        notes=out.get("notes"),
        created_at=out["created_at"],
    )


@router.get("/api/mealplan")
def list_mealplan(user=Depends(bearer_user)):
    uid = int(user["sub"])
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, user_id, recipe_id, title,
                   ingredients, directions,
                   servings, DATE_FORMAT(planned_for,'%%Y-%%m-%%d') AS planned_for,
                   slot, notes,
                   DATE_FORMAT(created_at,'%%Y-%%m-%%d %%H:%%i:%%s') AS created_at
            FROM recipe.meal_plan
            WHERE user_id = %s
            ORDER BY COALESCE(planned_for, '9999-12-31') DESC, created_at DESC
            """,
            (uid,),
        )
        rows = cur.fetchall() or []

    items = []
    for r in rows:
        items.append({
            "id": r["id"],
            "recipe_id": str(r["recipe_id"]),
            "title": r.get("title"),
            "ingredients": _to_list_jsonish(r.get("ingredients")),
            "directions": _to_list_jsonish(r.get("directions")),
            "servings": r.get("servings"),
            "planned_for": r.get("planned_for"),
            "slot": r.get("slot"),
            "notes": r.get("notes"),
            "created_at": r.get("created_at"),
        })
    return {"items": items}


@router.delete("/api/mealplan/{plan_id}")
def delete_mealplan_item(plan_id: int, user=Depends(bearer_user)):
    uid = int(user["sub"])
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM meal_plan WHERE id=%s AND user_id=%s", (plan_id, uid))
        conn.commit()
    return {"ok": True}
