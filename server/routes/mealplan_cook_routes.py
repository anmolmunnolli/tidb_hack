from __future__ import annotations

import json, re
from typing import List, Tuple, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from rapidfuzz import fuzz
from pint import UnitRegistry
from pydantic import BaseModel
from typing import List, Dict, Any
from auth import bearer_user
from db import get_conn
from agents.llm import get_chat

router = APIRouter()

ureg = UnitRegistry()
Q_ = ureg.Quantity

# --- LLM wrapper used by convert_with_context -------------------------------
# If you already have a get_chat() somewhere else, import it; otherwise stub.
try:
    from agents.llm import get_chat  # or wherever your chat helper lives
except Exception:
    get_chat = None

def llm_call(prompt: str) -> str:
    """
    Minimal callable for convert_with_context(model_call=...).
    Must return a string. If no LLM configured, return a safe JSON fallback.
    """
    if get_chat is None:
        # tell converter "no idea" so it falls back cleanly
        return '{"factor": 0, "confidence": 0}'
    chat = get_chat()
    resp = chat.invoke(prompt)
    # LangChain messages usually have .content
    return getattr(resp, "content", str(resp))

# =========================
# Utilities / Parsing
# =========================

def _to_list_jsonish(val) -> List[str]:
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
    q = q.strip()
    if " " in q and "/" in q:
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



# --- contextful conversion helpers (LLM + pint) -----------------------------

def _units_equal(a: Optional[str], b: Optional[str]) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower()

def _ask_llm_density_for_name(
    model_call, *, name: str, from_unit: str, to_unit: str
) -> Optional[float]:
    """
    Ask the LLM for an approximate conversion factor for this ingredient name,
    returning the numeric factor so: qty * factor converts from_unit -> to_unit.
    """
    prompt = (
        "You are a cooking assistant. Estimate a reasonable conversion factor for an ingredient.\n"
        f"Ingredient: {name}\n"
        f"Convert: 1 {from_unit} -> ? {to_unit}\n"
        "Return ONLY JSON like: {\"factor\": number, \"confidence\": 0..100}. "
        "Use typical home cooking approximations; if unknown, set confidence=0."
    )
    try:
        txt = model_call(prompt)
        m = re.search(r"\{.*\}", txt, flags=re.S)
        if not m:
            return None
        obj = json.loads(m.group(0))
        fac = float(obj.get("factor", 0) or 0)
        conf = float(obj.get("confidence", 0) or 0)
        if fac > 0 and conf >= 40:  # be conservative
            print(f"[cxt] LLM factor 1 {from_unit} -> {fac} {to_unit} for '{name}' (conf={conf:.0f})")
            return fac
    except Exception as e:
        print("[cxt] LLM density error:", e)
    return None

