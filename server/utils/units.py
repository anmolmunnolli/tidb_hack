# utils/units.py
from __future__ import annotations
from typing import Optional
import os, re
import numpy as np
from pint import UnitRegistry

try:
    from langchain_openai import ChatOpenAI
    _HAS_OPENAI = bool(os.getenv("OPENAI_API_KEY"))
except Exception:
    _HAS_OPENAI = False
    ChatOpenAI = None  # type: ignore

ureg = UnitRegistry()
Q_ = ureg.Quantity

COUNT_SYNS = {"count", "pc", "pcs", "piece", "pieces", "each", "ct", "ea"}

def _canon_unit(u: Optional[str]) -> str:
    if not u: return ""
    u = u.strip().lower()
    aliases = {
        "tsp":"teaspoon", "tsps":"teaspoon",
        "tbsp":"tablespoon", "tbsps":"tablespoon", "tbl":"tablespoon",
        "c":"cup", "cups":"cup",
        "oz":"ounce", "ozs":"ounce", "lb":"pound", "lbs":"pound",
        "gms":"gram", "kg":"kilogram", "kgs":"kilogram",
        "l":"liter", "lt":"liter", "mls":"milliliter",
        "pc":"count", "pcs":"count",
    }
    return aliases.get(u, u)

def _is_count(u: Optional[str]) -> bool:
    return (u or "").lower().strip() in COUNT_SYNS

# ---- DB helpers (optional but recommended) ----
def _get_density_g_per_ml(cur, food_norm: str) -> Optional[float]:
    """food_density(food_norm, grams_per_ml)"""
    try:
        cur.execute("SELECT grams_per_ml FROM food_density WHERE food_norm=%s", (food_norm,))
        row = cur.fetchone()
        if row and row.get("grams_per_ml") is not None:
            return float(row["grams_per_ml"])
    except Exception:
        pass
    return None

def _get_per_count(cur, food_norm: str) -> tuple[Optional[float], Optional[str]]:
    """
    pantry_norm_facts(food_norm, unit_kind, grams_per_count, ml_per_count).
    Returns (value, 'g'|'ml') if known, else (None, None)
    """
    try:
        cur.execute(
            "SELECT unit_kind, grams_per_count, ml_per_count FROM pantry_norm_facts WHERE food_norm=%s",
            (food_norm,),
        )
        row = cur.fetchone()
        if not row: return (None, None)
        if row["unit_kind"] == "mass" and row.get("grams_per_count"):
            return (float(row["grams_per_count"]), "g")
        if row["unit_kind"] == "volume" and row.get("ml_per_count"):
            return (float(row["ml_per_count"]), "ml")
    except Exception:
        pass
    return (None, None)

# ---- Optional LLM fallback (last resort) ----
_llm = None
def _get_llm():
    global _llm
    if _llm is None and _HAS_OPENAI:
        _llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    return _llm

def _llm_convert(name: str, qty: float, from_unit: str, to_unit: str) -> Optional[float]:
    llm = _get_llm()
    if not llm:
        return None
    prompt = (
        "Convert this cooking quantity using typical culinary assumptions/density for the specific ingredient. "
        "Return ONLY a number (no unit).\n\n"
        f"Ingredient: {name}\nValue: {qty}\nFrom: {from_unit}\nTo: {to_unit}\n\nNumber only:"
    )
    try:
        text = llm.invoke(prompt).content.strip()
        m = re.search(r"-?\d+(?:\.\d+)?", text)
        return float(m.group(0)) if m else None
    except Exception:
        return None

# ---- Public API ----
def convert_with_context(
    name: str,
    qty: float,
    unit_from: Optional[str],
    unit_to: Optional[str],
    cur=None,
) -> Optional[float]:
    """
    Convert qty from unit_from -> unit_to for a given ingredient name.
    Strategy:
      1) identical or trivial units → return qty
      2) count <-> mass/volume via per-count facts (DB)
      3) Pint for mass<->mass, volume<->volume
      4) mass<->volume via density table (g/ml)
      5) LLM fallback (optional)
    Returns float or None if cannot convert.
    """
    if qty is None:
        return None

    uf = _canon_unit(unit_from)
    ut = _canon_unit(unit_to)
    if not uf or not ut:
        return None
    if uf == ut:
        return float(qty)

    food_norm = (name or "").strip().lower()

    # ---- Count path (from count) ----
    if _is_count(uf) and ut in {"g", "gram", "grams", "ml", "milliliter", "milliliters"}:
        per, unit_kind = _get_per_count(cur, food_norm) if cur else (None, None)
        if per and unit_kind:
            if unit_kind == "g" and ut in {"g","gram","grams"}:
                return float(qty) * per
            if unit_kind == "ml" and ut in {"ml","milliliter","milliliters"}:
                return float(qty) * per
        # try LLM last
        out = _llm_convert(name, float(qty), uf, ut)
        if out is not None and np.isfinite(out):
            return float(out)
        return None

    # ---- Count path (to count) ----
    if _is_count(ut) and uf in {"g","gram","grams","ml","milliliter","milliliters"}:
        per, unit_kind = _get_per_count(cur, food_norm) if cur else (None, None)
        if per and unit_kind:
            if unit_kind == "g" and uf in {"g","gram","grams"} and per > 0:
                return float(qty) / per
            if unit_kind == "ml" and uf in {"ml","milliliter","milliliters"} and per > 0:
                return float(qty) / per
        out = _llm_convert(name, float(qty), uf, ut)
        if out is not None and np.isfinite(out):
            return float(out)
        return None

    # ---- Same kind via Pint (mass↔mass or volume↔volume) ----
    try:
        q = Q_(qty, uf)
        # mass<->mass
        if q.check(ureg.mass) and ut in {"g","gram","grams","kg","kilogram","kilograms","mg"}:
            return float(q.to("gram").magnitude if ut.startswith("g") else q.to(ut).magnitude)
        # volume<->volume
        if q.check(ureg.volume) and ut in {"ml","milliliter","milliliters","l","liter","liters","cup","tablespoon","teaspoon","pint","quart","gallon","ounce","fluid_ounce"}:
            return float(q.to(ut if ut != "ml" else "milliliter").magnitude)
    except Exception:
        pass

    # ---- Mass<->Volume via density (g/ml) ----
    dens = _get_density_g_per_ml(cur, food_norm) if cur else None
    if dens and dens > 0:
        try:
            q = Q_(qty, uf)
            if q.check(ureg.volume) and ut in {"g","gram","grams"}:
                ml = float(q.to("milliliter").magnitude)
                return ml * float(dens)           # ml * g/ml -> g
            if q.check(ureg.mass) and ut in {"ml","milliliter","milliliters"}:
                g = float(q.to("gram").magnitude)
                return g / float(dens)            # g / (g/ml) -> ml
        except Exception:
            pass

    # ---- LLM fallback (last resort) ----
    out = _llm_convert(name, float(qty), uf, ut)
    if out is not None and np.isfinite(out):
        return float(out)
    return None
