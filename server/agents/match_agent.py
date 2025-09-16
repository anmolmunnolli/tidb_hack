# routes/mealplan_cook_routes.py
from __future__ import annotations

import json, re
from typing import List, Tuple, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import bearer_user                  # JWT dependency (must exist)
from db import get_conn                      # DB connector (DictCursor)
from rapidfuzz import fuzz
from pint import UnitRegistry

router = APIRouter()

ureg = UnitRegistry()
Q_ = ureg.Quantity

# =============== helpers ===============

def _to_list_jsonish(val) -> List[str]:
    """Tolerant list parser for ingredients/directions stored as JSON or text."""
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

def _parse_qty(q: str) -> float:
    """Parse numbers like '1 1/2', '3/4', '2.5'."""
    q = q.strip()
    if " " in q and "/" in q:  # "1 1/2"
        a, b = q.split(" ", 1)
        num, den = b.split("/", 1)
        return float(a) + float(num) / float(den)
    if "/" in q:
        num, den = q.split("/", 1)
        return float(num) / float(den)
    return float(q)

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
    if not u:
        return None
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
    - mass→g, volume→ml using pint; otherwise keep as 'count'
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
    """Mass↔mass or volume↔volume conversion (no cross without density)."""
    if not from_unit or not to_unit:
        return None
    if from_unit == to_unit:
        return float(qty)
    try:
        q = Q_(qty, from_unit)
        # only allow same-dimension conversions
        if (q.check(ureg.mass) and Q_(1, to_unit).check(ureg.mass)) or \
           (q.check(ureg.volume) and Q_(1, to_unit).check(ureg.volume)):
            return float(q.to(to_unit).magnitude)
    except Exception:
        return None
    return None

# =============== response model ===============

class DeductOut(BaseModel):
    ok: bool
    plan_id: int
    deducted: List[Dict[str, Any]]
    shortages: List[Dict[str, Any]]

# =============== endpoints ===============

@router.post("/api/mealplan/{plan_id}/cook", response_model=DeductOut)
@router.post("/api/mealplan/{plan_id}/deduct", response_model=DeductOut)  # alias
def cook_plan(plan_id: int, user=Depends(bearer_user)):
    """
    Deduct pantry quantities for the ingredients of a meal plan item.
    Includes verbose DEBUG prints for troubleshooting.
    """
    uid = int(user["sub"])
    print(f"\n[DEBUG] === COOK PLAN plan_id={plan_id} user_id={uid} ===")

    with get_conn() as conn, conn.cursor() as cur:
        # --- Load plan
        cur.execute(
            """SELECT id, user_id, recipe_id, title, ingredients, directions, servings
               FROM meal_plan WHERE id=%s AND user_id=%s LIMIT 1""",
            (plan_id, uid),
        )
        plan = cur.fetchone()
        if not plan:
            print("[DEBUG] Meal plan not found.")
            raise HTTPException(status_code=404, detail="Meal plan not found")

        servings_mult = float(plan.get("servings") or 1.0)
        ing_lines = _to_list_jsonish(plan.get("ingredients"))
        print(f"[DEBUG] Title: {plan.get('title')}")
        print(f"[DEBUG] Servings multiplier: {servings_mult}")
        print(f"[DEBUG] Ingredient lines ({len(ing_lines)}): {ing_lines}")

        # --- Load pantry
        cur.execute(
            """SELECT id, user_id, name, qty, unit,
                     canonical_name, norm_qty, norm_unit, norm_conf
               FROM pantry_items
               WHERE user_id=%s
               ORDER BY id ASC""",
            (uid,),
        )
        pantry_rows = cur.fetchall() or []
        print(f"[DEBUG] Pantry rows before norm: {len(pantry_rows)}")

        for pr in pantry_rows:
            _ensure_pantry_norm(cur, pr)

        pantry_names = [(r.get("canonical_name") or r.get("name") or "").strip().lower() for r in pantry_rows]
        print(f"[DEBUG] Pantry names (normalized): {pantry_names}")

        deducted: List[Dict[str, Any]] = []
        shortages: List[Dict[str, Any]] = []

        # --- Deduction loop
        for raw in ing_lines:
            print(f"\n[DEBUG] --- Checking ingredient line: {raw}")
            qty, unit, name = parse_ingredient_line(raw)
            print(f"[DEBUG] Parsed → qty={qty}, unit={unit}, name='{name}'")

            if qty is None or unit is None:
                shortages.append({"ingredient": raw, "reason": "no parsable qty/unit"})
                print("[DEBUG] → Could not parse qty/unit, skipping.")
                continue

            need_qty = float(qty) * servings_mult
            need_unit = unit
            print(f"[DEBUG] Need {need_qty} {need_unit} for this recipe line.")

            # best pantry match
            idx, conf = _substr_or_fuzzy_best(name, pantry_names)
            print(f"[DEBUG] Match search → idx={idx}, conf={conf}")

            if idx < 0:
                shortages.append({"ingredient": raw, "reason": "no matching pantry item"})
                print("[DEBUG] → No pantry match found.")
                continue

            prow = pantry_rows[idx]
            p_id = int(prow["id"])
            p_name = (prow.get("canonical_name") or prow.get("name") or "").strip()
            p_qty  = prow.get("norm_qty")
            p_unit = prow.get("norm_unit")
            print(f"[DEBUG] Pantry match → id={p_id}, name='{p_name}', stock={p_qty} {p_unit}")

            if p_qty is None or not p_unit:
                shortages.append({"ingredient": raw, "reason": f"pantry item '{p_name}' not normalized"})
                print("[DEBUG] → Pantry item missing norm qty/unit.")
                continue

            # convert recipe need into pantry unit (mass↔mass or vol↔vol)
            need_in_punit = _convert_with_pint(need_qty, need_unit, p_unit)
            print(f"[DEBUG] Converted need {need_qty} {need_unit} → {need_in_punit} {p_unit}")

            if need_in_punit is None:
                # last resort: if string-equal units, treat as same
                if need_unit == p_unit:
                    need_in_punit = need_qty
                    print("[DEBUG] Units equal as strings; using raw qty.")
                else:
                    shortages.append({"ingredient": raw, "reason": f"unit mismatch ({need_unit}→{p_unit})"})
                    print("[DEBUG] → Unit mismatch, cannot convert.")
                    continue

            need_in_punit = float(need_in_punit)
            have = float(p_qty)

            if have >= need_in_punit:
                new_qty = have - need_in_punit
                print(f"[DEBUG] Deducting {need_in_punit} {p_unit} from pantry (had {have} {p_unit}; new {new_qty} {p_unit})")
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
                print(f"[DEBUG] Shortage → need {need_in_punit} {p_unit}, have {have} {p_unit}")
                shortages.append({
                    "ingredient": raw,
                    "matched_pantry": p_name,
                    "reason": f"need {round(need_in_punit,2)} {p_unit}, have {round(have,2)} {p_unit}",
                    "match_conf": round(conf, 2),
                })

        try:
            conn.commit()
            print(f"\n[DEBUG] Commit OK. Deducted={len(deducted)}, Shortages={len(shortages)}")
        except Exception as e:
            print(f"[DEBUG] Commit ERROR: {e}")
            raise

    return DeductOut(ok=True, plan_id=plan_id, deducted=deducted, shortages=shortages)