def convert_with_context(
    *,
    name: str,
    qty: float,
    unit_from: Optional[str],
    unit_to: Optional[str],
    model_call=None,   # callable(prompt)->str, pass your LLM wrapper
) -> Optional[float]:
    """
    Attempts:
      0) identical units → return qty (fixes cinnamon case)
      1) pint mass↔mass or volume↔volume
      2) LLM one-hop mass↔volume (density) when same name, e.g. 'oil' cup→g
      3) Two-hop cup↔count or tsp↔count via LLM:
         - from → grams (LLM or pint if from is mass)
         - grams per COUNT (LLM), then divide
    """
    uf = (unit_from or "").lower().strip() or None
    ut = (unit_to or "").lower().strip() or None
    nm = (name or "").strip().lower()

    # (0) identical units
    if _units_equal(uf, ut):
        print(f"[cxt] SAME-UNIT {qty} {uf} -> {qty} {ut} ('{nm}')")
        return float(qty)

    # (1) Try pint same-dimension
    if uf and ut:
        try:
            q = Q_(qty, uf)
            if q.check(ureg.mass) and Q_(1, ut).check(ureg.mass):
                out = float(q.to(ut).magnitude)
                print(f"[cxt] pint {qty} {uf} -> {out} {ut}")
                return out
            if q.check(ureg.volume) and Q_(1, ut).check(ureg.volume):
                out = float(q.to(ut).magnitude)
                print(f"[cxt] pint {qty} {uf} -> {out} {ut}")
                return out
        except Exception as e:
            print(f"[cxt] pint fail {qty} {uf} -> {ut}: {e}")

    # Helper: to grams from arbitrary uf
    def to_grams(qty_val: float, src_unit: Optional[str]) -> Optional[float]:
        if not src_unit:
            return None
        try:
            q = Q_(qty_val, src_unit)
            if q.check(ureg.mass):
                return float(q.to("g").magnitude)
            if q.check(ureg.volume):
                # ask LLM density for name: 1 src_unit -> X g
                if callable(model_call):
                    fac = _ask_llm_density_for_name(model_call, name=nm, from_unit=src_unit, to_unit="g")
                    if fac:
                        return qty_val * fac
            # src is count → ask grams per count
            if src_unit == "count" and callable(model_call):
                fac = _ask_llm_density_for_name(model_call, name=nm, from_unit="count", to_unit="g")
                if fac:
                    return qty_val * fac
        except Exception as e:
            print(f"[cxt] to_grams fail {qty_val} {src_unit}: {e}")
        return None

    # Helper: grams to a target unit
    def grams_to_target(g_in: float, target_unit: str) -> Optional[float]:
        try:
            # mass target
            if Q_(1, target_unit).check(ureg.mass):
                return float(Q_(g_in, "g").to(target_unit).magnitude)
            # volume target → ask LLM g -> target volume
            if Q_(1, target_unit).check(ureg.volume) and callable(model_call):
                fac = _ask_llm_density_for_name(model_call, name=nm, from_unit="g", to_unit=target_unit)
                if fac:
                    # fac = target_unit per 1 g, or 1 g -> ? target_unit
                    # our prompt defined "1 g -> ? target_unit"
                    return g_in * fac
            # count target → ask grams per count and divide
            if target_unit == "count" and callable(model_call):
                per_count_g = _ask_llm_density_for_name(model_call, name=nm, from_unit="count", to_unit="g")
                if per_count_g and per_count_g > 0:
                    return g_in / per_count_g
        except Exception as e:
            print(f"[cxt] grams_to_target fail {g_in} g -> {target_unit}: {e}")
        return None

    # (2) LLM one-hop: src volume ↔ mass
    if callable(model_call) and uf and ut:
        # ask direct factor: 1 uf -> ? ut
        fac = _ask_llm_density_for_name(model_call, name=nm, from_unit=uf, to_unit=ut)
        if fac:
            out = qty * fac
            print(f"[cxt] LLM DIRECT {qty} {uf} -> {out} {ut} ('{nm}')")
            return out

    # (3) two-hop via grams for cup↔count etc.
    g = to_grams(qty, uf)
    if g is not None and ut:
        out = grams_to_target(g, ut)
        if out is not None:
            print(f"[cxt] LLM TWO-HOP {qty} {uf} -> {g} g -> {out} {ut} ('{nm}')")
            return out

    print(f"[cxt] FAIL {qty} {uf} -> {ut} ('{nm}')")
    return None


def parse_ingredient_line(line: str) -> Tuple[Optional[float], Optional[str], str]:
    """
    Return (qty, unit, name_clean). If qty present but unit missing, default unit='count'.
    Expands dotted units (e.g., 'c.' -> 'cup').
    """
    raw = (line or "").strip().lower()
    raw = re.sub(r"\bc\.\b", "cup", raw)
    raw = re.sub(r"\btsp\.\b", "tsp", raw)
    raw = re.sub(r"\btbsp\.\b", "tbsp", raw)
    raw = re.sub(r"\boz\.\b", "oz", raw)
    raw = re.sub(r"\blb\.\b", "lb", raw)
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

    # NEW: if qty but no unit → treat as count
    if qty is not None and unit is None:
        unit = "count"

    return qty, unit, name

def _ensure_pantry_norm(cur, row):
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

# =========================
# Matching
# =========================

