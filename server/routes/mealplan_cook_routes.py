# routes/mealplan_cook_routes.py
from __future__ import annotations

import json, re
from typing import List, Tuple, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import bearer_user                  # JWT dependency
from db import get_conn                      # DB connector (DictCursor)
from rapidfuzz import fuzz
from pint import UnitRegistry

# ⚠️ NEW: context-aware unit conversion (uses DB density/per-count facts)
from utils.units import convert_with_context

router = APIRouter()

ureg = UnitRegistry()
Q_ = ureg.Quantity

# ---------- small helpers (self-contained) ----------

def _to_list_jsonish(val) -> List[str]:
    """Tolerant list parser for ingredients/directions in DB."""
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

# fraction/number like "1 1/2", "3/4", "2.5"
def _parse_qty(q: str) -> float:
    q = q.strip()
    if " " in q and "/" in q:  # "1 1/2"
        a, b = q.split(" ", 1)
        num, den = b.split("/", 1)
        return float(a) + float(num) / float(den)
    if "/" in q:
        num, den = q.split("/", 1)
        return float(num) / float(den)
    return float(q)

# unit + name regex (relaxed)
_FRAC = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"
_UNIT = r"(teaspoons?|tsp|tablespoons?|tbsp|cups?|c|mls?|ml|liters?|l|pints?|quarts?|gallons?|ounces?|oz|pounds?|lbs?|grams?|g|kilograms?|kg|stick|sticks|piece|pieces|pc|pcs|count|can|cans)"
PANTRY_LINE_RE = re.compile(rf"^\s*(?P<qty>{_FRAC})?\s*(?P<unit>{_UNIT})?\s*(?P<name>.+?)\s*$", re.I)

UNIT_ALIASES = {
    "tsp": "teaspoon", "tsps": "teaspoon",
    "tbsp": "tablespoon", "tbsps": "tablespoon", "tbl": "tablespoon",
    "c": "cup", "cups": "cup",
    "ozs": "ounce", "lbs": "pound", "gms": "gram", "kgs": "kilogram",
    "lt": "liter", "l": "liter", "mls": "milliliter",
    "pcs": "count", "pc": "count", "piece": "count", "pieces": "count",
}

def _canon_unit(u: Optional[str]) -> Optional[str]:
    if not u: return None
    u = u.strip().lower()
    return UNIT_ALIASES.get(u, u)

_TOKEN_RE = re.compile(r"[^a-z0-9 ]")
def _norm_token(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"\d+/?\d*\s*", " ", s)
    s = re.sub(r"\b(c\.|cup|cups|tsp|tbsp|teaspoon|tablespoon|stick|sticks|pkg|package|cans?|oz|lb|lbs|large|small)\b", " ", s)
    s = _TOKEN_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()

