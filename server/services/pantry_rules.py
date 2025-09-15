from dataclasses import dataclass
from pint import UnitRegistry
import re, json
from typing import Optional, Tuple
from db import get_conn

ureg = UnitRegistry()
Q_ = ureg.Quantity

LOCAL_SIZE_EQ = {
    "stick_butter": ("g", 113.0),
    "clove_garlic": ("count", 1.0),
    "egg": ("count", 1.0),
    "can_14oz": ("g", 397.0),
    "can_28oz": ("g", 794.0),
    "pinch_salt": ("g", 0.36),
    "dash_salt": ("g", 0.60),
}
COUNT_SYNONYMS = {"pc","pcs","piece","pieces","count","ct","each","ea"}

@dataclass
class NormResult:
    canonical_name: str
    norm_qty: float | None
    norm_unit: str | None
    norm_conf: float
    norm_source: str

_TOKEN_RE = re.compile(r"[^a-z0-9\s\-]")
def _canon(s: str) -> str:
    s = (s or "").lower()
    s = _TOKEN_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()

def _parse_qty(q: str) -> float:
    q = q.strip()
    if " " in q and "/" in q:
        a, b = q.split(" ", 1); num, den = b.split("/", 1)
        return float(a) + float(num)/float(den)
    if "/" in q:
        num, den = q.split("/", 1)
        return float(num)/float(den)
    return float(q)

UNIT_RX = r"(teaspoons?|tsp|tablespoons?|tbsp|cups?|c|mls?|ml|liters?|l|pints?|quarts?|gallons?|ounces?|oz|pounds?|lbs?|grams?|g|kilograms?|kg|stick|sticks|piece|pieces|pc|pcs|count|can|cans|clove|cloves)"
PANTRY_LINE_RE = re.compile(
    rf"^\s*(?P<qty>\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)?\s*(?P<unit>{UNIT_RX})?\s*(?P<name>.+?)\s*$",
    re.IGNORECASE,
)

def parse_line(raw: str) -> tuple[float | None, str | None, str]:
    m = PANTRY_LINE_RE.match(raw or "")
    if not m:
        return None, None, raw or ""
    qty = None
    if m.group("qty"):
        try: qty = _parse_qty(m.group("qty"))
        except Exception: qty = None
    unit = m.group("unit").lower() if m.group("unit") else None
    name = (m.group("name") or raw).strip()
    return qty, unit, name

def _db_density(conn, key: str) -> float | None:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT grams_per_ml FROM food_density WHERE food_norm=%s", (key,))
            r = cur.fetchone()
            if r and r.get("grams_per_ml") is not None:
                return float(r["grams_per_ml"])
    except Exception: pass
    return None

def _db_size_equiv(conn, key: str) -> tuple[str, float] | None:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT target_unit, approx_value FROM size_equivalent WHERE keyword=%s LIMIT 1",
                (key,),
            )
            r = cur.fetchone()
            if r: return (str(r["target_unit"]), float(r["approx_value"]))
    except Exception: pass
    return None

def _maybe_size_equiv(canon: str, unit: str | None, qty: float, conn) -> tuple[float | None, str | None, float]:
    if "butter" in canon and unit in ("stick","sticks"):
        u,v = _db_size_equiv(conn,"stick_butter") or LOCAL_SIZE_EQ["stick_butter"]; return qty*v, u, 0.9
    if "garlic" in canon and ("clove" in canon or "cloves" in canon or unit=="clove"):
        u,v = _db_size_equiv(conn,"clove_garlic") or LOCAL_SIZE_EQ["clove_garlic"]; return qty*v, u, 0.8
    if "egg" in canon and (unit in (None,"", "count")):
        u,v = _db_size_equiv(conn,"egg") or LOCAL_SIZE_EQ["egg"]; return qty*v, u, 0.9
    if unit in ("can","cans"):
        if "14" in canon and "oz" in canon:
            u,v = _db_size_equiv(conn,"can_14oz") or LOCAL_SIZE_EQ["can_14oz"]; return qty*v, u, 0.7
        if "28" in canon and "oz" in canon:
            u,v = _db_size_equiv(conn,"can_28oz") or LOCAL_SIZE_EQ["can_28oz"]; return qty*v, u, 0.7
        return qty, "count", 0.6
    if "salt" in canon and ("pinch" in canon or "dash" in canon):
        key = "pinch_salt" if "pinch" in canon else "dash_salt"
        u,v = LOCAL_SIZE_EQ[key]; return qty*v, u, 0.6
    return None, None, 0.0

def normalize_rules(name: str, qty: float | None, unit: str | None, conn) -> NormResult:
    canon = _canon(name)
    if qty is not None:
        val,u,conf = _maybe_size_equiv(canon, unit, float(qty), conn)
        if u: return NormResult(canon, float(val), u, conf, "rule")

    # pure count
    if qty is not None and (unit in COUNT_SYNONYMS or unit in (None,"")):
        return NormResult(canon, float(qty), "count", 0.9, "rule")

    # mass → g
    if qty is not None and unit:
        try:
            q = Q_(qty, unit)
            if q.check(ureg.mass):  return NormResult(canon, float(q.to("g").magnitude), "g", 0.95, "rule")
            if q.check(ureg.volume):
                dens = _db_density(conn, canon)
                if dens:  # g/ml
                    ml = float(q.to("ml").magnitude)
                    return NormResult(canon, ml*dens, "g", 0.9, "rule")
                return NormResult(canon, float(q.to("ml").magnitude), "ml", 0.7, "rule")
        except Exception: pass

    return NormResult(canon, None, None, 0.5, "rule")