_WORDS = re.compile(r"[a-z0-9]+")
_JSON_RE = re.compile(r"\{[\s\S]*\}")

def _cheap_overlap(a: str, b: str) -> int:
    A = set(_WORDS.findall((a or "").lower()))
    B = set(_WORDS.findall((b or "").lower()))
    return len(A & B)

def _tokens(s: str) -> List[str]:
    return [t for t in _WORDS.findall((s or "").lower()) if t]

def _wb_contains(hay: str, ned: str) -> bool:
    h = f" {re.sub(r'[^a-z0-9 ]',' ', (hay or '').lower()).strip()} "
    n = re.sub(r'[^a-z0-9 ]',' ', (ned or '').lower()).strip()
    if not n: return False
    toks = [t for t in n.split() if t]
    return (all(re.search(rf"\b{re.escape(t)}\b", h) for t in toks)) or (n in h)

def _llm_pick_index(ing: str, options: list[str]) -> tuple[int, float]:
    """
    Ask the LLM to pick an index; be robust to prose and code fences.
    Returns (local_idx_in_options, confidence 0..1) or (-1, 0.0).
    """
    if not callable(llm_call):
        return (-1, 0.0)

    prompt = (
        "You are matching a recipe ingredient to a user's pantry item.\n"
        "Pick the single best match INDEX from the numbered list (0-based), or -1 if none fits.\n"
        "Return ONLY JSON like: {\"index\": int, \"confidence\": 0..1}\n\n"
        f"Ingredient: {ing}\n\n"
        "Pantry options:\n" + "\n".join(f"{i}: {n}" for i, n in enumerate(options)) + "\n\nJSON:"
    )
    raw = llm_call(prompt) or ""
    # --- debug print so we can see raw model output in logs
    print("[llm_pick] RAW:", repr(raw)[:400])

    s = str(raw).strip()

    # Strip common code fences
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?", "", s.strip(), flags=re.I)
        s = s.strip()
        if s.endswith("```"):
            s = s[:-3].strip()

    # Collect all candidate { ... } objects that mention "index"
    # (LLMs sometimes emit multiple JSON blobs or add messages around them)
    candidates = []
    for m in re.finditer(r"\{[^{}]*\}", s, flags=re.S):
        chunk = m.group(0)
        if "index" not in chunk:
            continue
        candidates.append(chunk)

    # If none found, try a looser grab of a larger block ending with }
    if not candidates:
        # Try to grab longest {...} block
        m = re.search(r"\{[\s\S]*\}", s)
        if m and "index" in m.group(0):
            candidates.append(m.group(0))

    # Try to parse candidates in order; normalize common issues first
    for chunk in candidates:
        cleaned = chunk.strip()

        # Replace single quotes with double quotes when it looks JSON-ish
        if cleaned.count('"') == 0 and cleaned.count("'") >= 2:
            cleaned = cleaned.replace("'", '"')

        # Remove trailing commas inside objects, e.g. {"a":1,}
        cleaned = re.sub(r",\s*}", "}", cleaned)

        try:
            obj = json.loads(cleaned)
            idx = int(obj.get("index", -1))
            conf = float(obj.get("confidence", 0.0))
            # clamp confidence
            if not (0.0 <= conf <= 1.0):
                conf = max(0.0, min(1.0, conf))
            # validate index
            if -1 <= idx < len(options):
                print(f"[llm_pick] OK index={idx} conf={conf}")
                return (idx, conf)
        except Exception as e:
            print("[llm_pick] parse fail:", e, "chunk=", cleaned[:200])

    print("[llm_pick] no valid JSON, defaulting to (-1, 0.0)")
    return (-1, 0.0)