def _clean(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def parse_ingredient_line(line: str) -> Tuple[Optional[float], Optional[str], str]:
    """
    Return (qty, unit, name_clean). If no qty/unit, returns (None, None, cleaned name).
    """
    raw = (line or "").strip()
    m = PANTRY_LINE_RE.match(raw)
    if not m:
        return None, None, _clean(raw)
    qty = None
    if m.group("qty"):
        try:
            qty = _parse_qty(m.group("qty"))
        except Exception:
            qty = None
    unit = _canon_unit(m.group("unit"))
    name = _clean(m.group("name") or raw)
    return qty, unit, name

def _ensure_pantry_norm(cur, row):
    """
    If pantry row lacks norm_qty/norm_unit, set minimal normalization:
    - if unit is mass/volume supported by pint -> normalize to g/ml
    - else keep as 'count'
    """
    if row.get("norm_qty") is not None and row.get("norm_unit"):
        return row

    qty = row.get("qty")
    unit = (row.get("unit") or "").lower() if row.get("unit") else None
    norm_qty, norm_unit = None, None

    if qty is not None and unit:
        try:
            q = Q_(qty, unit)
            if q.check(ureg.mass):
                norm_qty = float(q.to("g").magnitude)
                norm_unit = "g"
            elif q.check(ureg.volume):
                norm_qty = float(q.to("ml").magnitude)
                norm_unit = "ml"
        except Exception:
            pass

    if norm_qty is None:
        # fallback to count if we can't normalize
        norm_qty = float(qty) if qty is not None else None
        norm_unit = unit or "count"

    cur.execute(
        """UPDATE pantry_items
           SET canonical_name=%s,
               norm_qty=%s,
               norm_unit=%s,
               norm_conf=%s,
               norm_source='rule'
         WHERE id=%s AND user_id=%s""",
        (
            _clean(row.get("name") or ""),
            norm_qty,
            norm_unit,
            0.8,
            row["id"],
            row["user_id"],
        ),
    )
    cur.connection.commit()

    row["canonical_name"] = _clean(row.get("name") or "")
    row["norm_qty"] = norm_qty
    row["norm_unit"] = norm_unit
    row["norm_conf"] = 0.8
    row["norm_source"] = "rule"
    return row

def _substr_or_fuzzy_best(ingredient_name: str, pantry_names: List[str]) -> Tuple[int, float]:
    """
    Substring first, then RapidFuzz. Returns (index, confidence 0..1) or (-1,0).
    """
    ing = ingredient_name.strip().lower()
    best_i, best_sc = -1, 0.0
    for i, p in enumerate(pantry_names):
        p2 = (p or "").strip().lower()
        if not p2:
            continue
        if ing in p2 or p2 in ing:
            return i, 0.95
        f = max(fuzz.token_set_ratio(ing, p2), fuzz.partial_ratio(ing, p2)) / 100.0
        if f > best_sc:
            best_sc, best_i = f, i
    return (best_i, best_sc) if best_sc >= 0.78 else (-1, 0.0)

def _convert_with_pint(qty: float, from_unit: str, to_unit: str) -> Optional[float]:
    """
    Plain pint conversion for same-kind units (mass↔mass or volume↔volume).
    Use only as a last resort when contextual conversion can't help.
    """
    if not from_unit or not to_unit:
        return None
    if from_unit == to_unit:
        return float(qty)
    try:
        q = Q_(qty, from_unit)
        # only mass↔mass or volume↔volume directly; no cross without density
        if (q.check(ureg.mass) and Q_(1, to_unit).check(ureg.mass)) or \
           (q.check(ureg.volume) and Q_(1, to_unit).check(ureg.volume)):
            return float(q.to(to_unit).magnitude)
    except Exception:
        return None
    return None

# ---------- response models ----------
class DeductOut(BaseModel):
    ok: bool
    plan_id: int
    deducted: List[Dict[str, Any]]
    shortages: List[Dict[str, Any]]

# ---------- endpoints ----------

@router.post("/api/mealplan/{plan_id}/cook", response_model=DeductOut)
@router.post("/api/mealplan/{plan_id}/deduct", response_model=DeductOut)  # alias
def cook_plan(plan_id: int, user=Depends(bearer_user)):
    """
    Deduct pantry quantities for the ingredients of a meal plan item.
    - Parse each ingredient line (qty/unit/name).
    - Substring/fuzzy match to a pantry item (by canonical/name).
    - Convert units using convert_with_context (DB-backed density/per-count); fall back to pint.
    - Update pantry_items.norm_qty.
    """
    uid = int(user["sub"])

    with get_conn() as conn, conn.cursor() as cur:
        # Load plan
        cur.execute(
            """SELECT id, user_id, recipe_id, title, ingredients, directions, servings
               FROM meal_plan WHERE id=%s AND user_id=%s LIMIT 1""",
            (plan_id, uid),
        )
        plan = cur.fetchone()
        if not plan:
            raise HTTPException(status_code=404, detail="Meal plan not found")

        servings_mult = float(plan.get("servings") or 1.0)
        ing_lines = _to_list_jsonish(plan.get("ingredients"))

        # Load pantry
        cur.execute(
            """SELECT id, user_id, name, qty, unit,
                     canonical_name, norm_qty, norm_unit, norm_conf
               FROM pantry_items
               WHERE user_id=%s
               ORDER BY id ASC""",
            (uid,),
        )
        pantry_rows = cur.fetchall() or []
        for pr in pantry_rows:
            _ensure_pantry_norm(cur, pr)

        pantry_names = [
            (r.get("canonical_name") or r.get("name") or "").strip().lower()
            for r in pantry_rows
        ]

        deducted: List[Dict[str, Any]] = []
        shortages: List[Dict[str, Any]] = []

        for raw in ing_lines:
            qty, unit, name = parse_ingredient_line(raw)
            if qty is None or unit is None:
                shortages.append({"ingredient": raw, "reason": "no parsable qty/unit"})
                continue

            need_qty = float(qty) * servings_mult
            need_unit = unit

            # best pantry match
            idx, conf = _substr_or_fuzzy_best(name, pantry_names)
            if idx < 0:
                shortages.append({"ingredient": raw, "reason": "no matching pantry item"})
                continue

            prow = pantry_rows[idx]
            p_id = int(prow["id"])
            p_name = (prow.get("canonical_name") or prow.get("name") or "").strip()
            p_qty = prow.get("norm_qty")
            p_unit = (prow.get("norm_unit") or "").strip().lower()

            if p_qty is None or not p_unit:
                shortages.append({"ingredient": raw, "reason": f"pantry item '{p_name}' not normalized"})
                continue

            # === NEW: context-aware conversion (DB densities / per-count facts) ===
            need_in_punit = convert_with_context(
                name=name,           # cleaned ingredient name
                qty=need_qty,
                unit_from=need_unit,
                unit_to=p_unit,
                cur=cur,            # pass cursor so converter can read facts/densities
            )

            # Fallbacks:
            if need_in_punit is None:
                # last resort: same-kind pint conversion
                need_in_punit = _convert_with_pint(need_qty, need_unit, p_unit)

            if need_in_punit is None:
                # absolute last resort: if strings equal, treat as same
                if (need_unit or "").lower() == p_unit:
                    need_in_punit = need_qty
                else:
                    shortages.append({
                        "ingredient": raw,
                        "reason": f"cannot convert {need_qty} {need_unit} -> {p_unit}"
                    })
                    continue

            need_in_punit = float(need_in_punit)
            have = float(p_qty)

            if have >= need_in_punit:
                new_qty = have - need_in_punit
                cur.execute(
                    "UPDATE pantry_items SET norm_qty=%s WHERE id=%s AND user_id=%s",
                    (new_qty, p_id, uid),
                )
                deducted.append({
                    "ingredient": raw,
                    "matched_pantry": p_name,
                    "used": f"{round(need_in_punit, 2)} {p_unit}",
                    "remaining": f"{round(new_qty, 2)} {p_unit}",
                    "match_conf": round(conf, 2),
                })
            else:
                shortages.append({
                    "ingredient": raw,
                    "matched_pantry": p_name,
                    "reason": f"need {round(need_in_punit,2)} {p_unit}, have {round(have,2)} {p_unit}",
                    "match_conf": round(conf, 2),
                })

        conn.commit()

    return DeductOut(ok=True, plan_id=plan_id, deducted=deducted, shortages=shortages)