def best_match_substring_first(
    ingredient: str,
    pantry_names: List[str],
    *,
    use_llm: bool = True,
    debug: Optional[dict] = None
) -> Tuple[int, float]:
    ing = (ingredient or "").lower().strip()
    ing_toks = _tokens(ing)
    single_token = len(ing_toks) == 1
    if debug is not None:
        debug.clear()
        debug.update({"ingredient": ing, "steps": []})

    if not pantry_names:
        if debug is not None: debug["steps"].append({"stage":"empty"})
        return (-1, 0.0)

    # 1) Strong: word boundary / substring
    for i, p in enumerate(pantry_names):
        p2 = (p or "").lower().strip()
        if not p2: 
            continue
        if _wb_contains(p2, ing) or _wb_contains(ing, p2):
            if debug is not None: debug["steps"].append({"stage":"wb", "pick":i, "conf":0.95, "hit":p2})
            return (i, 0.95)

    # 2) Fuzzy (require token overlap)
    best_i, best_sc = -1, 0.0
    for i, p in enumerate(pantry_names):
        p2 = (p or "").lower().strip()
        if not p2: continue
        sc = max(fuzz.token_set_ratio(ing, p2), fuzz.partial_ratio(ing, p2)) / 100.0
        if sc > best_sc:
            best_sc, best_i = sc, i
    if debug is not None: debug["steps"].append({"stage":"fuzzy", "best_i":best_i, "best_sc":best_sc})

    def _has_overlap(p_name: str) -> bool:
        ptoks = set(_tokens(p_name))
        return bool(set(ing_toks) & ptoks)

    # If fuzzy above threshold AND shares at least one token, accept.
    if best_sc >= 0.82 and best_i >= 0 and _has_overlap(pantry_names[best_i]):
        return (best_i, best_sc)

    # 3) LLM shortlist (still require minimal overlap unless exact)
    if use_llm:
        scored = sorted(
            [(i, _cheap_overlap(ing, p or ""), (p or "")) for i, p in enumerate(pantry_names)],
            key=lambda x: x[1], reverse=True
        )[: max(10, min(40, len(pantry_names)))]
        if scored:
            opts = [name for _,__,name in scored]
            local_idx, conf = _llm_pick_index(ing, opts)
            if 0 <= local_idx < len(opts):
                global_idx = [i for i,_,_ in scored][local_idx]
                p_name = pantry_names[global_idx]
                # For single-token ingredients, require that token appear in the chosen name
                if single_token and (ing_toks[0] not in _tokens(p_name)):
                    if debug is not None: debug["steps"].append({"stage":"llm_reject", "pick":global_idx, "conf":conf})
                    return (-1, 0.0)
                # Otherwise require at least some token overlap
                if not single_token and not _has_overlap(p_name):
                    if debug is not None: debug["steps"].append({"stage":"llm_reject_no_overlap", "pick":global_idx, "conf":conf})
                    return (-1, 0.0)
                if debug is not None: debug["steps"].append({"stage":"llm", "pick":global_idx, "conf":conf})
                return global_idx, conf

    if debug is not None: debug["steps"].append({"stage":"fallback", "pick":-1, "conf":0.0})
    return (-1, 0.0)

# =========================
# LLM-backed Conversion (with DB cache)
# =========================

def _food_norm(s: str) -> str:
    s = re.sub(r"[^a-z0-9\s]", " ", (s or "").lower())
    return re.sub(r"\s+", " ", s).strip()

def _db_get(cur, sql: str, args: tuple) -> Optional[dict]:
    try:
        cur.execute(sql, args)
        return cur.fetchone()
    except Exception:
        return None

def _db_exec(cur, sql: str, args: tuple):
    try:
        cur.execute(sql, args)
        cur.connection.commit()
    except Exception:
        pass

def _db_get_per_count_g(cur, food_norm: str) -> Optional[float]:
    r = _db_get(cur, """SELECT grams_per_count FROM pantry_norm_facts
                        WHERE food_norm=%s AND grams_per_count IS NOT NULL LIMIT 1""", (food_norm,))
    return float(r["grams_per_count"]) if r and r.get("grams_per_count") is not None else None

def _db_set_per_count_g(cur, food_norm: str, per_g: float, conf: float, model="llm"):
    _db_exec(cur, """INSERT INTO pantry_norm_facts (food_norm, unit_kind, grams_per_count, ml_per_count, model, confidence, source)
                     VALUES (%s,'mass',%s,NULL,%s,%s,'llm')
                     ON DUPLICATE KEY UPDATE grams_per_count=VALUES(grams_per_count),
                                             model=VALUES(model),
                                             confidence=VALUES(confidence),
                                             source=VALUES(source)""",
             (food_norm, per_g, model, float(conf)))

def _db_get_per_cup_g(cur, food_norm: str) -> Optional[float]:
    r = _db_get(cur, """SELECT grams_per_cup FROM food_volume_facts
                        WHERE food_norm=%s AND grams_per_cup IS NOT NULL LIMIT 1""", (food_norm,))
    return float(r["grams_per_cup"]) if r and r.get("grams_per_cup") is not None else None

def _db_set_per_cup_g(cur, food_norm: str, g_per_cup: float, conf: float, model="llm"):
    _db_exec(cur, """INSERT INTO food_volume_facts (food_norm, grams_per_cup, model, confidence, source)
                     VALUES (%s,%s,%s,%s,'llm')
                     ON DUPLICATE KEY UPDATE grams_per_cup=VALUES(grams_per_cup),
                                             model=VALUES(model),
                                             confidence=VALUES(confidence),
                                             source=VALUES(source)""",
             (food_norm, g_per_cup, model, float(conf)))

def _db_get_density_g_per_ml(cur, food_norm: str) -> Optional[float]:
    r = _db_get(cur, """SELECT grams_per_ml FROM food_density
                        WHERE food_norm=%s AND grams_per_ml IS NOT NULL LIMIT 1""", (food_norm,))
    return float(r["grams_per_ml"]) if r and r.get("grams_per_ml") is not None else None

def _db_set_density_g_per_ml(cur, food_norm: str, g_per_ml: float, conf: float, model="llm"):
    _db_exec(cur, """INSERT INTO food_density (food_norm, grams_per_ml, model, confidence, source)
                     VALUES (%s,%s,%s,%s,'llm')
                     ON DUPLICATE KEY UPDATE grams_per_ml=VALUES(grams_per_ml),
                                             model=VALUES(model),
                                             confidence=VALUES(confidence),
                                             source=VALUES(source)""",
             (food_norm, g_per_ml, model, float(conf)))

def _ask_llm_json(prompt: str) -> Optional[dict]:
    llm = get_chat()
    text = llm.invoke(prompt).content
    m = _JSON_RE.search(text or "")
    if not m:
        try:
            return json.loads(text)
        except Exception:
            return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None

def _llm_estimate_per_count_g(name: str) -> Tuple[Optional[float], float]:
    prompt = f"""
Estimate grams for ONE medium unit (per-count) of the ingredient below for home cooking.
Return ONLY JSON:
{{"grams_per_count": number|null, "confidence": number}}
Ingredient: "{name}"
"""
    obj = _ask_llm_json(prompt)
    if not obj:
        return None, 0.0
    g = obj.get("grams_per_count", None)
    conf = obj.get("confidence", 0.0)
    try:
        return (float(g) if g is not None else None, float(conf))
    except Exception:
        return None, 0.0

def _llm_estimate_per_cup_g(name: str) -> Tuple[Optional[float], float]:
    prompt = f"""
Estimate grams per ONE US cup for this ingredient (dry scoop for solids, packed for pastes).
Return ONLY JSON:
{{"grams_per_cup": number|null, "confidence": number}}
Ingredient: "{name}"
"""
    obj = _ask_llm_json(prompt)
    if not obj:
        return None, 0.0
    g = obj.get("grams_per_cup", None)
    conf = obj.get("confidence", 0.0)
    try:
        return (float(g) if g is not None else None, float(conf))
    except Exception:
        return None, 0.0

def _llm_estimate_density_g_per_ml(name: str) -> Tuple[Optional[float], float]:
    prompt = f"""
Estimate density (grams per milliliter) for the ingredient below (liquids/pastes only).
Return ONLY JSON:
{{"grams_per_ml": number|null, "confidence": number}}
Ingredient: "{name}"
"""
    obj = _ask_llm_json(prompt)
    if not obj:
        return None, 0.0
    g = obj.get("grams_per_ml", None)
    conf = obj.get("confidence", 0.0)
    try:
        return (float(g) if g is not None else None, float(conf))
    except Exception:
        return None, 0.0

def _is_volume_unit(u: str) -> bool:
    try:
        return Q_(1, u).check(ureg.volume)
    except Exception:
        return False

def _is_mass_unit(u: str) -> bool:
    try:
        return Q_(1, u).check(ureg.mass)
    except Exception:
        return False


# =========================
# API models
# =========================

from typing import Optional

class DeductOut(BaseModel):
    ok: bool
    plan_id: int
    deducted: List[Dict[str, Any]]
    shortages: List[Dict[str, Any]]
    requires_confirmation: bool
    pantry_updates: Optional[List[Dict[str, Any]]] = None           # when confirm=True
    pantry_preview_updates: Optional[List[Dict[str, Any]]] = None   # when confirm=False


# =========================
# Endpoint: Cook / Deduct
# =========================
class DeductOut(BaseModel):
    ok: bool
    plan_id: int
    deducted: List[Dict[str, Any]]
    shortages: List[Dict[str, Any]]
    requires_confirmation: bool  # NEW
@router.post("/api/mealplan/{plan_id}/cook", response_model=DeductOut)
@router.post("/api/mealplan/{plan_id}/deduct", response_model=DeductOut)
def cook_plan(
    plan_id: int,
    user=Depends(bearer_user),
    confirm: bool = Query(False, description="Set true to commit deductions; false returns preview only"),
):
    uid = int(user["sub"])

    with get_conn() as conn, conn.cursor() as cur:
        # 1) Load plan
        cur.execute(
            """SELECT id, user_id, recipe_id, title, ingredients, directions, servings
               FROM meal_plan WHERE id=%s AND user_id=%s LIMIT 1""",
            (plan_id, uid),
        )
        plan = cur.fetchone()
        if not plan:
            raise HTTPException(status_code=404, detail="Meal plan not found")

        print(f"\n=== COOK START plan_id={plan_id} user_id={uid} confirm={confirm} ===")
        title = (plan.get("title") or "").strip()
        servings_mult = float(plan.get("servings") or 1.0)
        ing_lines = _to_list_jsonish(plan.get("ingredients"))
        print(f"[cook] Title={title}   servings_mult={servings_mult}")
        print(f"[cook] Ingredients lines={ing_lines}")

        # 2) Load pantry & ensure norm
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
        pantry_names = [(r.get("canonical_name") or r.get("name") or "").strip().lower() for r in pantry_rows]
        print(f"[cook] Pantry items loaded={len(pantry_rows)}\n")

        deducted: List[Dict[str, Any]] = []
        shortages: List[Dict[str, Any]] = []

        # NEW: track changes / previews
        changed_ids: set[int] = set()
        preview_updates: List[Dict[str, Any]] = []

        # 3) Compute pass
        for raw in ing_lines:
            qty, unit, name = parse_ingredient_line(raw)
            print(f"[cook] Parse line='{raw}' -> qty={qty} unit={unit} name='{name}'")

            if qty is None or unit is None:
                print(f"[cook] !! No quantity/unit parsed; skipping\n")
                shortages.append({"ingredient": raw, "reason": "no parsable qty/unit"})
                continue

            need_qty  = float(qty) * servings_mult
            need_unit = unit

            dbg = {}
            idx, conf = best_match_substring_first(name, pantry_names, use_llm=True, debug=dbg)
            print(f"[cook] Match result idx={idx} conf={conf}")
            if dbg.get("steps"):
                print(f"[cook] Match trace: {json.dumps(dbg, indent=2)}")

            if idx < 0:
                print(f"[cook] !! No pantry match for {name}\n")
                shortages.append({"ingredient": raw, "reason": "no matching pantry item"})
                continue

            prow  = pantry_rows[idx]
            p_id  = int(prow["id"])
            p_name = (prow.get("canonical_name") or prow.get("name") or "").strip()
            p_qty  = prow.get("norm_qty")
            p_unit = prow.get("norm_unit")

            if p_qty is None or not p_unit:
                print(f"[cook] !! Pantry item '{p_name}' not normalized\n")
                shortages.append({"ingredient": raw, "reason": f"pantry item '{p_name}' not normalized"})
                continue

            print(f"[cook] Pantry match id={p_id} name='{p_name}' stock={p_qty:.3f} {p_unit}")
            need_in_punit = convert_with_context(
                name=name,
                qty=need_qty,
                unit_from=need_unit,
                unit_to=p_unit,
                model_call=llm_call,
            )
            print(f"[cook] Conversion: {need_qty} {need_unit} -> {need_in_punit} {p_unit}")

            if need_in_punit is None:
                if _units_equal(need_unit, p_unit):
                    need_in_punit = float(need_qty)
                    print(f"[cook] Fallback SAME UNIT -> {need_in_punit} {p_unit}")
                else:
                    shortages.append({"ingredient": raw, "reason": f"unit mismatch ({need_unit}→{p_unit})"})
                    continue

            have = float(p_qty)
            if have >= need_in_punit:
                new_qty = have - need_in_punit

                if confirm:
                    # write & track
                    cur.execute(
                        "UPDATE pantry_items SET norm_qty=%s WHERE id=%s AND user_id=%s",
                        (new_qty, p_id, uid),
                    )
                    changed_ids.add(p_id)
                else:
                    # preview only
                    preview_updates.append({
                        "id": p_id,
                        "canonical_name": p_name,
                        "norm_unit": p_unit,
                        "norm_qty_current": round(have, 4),
                        "norm_qty_after": round(new_qty, 4),
                    })

                deducted.append({
                    "ingredient": raw,
                    "matched_pantry": p_name,
                    "used": f"{round(need_in_punit, 2)} {p_unit}",
                    "remaining": f"{round(new_qty, 2)} {p_unit}",
                    "match_conf": round(conf, 2),
                })
                print(f"[cook] {'✓ Deduct' if confirm else '→ WOULD deduct'} {need_in_punit:.3f} {p_unit} from '{p_name}'. New stock={new_qty:.3f} {p_unit}\n")
            else:
                shortages.append({
                    "ingredient": raw,
                    "matched_pantry": p_name,
                    "reason": f"need {round(need_in_punit,2)} {p_unit}, have {round(have,2)} {p_unit}",
                    "match_conf": round(conf, 2),
                })
                print(f"[cook] !! Shortage need={need_in_punit:.3f} have={have:.3f} {p_unit}\n")

        # 4) Commit & reselect changed rows on confirm
        pantry_updates: List[Dict[str, Any]] = []
        if confirm:
            conn.commit()
            if changed_ids:
                placeholders = ",".join(["%s"] * len(changed_ids))
                params = (uid, *list(changed_ids))
                cur.execute(
                    f"""
                    SELECT id, name, canonical_name, qty, unit,
                           norm_qty, norm_unit, norm_conf,
                           DATE_FORMAT(expires_on,'%%Y-%%m-%%d') AS expires_on,
                           DATE_FORMAT(added_at,'%%Y-%%m-%%d %%H:%%i:%%s') AS added_at
                    FROM pantry_items
                    WHERE user_id=%s AND id IN ({placeholders})
                    """,
                    params,
                )
                pantry_updates = cur.fetchall() or []

        requires_confirmation = len(shortages) > 0

        print(f"=== COOK {'COMMITTED' if confirm else 'PREVIEW'} plan_id={plan_id} ===")
        print(f"[cook] Deducted={deducted}")
        print(f"[cook] Shortages={shortages}\n")

        return DeductOut(
            ok=True,
            plan_id=plan_id,
            deducted=deducted,
            shortages=shortages,
            requires_confirmation=requires_confirmation,
            pantry_updates=pantry_updates or None,
            pantry_preview_updates=preview_updates or None,
        )
