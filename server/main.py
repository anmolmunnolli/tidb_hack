import os, time, bcrypt, jwt, pymysql
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from dotenv import load_dotenv
from pydantic import BaseModel, condecimal
from typing import Optional, List, Literal
from fastapi import Request
import jwt
from typing import TypedDict
from transformers import pipeline


from typing import Optional
from fastapi import Header, HTTPException
from jwt import ExpiredSignatureError, InvalidTokenError
import re, json
from typing import List, Dict, Any, Tuple, Set
import numpy as np
from pint import UnitRegistry
import requests, json, re, math
from sentence_transformers import SentenceTransformer
import pymysql
from typing import Literal
import numpy as np
from sentence_transformers import SentenceTransformer
import ssl as _ssl
from pydantic import BaseModel
from typing import Any, Dict
import re, json
from dataclasses import dataclass
from pint import UnitRegistry

import requests, re, json, os
from rapidfuzz import fuzz, process
import logging, traceback
logger = logging.getLogger("cook")
logging.basicConfig(level=logging.INFO)


# Expandable stop/adjective lists
_PREP_WORDS = {
    "chopped","diced","sliced","minced","crushed","ground","grated","shredded",
    "peeled","seeded","seedless","fresh","large","small","medium","ripe","heaping",
    "packed","optional","to","taste"
}
_PARENS_RE = re.compile(r"\([^)]*\)|\[[^\]]*\]")  # remove (notes) or [notes]

def _canon_text(s: str) -> str:
    s = (s or "").lower()
    s = _PARENS_RE.sub(" ", s)
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _strip_prep_words(s: str) -> str:
    toks = [t for t in _canon_text(s).split() if t not in _PREP_WORDS]
    return " ".join(toks)

def canonical_head(s: str) -> str:
    """
    Heuristic 'head noun' extractor: keep last 1-3 tokens that aren’t prep words.
    E.g., '1 c. sliced seedless grapes' -> 'grapes'
          'unsalted butter, softened'   -> 'butter'
    """
    toks = _strip_prep_words(s).split()
    if not toks: return ""
    # keep the tail; often the ingredient noun is last
    tail = toks[-3:]
    return " ".join(tail)

def load_alias_map(cur) -> dict[str, str]:
    cur.execute("SELECT alias, canonical FROM ingredient_aliases")
    out = {}
    for r in cur.fetchall() or []:
        out[_canon_text(r["alias"])] = _canon_text(r["canonical"])
    return out

def alias_canonicalize(name: str, alias_map: dict[str,str]) -> str:
    raw = _canon_text(name)
    if raw in alias_map:
        return alias_map[raw]
    # also map the head
    head = canonical_head(name)
    if head and head in alias_map:
        return alias_map[head]
    return raw

# Optional: cache pantry embeddings (short strings → vector) for embedding fallback
_embed_cache: dict[str, np.ndarray] = {}

def embed_text_short(model: SentenceTransformer, text: str) -> np.ndarray:
    key = f"{model._first_module().__class__.__name__}:{text}"
    if key in _embed_cache:
        return _embed_cache[key]
    v = model.encode([text], normalize_embeddings=True, convert_to_numpy=True)[0]
    _embed_cache[key] = v
    return v

def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))  # already normalized


def match_recipe_to_pantry(recipe_name: str, pantry_rows: list[dict], cur, model: SentenceTransformer | None = None):
    """
    pantry_rows need: {id, name, canonical_name}
    Returns: (idx, score, method, r_can, p_can) or (-1, 0.0, None, r_can, "")
    """
    alias_map = load_alias_map(cur)

    r_can = alias_canonicalize(recipe_name, alias_map)
    r_head = canonical_head(recipe_name) or r_can

    best = (-1, 0.0, None, r_can, "")
    for i, p in enumerate(pantry_rows):
        p_name = p.get("canonical_name") or p.get("name") or ""
        p_can  = alias_canonicalize(p_name, alias_map)

        # 1) exact/contain
        if r_can == p_can or r_can in p_can or p_can in r_can:
            sc = 1.0
            if sc > best[1]:
                best = (i, sc, "exact", r_can, p_can)
            continue

        # 2) fuzzy token ratios (token_set_ratio is forgiving on order/extras)
        f1 = fuzz.token_set_ratio(r_can, p_can) / 100.0
        f2 = fuzz.partial_ratio(r_can, p_can) / 100.0
        sc_fuzzy = max(f1, f2)
        if sc_fuzzy > best[1]:
            best = (i, sc_fuzzy, "fuzzy", r_can, p_can)

        # 3) head-token fuzzy to catch 'seedless red grapes' vs 'grapes'
        if r_head and r_head != r_can:
            f3 = fuzz.token_set_ratio(r_head, p_can) / 100.0
            if f3 > best[1]:
                best = (i, f3, "head-fuzzy", r_can, p_can)

        # 4) optional embedding fallback (only if provided & fuzzy not decisive)
        # Use a modest threshold to avoid bad matches (tune as you observe)
        if model and best[1] < 0.82:
            v1 = embed_text_short(model, r_head)
            v2 = embed_text_short(model, p_can)
            sc_emb = cosine_sim(v1, v2)  # 0..1
            if sc_emb > best[1]:
                best = (i, sc_emb, "embed", r_can, p_can)

    # final acceptance threshold: tune with logs
    THRESH = 0.78  # 78% fuzzy or ~0.78 cosine
    return best if best[1] >= THRESH else (-1, 0.0, None, r_can, "")


# ---------- Hugging Face LLM (replaces Ollama) ----------
HF_MODEL_ID = os.getenv("HF_MODEL_ID", "google/flan-t5-base")  # or "google/flan-t5-large"
_HF_GEN = None

def get_hf():
    global _HF_GEN
    if _HF_GEN is None:
        # text2text-generation works well for “return JSON / number only” prompts
        _HF_GEN = pipeline(
            task="text2text-generation",
            model=HF_MODEL_ID,
            device_map="auto",
        )
    return _HF_GEN

def _hf_generate(prompt: str, max_new_tokens: int = 128) -> str:
    gen = get_hf()
    out = gen(
        prompt,
        max_new_tokens=max_new_tokens,
        # low temperature-style behavior (for t5, use num_beams to make it more deterministic)
        num_beams=4,
    )
    # pipeline returns list of dicts with 'generated_text'
    return (out[0].get("generated_text") or "").strip()


UNIT_ALIASES = {
    "tsp": "teaspoon", "tsps": "teaspoon",
    "tbsp": "tablespoon", "tbsps": "tablespoon",
    "tbl": "tablespoon",
    "c": "cup", "cups": "cup",
    "ozs": "ounce", "lbs": "pound", "gms": "gram", "kgs": "kilogram",
    "lt": "liter", "l": "liter", "mls": "milliliter",
    "pcs": "count", "pc": "count", "piece": "count", "pieces": "count",
    "stick": "stick", "sticks": "stick",  # we’ll map 'stick butter' via size_equivalent
}

def log(*a): 
    print("[cook]", *a)


# local fallback package/size (used if DB table has no match)
LOCAL_SIZE_EQ = {
    "stick_butter": ("g", 113.0),
    "clove_garlic": ("count", 1.0),
    "egg": ("count", 1.0),
    "pinch_salt": ("g", 0.36),
    "dash_salt": ("g", 0.60),
    "can_14oz": ("g", 397.0),
    "can_28oz": ("g", 794.0),
}


CANONICAL_BASE = {"g", "ml", "count"}

_frac = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"   # matches 1 1/2, 1/2, 2, 2.5
UNIT_RX = r"(teaspoons?|tsp|tablespoons?|tbsp|cups?|c|mls?|ml|liters?|l|pints?|quarts?|gallons?|ounces?|oz|pounds?|lbs?|grams?|g|kilograms?|kg|stick|sticks|piece|pieces|pc|pcs|count|can|cans)"

# basic parser: "2 cups milk", "1 can tomatoes", "3 sticks butter"
PANTRY_LINE_RE = re.compile(
    rf"^\s*(?P<qty>{_frac})?\s*(?P<unit>{UNIT_RX})?\s*(?P<name>.+?)\s*$",
    re.IGNORECASE,
)


COUNT_SYNONYMS = {"pc","pcs","piece","pieces","count","ct","each","ea"}
MASS_CANON = "g"
VOL_CANON  = "ml"

# reuse your _norm_token
def _norm_food(s: str) -> str:
    return _norm_token(s)

def _looks_like_count(unit: str | None) -> bool:
    if not unit: return False
    u = unit.strip().lower()
    return u in COUNT_SYNONYMS

# --- model/config for recommendations (match your CLI) ---
REC_MODEL_NAME = "BAAI/bge-large-en-v1.5"   # 1024-d
REC_MAX_LEN    = 512
REC_USE_COSINE = True
REC_TABLE      = os.getenv("DB_TABLE", "recipe.vector_db")
REC_QUERY_TMPL = "Represent this sentence for searching relevant passages: {}"                    # cosine => normalize=True

from typing import List
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
import numpy as np


# ---------- Recipe ingredient parsing & normalization ----------

# Relaxed scrubbing for common dotted abbrevs in recipes ("c.", "tsp.", etc.)
_UNIT_DOT_FIXES = {
    r"\bc\.\b": "cup",
    r"\btsp\.\b": "tsp",
    r"\btbsp\.\b": "tbsp",
    r"\boz\.\b": "oz",
    r"\blb\.\b": "lb",
}

def _preclean_recipe_line(s: str) -> str:
    s = " " + s.strip().lower() + " "
    for pat, rep in _UNIT_DOT_FIXES.items():
        s = re.sub(pat, rep, s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def parse_recipe_ingredient_line(line: str) -> tuple[float | None, str | None, str, str]:
    """
    Returns (qty, unit, name_raw, canonical_name)
    - Very tolerant: tries your PANTRY_LINE_RE after pre-clean
    - If no qty/unit found, returns (None, None, line, canon(line))
    """
    raw = line or ""
    cleaned = _preclean_recipe_line(raw)
    m = PANTRY_LINE_RE.match(cleaned)
    if not m:
        name = cleaned.strip()
        return None, None, raw, _canon_name(name)
    qty = None
    if m.group("qty"):
        try:
            qty = _parse_qty(m.group("qty"))
        except Exception:
            qty = None
    unit = m.group("unit")
    name = (m.group("name") or "").strip()
    if not name:
        name = cleaned
    return qty, unit, raw, _canon_name(name)

def normalize_need_to_base(name_raw: str, qty: float | None, unit: str | None, conn) -> tuple[str, float | None, str | None, float]:
    """
    Use your normalize_pantry_rules_only() to land in base {g/ml/count}.
    Returns (canonical_name, base_qty, base_unit, confidence)
    """
    norm = normalize_pantry_rules_only(name_raw, qty, unit, conn)
    return norm.canonical_name, norm.norm_qty, norm.norm_unit, norm.norm_conf

def _ensure_pantry_row_normalized(cur, row):
    """
    If pantry row is missing norm fields, fill them in using the same rules.
    Updates in-place in DB and returns the refreshed row.
    """
    if row.get("norm_qty") is not None and row.get("norm_unit"):
        return row

    norm = normalize_pantry_rules_only(
        row.get("name"),
        float(row["qty"]) if row.get("qty") is not None else None,
        row.get("unit"),
        None,  # conn unused in local rules
    )
    cur.execute(
        """UPDATE pantry_items
           SET canonical_name=%s, norm_qty=%s, norm_unit=%s, norm_conf=%s, norm_source=%s
           WHERE id=%s AND user_id=%s""",
        (
            norm.canonical_name or None,
            norm.norm_qty,
            norm.norm_unit,
            norm.norm_conf,
            norm.norm_source,
            row["id"],
            row["user_id"],
        ),
    )
    cur.connection.commit()
    row["canonical_name"] = norm.canonical_name
    row["norm_qty"] = norm.norm_qty
    row["norm_unit"] = norm.norm_unit
    row["norm_conf"] = norm.norm_conf
    row["norm_source"] = norm.norm_source
    return row



def _load_fact(cur, food_norm: str) -> dict | None:
    cur.execute("""SELECT food_norm, unit_kind, grams_per_count, ml_per_count, confidence, model
                   FROM pantry_norm_facts WHERE food_norm=%s""", (food_norm,))
    return cur.fetchone()

def _save_fact(cur, food_norm: str, unit: str, per_count: float, confidence: float, source="llm", model="ollama"):
    unit_kind = "mass" if unit == "g" else "volume"
    cur.execute(
      """INSERT INTO pantry_norm_facts (food_norm, unit_kind, grams_per_count, ml_per_count, model, confidence, source)
         VALUES (%s,%s,%s,%s,%s,%s,%s)
         ON DUPLICATE KEY UPDATE
           grams_per_count=VALUES(grams_per_count),
           ml_per_count=VALUES(ml_per_count),
           model=VALUES(model),
           confidence=VALUES(confidence),
           source=VALUES(source)""",
      (food_norm, unit_kind, per_count if unit=="g" else None,
                   per_count if unit=="ml" else None, model, confidence, source)
    )

def _get_density(cur, food_norm: str) -> float | None:
    cur.execute("SELECT grams_per_ml FROM food_density WHERE food_norm=%s", (food_norm,))
    row = cur.fetchone()
    return float(row["grams_per_ml"]) if row and row.get("grams_per_ml") is not None else None


OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")

_LLM_SYS = (
  "You convert everyday food counts into standard units.\n"
  "For solids return grams (g). For liquids return milliliters (ml).\n"
  "Assume 'medium' grocery-store size if unspecified. Be conservative.\n"
  "Return ONLY strict JSON: {\"unit\":\"g\"|\"ml\", \"per_count\": number, \"confidence\": 0..1}."
)

def _llm_estimate_per_count(food_name: str) -> dict | None:
    prompt = f"{_LLM_SYS}\n\nHow much is 1 {food_name} on average?"
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "options": {"temperature": 0.0}},
            timeout=20
        )
        r.raise_for_status()
        resp = r.json().get("response","").strip()
        data = json.loads(resp)
        unit = str(data.get("unit","")).lower()
        per  = float(data.get("per_count",0) or 0)
        conf = float(data.get("confidence",0) or 0)
        if unit in ("g","ml") and per > 0:
            return {"unit":unit, "per_count":per, "confidence":max(0,min(conf,1))}
    except Exception as e:
        print("LLM estimate error:", e)
    return None


def _cheap_overlap_score(a: str, b: str) -> int:
    """Tiny prefilter: token overlap count (lowercase, alnum)."""
    def toks(s: str) -> set[str]:
        s = re.sub(r"[^a-z0-9\s]", " ", (s or "").lower())
        return set(t for t in s.split() if t)
    A, B = toks(a), toks(b)
    return len(A & B)

def llm_best_pantry_match(ingredient_name: str, pantry_names: list[str]) -> tuple[int, float]:
    """
    Ask the LLM to choose the best pantry name index for the ingredient_name.
    Returns (index, confidence). index == -1 if none.
    """
    # Keep prompt short: prefilter top ~40 by cheap overlap, but always include at least 10
    scored = [(i, _cheap_overlap_score(ingredient_name, n), n) for i, n in enumerate(pantry_names)]
    scored.sort(key=lambda x: x[1], reverse=True)
    shortlist = scored[: max(10, min(40, len(scored)))]
    idx_map = {rank: orig_i for rank, (orig_i, _, _) in enumerate(shortlist)}
    names_only = [name for _, _, name in shortlist]

    # If everything is empty, bail
    if not any(n.strip() for n in names_only):
        return -1, 0.0

    prompt = (
        "You are matching a recipe ingredient to a user's pantry item.\n"
        "Pick the single best match from the numbered pantry list, or -1 if none is appropriate.\n"
        "Return ONLY a JSON object with fields: index (integer) and confidence (0..1).\n"
        "Prefer close semantic matches (synonyms acceptable). Ignore brand words.\n\n"
        f"Ingredient: {ingredient_name}\n\n"
        "Pantry options (index: name):\n" +
        "\n".join([f"{i}: {n}" for i, n in enumerate(names_only)]) +
        "\n\nJSON:"
    )

    text = _ollama_generate(prompt, json_mode=True)
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return -1, 0.0

    try:
        obj = json.loads(m.group(0))
        local_idx = int(obj.get("index", -1))
        conf = float(obj.get("confidence", 0.0))
        if local_idx < 0 or local_idx >= len(names_only):
            return -1, 0.0
        global_idx = idx_map[local_idx]
        return global_idx, max(0.0, min(1.0, conf))
    except Exception:
        return -1, 0.0
    
def llm_normalize_line(line: str) -> dict:
    """
    Normalize a free-text ingredient line to {name, qty, unit}.
    1) Pre-clean (expand dotted units like 'c.' -> 'cup', normalize spaces)
    2) Ask HF model for STRICT JSON
    3) If LLM fails or omits qty/unit, fallback to regex parse (handles fractions)
    """
    raw = (line or "").strip()
    cleaned = _preclean_recipe_line(raw)  # you already defined this

    # ---------- 1) Try Hugging Face LLM (strict JSON) ----------
    prompt = f"""
Normalize this cooking ingredient line and return ONLY JSON with keys:
- name: short canonical ingredient (lowercase, no brand words, remove adjectives like "cubed", "sliced", "fresh")
- qty: number (float) if quantity is present, else null (support mixed and fractional like "1 1/2", "1/4")
- unit: one of ["g","ml","count","cup","tbsp","tsp"] when applicable, else null
  - If the unit is a dotted abbreviation like "c.", treat as "cup"
  - For whole items like fruits/eggs, use "count"

Examples:
Input: "6 c. cubed watermelon"
Output: {{"name":"watermelon","qty":6.0,"unit":"cup"}}

Input: "1/4 c. raspberries"
Output: {{"name":"raspberries","qty":0.25,"unit":"cup"}}

Input: "1/3 c. sugar"
Output: {{"name":"sugar","qty":0.3333333333,"unit":"cup"}}

Input: "1/2 c. lemon juice"
Output: {{"name":"lemon juice","qty":0.5,"unit":"cup"}}

Input: "salt to taste"
Output: {{"name":"salt","qty":null,"unit":null}}

Now normalize:
Input: "{cleaned}"
JSON:
""".strip()

    txt = _hf_generate(prompt, max_new_tokens=160)
    m = re.search(r"\{[\s\S]*\}", txt)
    if m:
        try:
            obj = json.loads(m.group(0))
            name = str(obj.get("name") or cleaned).strip().lower()
            qty  = obj.get("qty")
            unit = obj.get("unit")
            # canonicalize unit aliases (e.g., "c" -> "cup")
            if unit:
                u = UNIT_ALIASES.get(str(unit).lower().strip(), str(unit).lower().strip())
            else:
                u = None
            # if we actually got qty+unit, return early
            if qty is not None and u:
                try:
                    qty_f = float(qty)
                    return {"name": name, "qty": qty_f, "unit": u}
                except Exception:
                    pass
            # fall through to regex fallback
        except Exception:
            pass

    # ---------- 2) Deterministic regex fallback (fractions + dotted units) ----------
    m2 = PANTRY_LINE_RE.match(cleaned)  # you already defined this
    if m2:
        name = (m2.group("name") or cleaned).strip().lower()
        unit = m2.group("unit")
        qty  = None
        if m2.group("qty"):
            try:
                qty = _parse_qty(m2.group("qty"))  # handles "1 1/2", "1/4", "2.5"
            except Exception:
                qty = None
        # map unit aliases
        u = UNIT_ALIASES.get((unit or "").lower().strip(), (unit or "").lower().strip()) or None
        # Heuristic: if there is a qty but no unit, treat as count (e.g., "1 mango")
        if qty is not None and not u:
            u = "count"
        # scrub adjectives from name (reuse your earlier head extractor if you want)
        name = canonical_head(name) or name  # you already have canonical_head
        return {"name": name, "qty": qty, "unit": u}

    # ---------- 3) Total fallback ----------
    return {"name": cleaned.lower(), "qty": None, "unit": None}


# ---------- Substring-first matching helpers ----------
_WORD_RE = re.compile(r"[a-z0-9]+")

_PREP_DROP = {
    "fresh","ripe","large","small","medium","seedless","chopped","diced",
    "sliced","minced","crushed","ground","grated","shredded","peeled",
    "packed","heaping","optional","to","taste","cubed"
}

def _clean_ingredient_text(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _strip_prep_words_from_text(s: str) -> str:
    toks = _clean_ingredient_text(s).split()
    toks = [t for t in toks if t not in _PREP_DROP]
    return " ".join(toks)

def _tokens(s: str) -> set[str]:
    return set(_WORD_RE.findall(_clean_ingredient_text(s)))

def _word_boundary_contains(haystack_text: str, needle_text: str) -> bool:
    """
    True if all tokens of 'needle' appear in 'haystack' as full words (word boundaries),
    OR if the cleaned needle is a substring of haystack (helps short names like 'lemon').
    """
    H = " " + _clean_ingredient_text(haystack_text) + " "
    N = _clean_ingredient_text(needle_text)
    if not N.strip():
        return False
    ntoks = _tokens(N)
    if ntoks and all(re.search(rf"\b{re.escape(t)}\b", H) for t in ntoks):
        return True
    return N in H

def _substring_candidates(recipe_line: str, pantry_rows: list[dict]) -> list[int]:
    """
    Return indices into pantry_rows that appear in recipe_line (substring/word-boundary).
    Uses canonical_name if present, else name; removes prep adjectives on both sides.
    """
    rtext = _strip_prep_words_from_text(recipe_line)
    out = []
    for i, pr in enumerate(pantry_rows):
        pname = (pr.get("canonical_name") or pr.get("name") or "").strip()
        pname_clean = _strip_prep_words_from_text(pname)
        if not pname_clean:
            continue
        if _word_boundary_contains(rtext, pname_clean) or _word_boundary_contains(pname_clean, rtext):
            out.append(i)
    return out

def _fallback_best_pantry_match(recipe_name: str, pantry_names: list[str]) -> tuple[int, float]:
    """
    Deterministic backup using RapidFuzz.
    Returns (index, confidence 0..1). -1 if nothing decent.
    """
    name = (recipe_name or "").strip().lower()
    if not name or not pantry_names:
        return -1, 0.0

    best_i, best_sc = -1, 0.0
    for i, p in enumerate(pantry_names):
        p2 = (p or "").strip().lower()
        if not p2:
            continue
        f1 = fuzz.token_set_ratio(name, p2) / 100.0
        f2 = fuzz.partial_ratio(name, p2) / 100.0
        sc = max(f1, f2)
        if sc > best_sc:
            best_sc, best_i = sc, i

    return (best_i, best_sc) if best_sc >= 0.70 else (-1, 0.0)



def llm_best_pantry_match(ingredient_name: str, pantry_names: list[str]) -> tuple[int, float]:
    # shortlist (same logic you already had)
    scored = [(i, _cheap_overlap_score(ingredient_name, n), n) for i, n in enumerate(pantry_names)]
    scored.sort(key=lambda x: x[1], reverse=True)
    shortlist = scored[: max(10, min(40, len(scored)))]
    idx_map = {rank: orig_i for rank, (orig_i, _, _) in enumerate(shortlist)}
    names_only = [name for _, _, name in shortlist]

    if not any(n.strip() for n in names_only):
        return -1, 0.0

    prompt = (
        "You are matching a recipe ingredient to a user's pantry item.\n"
        "Pick the single best match from the numbered pantry list, or -1 if none is appropriate.\n"
        "Return ONLY a JSON object with fields: index (integer) and confidence (0..1).\n"
        "Prefer close semantic matches (synonyms acceptable). Ignore brand words.\n\n"
        f"Ingredient: {ingredient_name}\n\n"
        "Pantry options (index: name):\n" +
        "\n".join([f"{i}: {n}" for i, n in enumerate(names_only)]) +
        "\n\nJSON:"
    )

    txt = _hf_generate(prompt, max_new_tokens=128)
    m = re.search(r"\{.*\}", txt, flags=re.S)
    if not m:
        return -1, 0.0

    try:
        obj = json.loads(m.group(0))
        local_idx = int(obj.get("index", -1))
        conf = float(obj.get("confidence", 0.0))
        if local_idx < 0 or local_idx >= len(names_only):
            return -1, 0.0
        global_idx = idx_map[local_idx]
        return global_idx, max(0.0, min(1.0, conf))
    except Exception:
        return -1, 0.0

ureg = UnitRegistry()
Q_ = ureg.Quantity



def canonicalize_qty(cur, name: str, qty: float | None, unit: str | None,
                     confidence_floor: float = 0.55, allow_llm: bool = True):
    """
    Returns (qty_canon, unit_canon, source, confidence).
    Rules:
      - mass → grams via Pint
      - volume → ml via Pint
      - count → use fact cache, or LLM (if allowed), else leave as count
      - cross mass/volume via density table only (if present)
    """
    if qty is None or qty <= 0:
        return None, None, "none", 0.0

    food_norm = _norm_food(name or "")
    u = (unit or "").strip().lower()

    # 1) Count path
    if _looks_like_count(u):
        fact = _load_fact(cur, food_norm)
        if fact:
            if fact["unit_kind"] == "mass" and fact.get("grams_per_count"):
                per = float(fact["grams_per_count"])
                return qty * per, MASS_CANON, "rule", float(fact["confidence"])
            if fact["unit_kind"] == "volume" and fact.get("ml_per_count"):
                per = float(fact["ml_per_count"])
                return qty * per, VOL_CANON, "rule", float(fact["confidence"])

        if allow_llm:
            est = _llm_estimate_per_count(food_norm)
            if est and est["confidence"] >= confidence_floor:
                _save_fact(cur, food_norm, est["unit"], est["per_count"], est["confidence"], source="llm",
                           model=f"ollama:{OLLAMA_MODEL}")
                if est["unit"] == "g":
                    return qty * est["per_count"], MASS_CANON, "llm", est["confidence"]
                else:
                    return qty * est["per_count"], VOL_CANON, "llm", est["confidence"]

        # fallback: leave as count
        return qty, "count", "none", 0.0

    # 2) Pint conversions (mass & volume)
    # Try mass first:
    try:
        q = Q_(qty, u)
        if q.check(ureg.mass):
            return float(q.to(MASS_CANON).magnitude), MASS_CANON, "rule", 0.95
        if q.check(ureg.volume):
            return float(q.to(VOL_CANON).magnitude), VOL_CANON, "rule", 0.95
    except Exception:
        pass

    # 3) Cross mass/volume only with density table (if requested later)
    # Example: if recipe says "2 cups sugar" and we want grams, use density:
    try:
        q = Q_(qty, u)
        if q.check(ureg.volume):
            ml = float(q.to(VOL_CANON).magnitude)
            dens = _get_density(cur, food_norm)  # g per ml
            if dens:
                return ml * dens, MASS_CANON, "rule", 0.90
        if q.check(ureg.mass):
            g  = float(q.to(MASS_CANON).magnitude)
            dens = _get_density(cur, food_norm)
            if dens:  # ml = g / (g/ml)
                return g / dens, VOL_CANON, "rule", 0.90
    except Exception:
        pass

    # 4) Unknown unit → store as-is
    return qty, u or None, "none", 0.0




def _canon_unit(u: str | None) -> str:
    if not u: return ""
    u = u.strip().lower()
    return UNIT_ALIASES.get(u, u)

def _canon_name(name: str | None) -> str:
    if not name: return ""
    s = re.sub(r"[^a-z0-9\s\-]", " ", name.lower())
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _parse_qty(q: str) -> float:
    q = q.strip()
    if " " in q and "/" in q:  # e.g. "1 1/2"
        a, b = q.split(" ", 1)
        num, den = b.split("/", 1)
        return float(a) + float(num) / float(den)
    if "/" in q:               # e.g. "3/4"
        num, den = q.split("/", 1)
        return float(num) / float(den)
    return float(q)



@dataclass
class NormResult:
    canonical_name: str
    norm_qty: float | None
    norm_unit: str | None
    norm_conf: float
    norm_source: str  # 'rule'

def _db_density(conn, ingredient_key: str, unit_from: str) -> float | None:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT factor FROM ingredient_density WHERE ingredient_key=%s AND unit_from=%s AND unit_to='g' LIMIT 1",
                (ingredient_key, unit_from),
            )
            r = cur.fetchone()
            if r: return float(r["factor"])
    except Exception:
        pass
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
    except Exception:
        pass
    return None

def _fractional_ounces_to_grams(oz: float) -> float:
    return oz * 28.349523125

def _maybe_size_equivalent(canon_name: str, unit: str, qty: float, conn) -> tuple[float | None, str | None, float]:
    """
    Map 'stick butter', 'clove garlic', 'egg', 'can 14oz', etc.
    returns (norm_qty, norm_unit, conf) or (None,None,0)
    """
    # butter sticks
    if "butter" in canon_name and unit in ("stick",):
        key = "stick_butter"
        u, v = _db_size_equiv(conn, key) or LOCAL_SIZE_EQ.get(key, (None, None))
        if u and v:
            return qty * float(v), u, 0.9

    # cloves of garlic
    if "garlic" in canon_name and ("clove" in canon_name or "cloves" in canon_name or unit in ("clove",)):
        key = "clove_garlic"
        u, v = _db_size_equiv(conn, key) or LOCAL_SIZE_EQ.get(key, (None, None))
        if u and v:
            return qty * float(v), u, 0.8

    # eggs
    if "egg" in canon_name and unit in ("count", "", None):
        key = "egg"
        u, v = _db_size_equiv(conn, key) or LOCAL_SIZE_EQ.get(key, (None, None))
        if u and v:
            return qty * float(v), u, 0.9

    # “can” (try to detect common 14oz / 28oz)
    if unit in ("can", "cans"):
        if "14" in canon_name and "oz" in canon_name:
            key = "can_14oz"
            u, v = _db_size_equiv(conn, key) or LOCAL_SIZE_EQ.get(key, (None, None))
            if u and v: return qty * float(v), u, 0.7
        if "28" in canon_name and "oz" in canon_name:
            key = "can_28oz"
            u, v = _db_size_equiv(conn, key) or LOCAL_SIZE_EQ.get(key, (None, None))
            if u and v: return qty * float(v), u, 0.7
        # generic “can” → leave as count
        return qty, "count", 0.6

    # pinch/dash of salt
    if "salt" in canon_name and ("pinch" in canon_name or "dash" in canon_name):
        key = "pinch_salt" if "pinch" in canon_name else "dash_salt"
        u, v = _db_size_equiv(conn, key) or LOCAL_SIZE_EQ.get(key, (None, None))
        if u and v: return qty * float(v), u, 0.6

    return None, None, 0.0

def normalize_pantry_rules_only(name: str, qty: float | None, unit: str | None, conn) -> NormResult:
    """
    1) robust parse (qty/unit/name) if user typed free text into NAME
    2) use pint for SI conversions
    3) use density (DB first, local fallback) to map volume→grams when possible
    4) use size_equivalent for package words (stick, clove, egg, can)
    """
    raw = name or ""
    m = PANTRY_LINE_RE.match(raw)
    if m:
        if qty is None and m.group("qty"):
            try:
                qty = _parse_qty(m.group("qty"))
            except Exception:
                pass
        if (not unit) and m.group("unit"):
            unit = m.group("unit")

        # name remainder
        parsed_name = m.group("name") or name
    else:
        parsed_name = name

    canon_name = _canon_name(parsed_name)
    u = _canon_unit(unit or "")

    # size-equivalent path (sticks/cans/cloves/eggs…)
    if qty is not None and (u in ("stick", "can") or "clove" in canon_name or "egg" in canon_name or "pinch" in canon_name or "dash" in canon_name):
        val, to_unit, conf = _maybe_size_equivalent(canon_name, u, float(qty), conn)
        if to_unit and val is not None:
            return NormResult(canon_name, float(val), to_unit, conf, "rule")

    # pure count
    if qty is not None and u in ("count", "", None):
        return NormResult(canon_name, float(qty), "count", 0.9, "rule")

    # mass units
    if qty is not None and u in ("g","gram","grams","kg","kilogram","kilograms","mg"):
        try:
            q = Q_(qty, u)
            g = q.to("gram").magnitude
            return NormResult(canon_name, float(g), "g", 0.95, "rule")
        except Exception:
            pass

    # volume units (try to map to grams using density; otherwise normalize to ml)
    if qty is not None and u in (
        "ml","milliliter","milliliters","l","liter","liters",
        "teaspoon","tablespoon","cup","pint","quart","gallon","ounce","oz","fluid_ounce"
    ):
        try:
            vol = Q_(qty, u)
            # try density → grams
            dens = _db_density(conn, canon_name, "cup")
            if dens is None:
                dens = LOCAL_DENSITY.get((canon_name, "cup", "g"))
            if dens is not None:
                cups = vol.to("cup").magnitude
                grams = float(cups) * float(dens)
                return NormResult(canon_name, grams, "g", 0.85, "rule")
            # fallback: normalize to ml
            ml = vol.to("milliliter").magnitude
            return NormResult(canon_name, float(ml), "ml", 0.7, "rule")
        except Exception:
            # if unit is “ounce” and ingredient is generic canned with ounces in the name
            if u in ("ounce","oz") and qty is not None:
                return NormResult(canon_name, _fractional_ounces_to_grams(float(qty)), "g", 0.7, "rule")

    # no numeric normalization possible, but we can still return canonical name
    return NormResult(canon_name, None, None, 0.5, "rule")


def _to_list_jsonish(val):
    """
    Return a list[str] from many possible DB shapes:
    - JSON text like '["a","b"]'
    - Plain text with commas/semicolons/newlines/sentences
    - Already a list (JSON column)
    - bytes -> decode
    """
    if val is None:
        return []
    if isinstance(val, (list, tuple)):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, (bytes, bytearray)):
        val = val.decode("utf-8", "ignore")
    if not isinstance(val, str):
        s = str(val).strip()
        return [s] if s else []

    s = val.strip()
    if not s:
        return []
    # Try JSON first
    try:
        j = json.loads(s)
        if isinstance(j, list):
            return [str(x).strip() for x in j if str(x).strip()]
    except Exception:
        pass
    # Fallback split on common delimiters / sentence ends
    parts = re.split(r"(?:\r?\n|\.\s+|;|,)", s)
    return [p.strip() for p in parts if p.strip()]




class PlanCreate(BaseModel):
    recipe_id: str
    planned_for: str | None = None      # "YYYY-MM-DD"
    slot: Literal["breakfast","lunch","dinner","snack"] | None = None
    servings: int | None = None
    notes: str | None = None

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

def _as_str_list(cell) -> list[str]:
    """Use the same tolerant parser you wrote, but always return list[str]."""
    return _to_list_jsonish(cell)



def bearer_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        print("AUTH: missing/format")
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        # Debug: see who we decoded
        print("DECODE OK:", payload.get("sub"), payload.get("email"))
        return payload
    except ExpiredSignatureError:
        print("DECODE FAIL: expired")
        raise HTTPException(status_code=401, detail="Token expired")
    except InvalidTokenError as e:
        # bad signature / wrong secret / malformed / etc.
        print("DECODE FAIL:", type(e).__name__, str(e))
        raise HTTPException(status_code=401, detail="Invalid token")


load_dotenv()

DB_CFG = dict(
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT", "4000")),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    database=os.getenv("DB_DATABASE"),
    ssl={"ssl": {}}  # TiDB Cloud requires TLS; local TiDB will also accept this.
)



JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret")
JWT_EXP_SECONDS = 7 * 24 * 3600
app = FastAPI(title="TiDB Auth API (FastAPI)")
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # or ["http://localhost:19006", "http://192.168.x.x:8081"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi import Request

@app.middleware("http")
async def log_requests(request: Request, call_next):
    print("REQ", request.method, request.url)
    response = await call_next(request)
    print("RES", response.status_code)
    return response


@app.middleware("http")
async def log_auth_header(request: Request, call_next):
    if request.url.path.startswith("/api/pantry"):
        print("AUTH HDR:", request.headers.get("authorization"))
    return await call_next(request)

# ⚠️ In production, restrict origins to your domain
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Models ----------

class PantryIn(BaseModel):
    name: str
    qty: Optional[condecimal(max_digits=10, decimal_places=2)] = None
    unit: Optional[str] = None
    expires_on: Optional[str] = None  # "YYYY-MM-DD"

class PantryOut(BaseModel):
    id: int
    name: str
    qty: Optional[float] = None
    unit: Optional[str] = None
    expires_on: Optional[str] = None
    added_at: str


class RegisterIn(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    password: str

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class UserOut(BaseModel):
    id: int
    email: EmailStr
    first_name: str
    last_name: str

class AuthOut(BaseModel):
    token: str
    user: UserOut

class CookIn(BaseModel):
    servings_override: int | None = None

class CookOut(BaseModel):
    plan_id: int
    servings_used: int | None = None
    deductions: list[dict] = []
    unfilled: list[dict] = []

# ---------- Helpers ----------
def get_conn():
    return pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **DB_CFG)

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")

def check_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False

# main.py

_rec_model = None
def get_rec_model():
    global _rec_model
    if _rec_model is None:
        m = SentenceTransformer(REC_MODEL_NAME)
        m.max_seq_length = REC_MAX_LEN
        _rec_model = m
    return _rec_model

def vec_literal(v: np.ndarray) -> str:
    v = np.asarray(v, dtype=np.float32)
    return "[" + ", ".join(f"{x:.7f}" for x in v) + "]"





# very common “filler” items so they don’t dominate overlap
# ---------- Pantry + ingredient normalization helpers ----------
import re, json

_TOKEN_RE = re.compile(r"[^a-z ]")

def _norm_token(s: str) -> str:
    s = s.lower()
    s = re.sub(r"\d+/?\d*\s*", " ", s)
    s = re.sub(r"\b(c\.|cup|cups|tsp|tbsp|teaspoon|tablespoon|stick|sticks|pkg|package|cans?|oz|lb|lbs|large|small)\b", " ", s)
    s = _TOKEN_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()



def parse_ingredients(cell) -> list[str]:
    """
    Ingredients in DB can be a JSON list (preferred) or a raw string.
    Return a list of normalized tokens.
    """
    if not cell:
        return []
    raw_list = []
    if isinstance(cell, (list, tuple)):
        raw_list = list(cell)
    else:
        try:
            j = json.loads(cell)
            if isinstance(j, list):
                raw_list = j
            else:
                raw_list = [str(cell)]
        except Exception:
            raw_list = [str(cell)]

    out = []
    for t in raw_list:
        tok = _norm_token(str(t))
        if tok:
            out.append(tok)
    return out

def tokenize_recipe_ingredients(cell) -> set[str]:
    """Unique normalized tokens for a recipe’s ingredients."""
    return set(parse_ingredients(cell))

def pantry_name_set_for_user(cur, user_id: int) -> set[str]:
    """
    Load the user’s pantry item names and normalize them.
    Works with DictCursor or tuple cursor.
    """
    cur.execute("SELECT name FROM pantry_items WHERE user_id=%s", (user_id,))
    rows = cur.fetchall() or []
    out = set()
    for row in rows:
        name = row["name"] if isinstance(row, dict) else row[0]
        tok = _norm_token(name)
        if tok:
            out.add(tok)
    return out


def overlap_count(ingredients_cell: str, pantry_set: set[str]) -> tuple[int, list[str]]:
    """Count matches and return which pantry items were used."""
    ing_tokens = parse_ingredients(ingredients_cell)
    if not ing_tokens or not pantry_set:
        return 0, []

    matched = []
    score = 0
    for p in pantry_set:
        # regex word boundary search across each ingredient token
        pat = re.compile(rf"\b{re.escape(p)}\b", re.IGNORECASE)
        for ing in ing_tokens:
            if pat.search(ing) or p in ing or ing in p:
                score += 1
                matched.append(p)
                break  # count pantry item once
    return score, matched



def _jaccard(a: Set[str], b: Set[str]) -> float:
    return 0.0 if not a and not b else len(a & b) / len(a | b)

def _coverage(recipe_tokens: Set[str], pantry: Set[str]) -> float:
    return 0.0 if not recipe_tokens else len(recipe_tokens & pantry) / len(recipe_tokens)

def _normalize_dist_scores(dists: List[float]) -> List[float]:
    """Convert distances to 0..1, higher is better (smaller distance = better)."""
    if not dists:
        return []
    lo, hi = min(dists), max(dists)
    if hi <= lo:
        return [1.0] * len(dists)
    return [1 - (d - lo) / (hi - lo) for d in dists]

# ---------- Request/Response models ----------
from pydantic import BaseModel

class RecommendIn(BaseModel):
    query: str
    k: int = 5          # final results to return
    m: int = 50         # candidate pool before rerank
    w1_query: float = 0.70
    w2_overlap: float = 0.20
    w3_cover: float = 0.10
    min_cover: float | None = None  # optional gate, e.g. 0.2

# models near your /api/recommend
class RecItem(BaseModel):
    id: str                  # <-- was int
    title: str | None = None
    dist: float
    # pantry scores (unchanged)
    query_score: float | None = None
    overlap_score: float | None = None
    cover_score: float | None = None
    final: float | None = None
    used_from_pantry: list[str] | None = None
    missing: list[str] | None = None


class RecommendOut(BaseModel):
    items: list[RecItem]


class DeductIn(TypedDict, total=False):
    plan_id: int
    servings: int         # if True, compute deltas but do not write changes

class DeductOut(BaseModel):
    plan_id: int
    servings_used: int
    deducted: list[dict]       # [{pantry_item_id, canonical_name, unit, amount_used, remaining}]
    shortages: list[dict]      # [{canonical_name, unit, amount_short}]
    unmatched: list[dict]      # [{original_line}]
    notes: str | None = None

NAME_SYNONYMS = {

}

def _canon(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def _name_tokens(s: str) -> set[str]:
    return set(t for t in _canon(s).split() if t)

def _syn_family(name: str) -> str | None:
    name_c = _canon(name)
    for fam, words in NAME_SYNONYMS.items():
        if name_c in words:
            return fam
    return None

def _name_match_score(recipe_name: str, pantry_name: str) -> int:
    """Heuristic score (>=0). Higher means better match."""
    r = _canon(recipe_name)
    p = _canon(pantry_name)
    if not r or not p:
        return 0
    if r == p:
        return 100
    score = 0
    # substring matches
    if r in p or p in r:
        score += 30
    # token overlap
    rt, pt = _name_tokens(r), _name_tokens(p)
    overlap = len(rt & pt)
    score += min(20, overlap * 5)  # up to +20
    # synonym family
    rf, pf = _syn_family(r), _syn_family(p)
    if rf and pf and rf == pf:
        score += 25
    # prefer shorter pantry names when otherwise equal (less noise words)
    score -= abs(len(p) - len(r)) // 10
    return max(score, 0)

def _pick_best_pantry(recipe_name: str, pantry_rows: list[dict]) -> dict | None:
    best = None
    best_score = 0
    for row in pantry_rows:
        pn = row.get("canonical_name") or row.get("name") or ""
        sc = _name_match_score(recipe_name, pn)
        if sc > best_score:
            best_score = sc
            best = row
    # require at least some match strength
    return best if best_score >= 15 else None

def llm_convert_between(name: str, qty: float, unit_from: str, unit_to: str) -> float:
    """
    Convert qty from unit_from to unit_to using HF model (density-aware if needed).
    Returns a float. If it can't, returns the original qty.
    """
    uf = (unit_from or "").lower().strip()
    ut = (unit_to   or "").lower().strip()
    if not uf or not ut or uf == ut:
        return float(qty)

    prompt = f"""
Convert this cooking quantity using typical culinary assumptions/density for the specific ingredient.
Return ONLY a number (no unit, no words).

Ingredient: {name}
Value: {qty}
From: {uf}
To: {ut}

Number only:
""".strip()

    txt = _hf_generate(prompt, max_new_tokens=64)
    m = re.search(r"-?\d+(?:\.\d+)?", txt or "")
    try:
        return float(m.group(0)) if m else float(qty)
    except Exception:
        return float(qty)


def sign_token(user_row: dict) -> str:
    payload = {
        "sub": str(user_row["id"]),   # ← make it a string
        "email": user_row["email"],
        "first_name": user_row["first_name"],
        "last_name": user_row["last_name"],
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXP_SECONDS,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")



def llm_convert_amount(qty: float, from_unit: str | None, to_unit: str, name: str) -> float | None:
    """
    Ask your LLM to convert qty/from_unit/name → qty in to_unit.
    Return None if it can’t.
    """
    # TODO: call local LLM here. For now just pass through when units match.
    if (from_unit or "").lower() == (to_unit or "").lower():
        return qty
    # Heuristic fallback when LLM is not hooked yet: give up.
    return None

# --- LLM helpers (normalizer + converter) ------------------------




# def llm_normalize_line(line: str) -> dict:
#     """
#     Return a JSON object like:
#       {"name": "sugar", "qty": 2.0, "unit": "cup"}
#     When qty unknown -> omit or null.
#     """
#     prompt = f"""Normalize this ingredient to JSON with fields: name (short canonical), qty (number if present), unit (singular, like g, ml, cup, tbsp, tsp, count).
# Input: {line}
# Only output JSON."""
#     txt = _llm_chat(prompt)
#     try:
#         # find first {...}
#         m = re.search(r"\{[\s\S]*\}", txt)
#         if m:
#             return json.loads(m.group(0))
#         return json.loads(txt)
#     except Exception:
#         # worst case, return the line as name
#         return {"name": line.strip()}


def llm_convert_quantity(name: str, qty: float, from_unit: str, to_unit: str) -> float | None:
    """
    Ask the LLM to convert a quantity for a specific ingredient (may require density).
    Returns a float in 'to_unit', or None on failure.
    """
    if from_unit == to_unit:
        return float(qty)
    prompt = f"""Convert the following ingredient quantity to a target unit. 
Respond with ONLY a number (no unit, no words).
Ingredient: {name}
Quantity: {qty} {from_unit}
Target unit: {to_unit}
Just the number, high-precision decimal."""
    txt = _llm_chat(prompt).strip()
    # keep only the first number-looking token
    m = re.search(r"[-+]?\d+(\.\d+)?", txt)
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None







# ---------- Routes ----------
@app.post("/api/register", response_model=AuthOut)
def register(body: RegisterIn):
    email = body.email.lower().strip()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE email=%s", (email,))
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="Email already registered")

        pw_hash = hash_password(body.password)
        cur.execute(
            "INSERT INTO users (email, first_name, last_name, password_hash) VALUES (%s, %s, %s, %s)",
            (email, body.first_name.strip(), body.last_name.strip(), pw_hash),
        )
        conn.commit()
        user_id = cur.lastrowid

        user = {"id": user_id, "email": email, "first_name": body.first_name.strip(), "last_name": body.last_name.strip()}
        token = sign_token(user)
        return {"token": token, "user": user}

@app.post("/api/login", response_model=AuthOut)
def login(body: LoginIn):
    email = body.email.lower().strip()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE email=%s", (email,))
        row = cur.fetchone()
        if not row or not check_password(body.password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        user = {"id": row["id"], "email": row["email"], "first_name": row["first_name"], "last_name": row["last_name"]}
        token = sign_token(user)
        return {"token": token, "user": user}

@app.get("/api/me")
def me(user=Depends(bearer_user)):
    return {"user": user}

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/api/pantry")
def list_pantry(user=Depends(bearer_user)):
    uid = int(user["sub"])
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, name, qty, unit,
                      canonical_name, norm_qty, norm_unit, norm_conf, norm_source,
                      DATE_FORMAT(expires_on, '%%Y-%%m-%%d') AS expires_on,
                      DATE_FORMAT(added_at, '%%Y-%%m-%%d %%H:%%i:%%s') AS added_at
               FROM pantry_items
               WHERE user_id=%s
               ORDER BY added_at DESC, id DESC""",
            (uid,),
        )
        return cur.fetchall()


@app.post("/api/pantry", response_model=PantryOut)
def create_pantry_item(body: PantryIn, user=Depends(bearer_user)):
    uid = int(user["sub"])
    with get_conn() as conn, conn.cursor() as cur:
        # Let the LLM parse the user's line (qty/unit/name may be split across fields)
        norm = llm_normalize_line(f"{body.qty or ''} {body.unit or ''} {body.name or ''}".strip())
        cur.execute(
            """INSERT INTO pantry_items (user_id, name, qty, unit, expires_on,
                                         canonical_name, norm_qty, norm_unit, norm_conf, norm_source)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0.9, 'llm')""",
            (
                uid,
                (body.name or "").strip(),
                body.qty, body.unit, body.expires_on,
                norm.get("name") or None, norm.get("qty"), norm.get("unit"),
            ),
        )
        conn.commit()
        new_id = cur.lastrowid
        cur.execute(
            """SELECT id, name, qty, unit,
                      DATE_FORMAT(expires_on, '%%Y-%%m-%%d') AS expires_on,
                      DATE_FORMAT(added_at, '%%Y-%%m-%%d %%H:%%i:%%s') AS added_at
               FROM pantry_items
               WHERE id=%s AND user_id=%s""",
            (new_id, uid),
        )
        return cur.fetchone()




@app.delete("/api/pantry/{item_id}")
def delete_pantry_item(item_id: int, user=Depends(bearer_user)):
    uid = int(user["sub"])
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM pantry_items WHERE id=%s AND user_id=%s", (item_id, uid))
        conn.commit()
    return {"ok": True}



@app.put("/api/pantry/{item_id}", response_model=PantryOut)
def update_pantry_item(item_id: int, body: PantryIn, user=Depends(bearer_user)):
    uid = int(user["sub"])
    with get_conn() as conn, conn.cursor() as cur:
        # 🔹 Normalize with your LLM
        norm = llm_normalize_line(f"{body.qty or ''} {body.unit or ''} {body.name}")

        # 🔹 Update, keeping both raw user input and normalized fields
        cur.execute(
            """UPDATE pantry_items
               SET name=%s,
                   qty=%s,
                   unit=%s,
                   expires_on=%s,
                   canonical_name=%s,
                   norm_qty=%s,
                   norm_unit=%s,
                   norm_conf=%s,
                   norm_source='llm'
               WHERE id=%s AND user_id=%s""",
            (
                body.name.strip(),
                body.qty,
                body.unit,
                body.expires_on,
                norm["name"],
                norm.get("qty"),
                norm.get("unit"),
                0.9,
                item_id,
                uid,
            ),
        )
        conn.commit()

        # 🔹 Return the updated row (fields required by PantryOut)
        cur.execute(
            """SELECT id, name, qty, unit,
                      DATE_FORMAT(expires_on, '%%Y-%%m-%%d') AS expires_on,
                      DATE_FORMAT(added_at, '%%Y-%%m-%%d %%H:%%i:%%s') AS added_at
               FROM pantry_items
               WHERE id=%s AND user_id=%s""",
            (item_id, uid),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        return row



    



@app.post("/api/recommend", response_model=RecommendOut)
def recommend(body: RecommendIn, user=Depends(bearer_user)):
    q = body.query.strip()
    debug: int = Query(0, description="Return matching internals if 1"),

    if not q:
        raise HTTPException(status_code=400, detail="Empty query")

    # 1) embed query (BGE + template)
    model = get_rec_model()
    q_text = REC_QUERY_TMPL.format(q)
    q_vec  = model.encode(
        [q_text],
        normalize_embeddings=REC_USE_COSINE,
        convert_to_numpy=True,
        show_progress_bar=False
    )[0]
    q_lit = vec_literal(q_vec)

    dist_fn = "VEC_COSINE_DISTANCE" if REC_USE_COSINE else "VEC_L2_DISTANCE"
    TOP_N = max(10, body.m or 50)

    with get_conn() as conn, conn.cursor() as cur:
        # pantry set
        uid = int(user["sub"])
        pantry_set = pantry_name_set_for_user(cur, uid)

        # grab vector top-N (now include ingredients)
        sql = f"""
            SELECT id, title, ingredients, {dist_fn}(embedding, %s) AS dist
            FROM {REC_TABLE}
            ORDER BY dist ASC
            LIMIT %s
        """
        cur.execute(sql, (q_lit, TOP_N))
        rows = cur.fetchall() or []

    # weights / gate
    w1 = float(body.w1_query)
    w2 = float(body.w2_overlap)
    w3 = float(body.w3_cover)
    min_cover = body.min_cover

    # 2) score & rerank
    results = []
    for r in rows:
        rid   = str(r["id"])  
        title = r.get("title")
        dist  = float(r["dist"])
        ings  = r.get("ingredients")

        # query component (smaller dist -> bigger score)
        query_score = 1.0 / (1.0 + dist)

        # pantry overlap signals
        recipe_tokens = tokenize_recipe_ingredients(ings)
        used = []
        if pantry_set and recipe_tokens:
            # exact/substring regex pass (same as you added before)
            # count matches & build used list
            matched = []
            for p in pantry_set:
                pat = re.compile(rf"\b{re.escape(p)}\b", re.IGNORECASE)
                if any(pat.search(t) or p in t or t in p for t in recipe_tokens):
                    matched.append(p)

            used = matched
            inter = len(matched)
            union = len(recipe_tokens | pantry_set)
            overlap_score = (inter / union) if union else 0.0
            cover_score   = (inter / len(recipe_tokens)) if recipe_tokens else 0.0
        else:
            overlap_score = 0.0
            cover_score   = 0.0

        # optional gate
        if min_cover is not None and cover_score < float(min_cover):
            continue

        final = w1 * query_score + w2 * overlap_score + w3 * cover_score

        # a short “missing” preview (handy in UI)
        missing = []
        if recipe_tokens and pantry_set:
            # choose up to 5 tokens that didn't match
            # simple heuristic: tokens not in ‘used’ substrings
            used_set = set(used)
            for t in recipe_tokens:
                if not any(u in t or t in u for u in used_set):
                    missing.append(t)
                if len(missing) >= 5:
                    break

        results.append({
            "id": rid,
            "title": title,
            "dist": dist,
            "query_score": query_score,
            "overlap_score": overlap_score,
            "cover_score": cover_score,
            "final": final,
            "used_from_pantry": used[:10],
            "missing": missing,
        })

    results.sort(key=lambda x: x["final"], reverse=True)
    topk = results[: (body.k or 5)]

    return RecommendOut(items=[RecItem(**it) for it in topk])

@app.get("/api/recipe/{rid}")
def get_recipe_detail(rid: str, user=Depends(bearer_user)):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""SELECT id, title, ingredients, directions
                FROM {REC_TABLE}
                WHERE id = %s
                LIMIT 1""",
            (rid,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Recipe not found")

        ings = _to_list_jsonish(row.get("ingredients"))
        dirs = _to_list_jsonish(row.get("directions"))

        return {
            "id": str(row["id"]),      # keep as string for consistency with client
            "title": row.get("title"),
            "ingredients": ings,       # string[]
            "directions": dirs,        # string[]
        }



# ---------- Create: copy recipe fields into meal_plan ----------
@app.post("/api/mealplan", response_model=PlanItemOut)
def add_to_mealplan(body: PlanCreate, user=Depends(bearer_user)):
    uid = int(user["sub"])
    rid = body.recipe_id.strip()
    if not rid:
        raise HTTPException(status_code=400, detail="Missing recipe_id")

    with get_conn() as conn, conn.cursor() as cur:
        # 1) fetch the recipe from your vector table
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

        # 3) reselect for normalized output
        cur.execute(
            """SELECT id, recipe_id, title, ingredients, directions,
                      DATE_FORMAT(planned_for, '%%Y-%%m-%%d') AS planned_for,
                      slot, servings, notes,
                      DATE_FORMAT(created_at, '%%Y-%%m-%%d %%H:%%i:%%s') AS created_at
               FROM meal_plan WHERE id=%s AND user_id=%s""",
            (pid, uid),
        )
        out = cur.fetchone()

    return PlanItemOut(
        id=out["id"],
        recipe_id=str(out["recipe_id"]),
        title=out.get("title"),
        ingredients=_as_str_list(out.get("ingredients")),
        directions=_as_str_list(out.get("directions")),
        planned_for=out.get("planned_for"),
        slot=out.get("slot"),
        servings=out.get("servings"),
        notes=out.get("notes"),
        created_at=out["created_at"],
    )

# ---------- List a user's plan (optionally by date range) ----------
@app.get("/api/mealplan")
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

    # parse JSON-ish ingredients/directions to string arrays
    def _to_list_jsonish(val):
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
        # fallback split
        parts = re.split(r"(?:\r?\n|\.\s+|;|,)", s)
        return [p.strip() for p in parts if p.strip()]

    items = []
    for r in rows:
        items.append({
            "id": str(r["id"]),
            "user_id": str(r["user_id"]),
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

# ---------- Delete a planned item ----------
@app.delete("/api/mealplan/{plan_id}")
def delete_mealplan_item(plan_id: int, user=Depends(bearer_user)):
    uid = int(user["sub"])
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM meal_plan WHERE id=%s AND user_id=%s", (plan_id, uid))
        conn.commit()
    return {"ok": True}




@app.post("/api/mealplan/{plan_id}/deduct", response_model=DeductOut)
def cook_and_deduct(plan_id: int, body: DeductIn, user=Depends(bearer_user)):
    uid = int(user["sub"])
    with get_conn() as conn, conn.cursor() as cur:
        # 1) Load the plan
        cur.execute(
            """SELECT id, user_id, recipe_id, title, ingredients, directions, servings
               FROM meal_plan WHERE id=%s AND user_id=%s LIMIT 1""",
            (plan_id, uid),
        )
        plan = cur.fetchone()
        if not plan:
            raise HTTPException(status_code=404, detail="Meal plan not found")

        # 2) Determine serving scale
        planned_servings = int(plan["servings"] or 1)
        used_servings = int(body.servings_used or planned_servings or 1)
        scale = (used_servings / planned_servings) if planned_servings else 1.0

        # 3) Parse ingredients list (string[] tolerant)
        ing_list = _to_list_jsonish(plan.get("ingredients"))
        if not ing_list:
            return DeductOut(
                plan_id=plan_id,
                servings_used=used_servings,
                deducted=[],
                shortages=[],
                unmatched=[{"original_line": "(no ingredients found)"}],
                notes="Recipe has no ingredient lines.",
            )

        # 4) Build normalized needs in base unit
        needs = []   # [{canonical_name, unit, qty}]
        unmatched = []
        for line in ing_list:
            qty, unit, raw, canon = parse_recipe_ingredient_line(line)
            if qty is None and unit is None:
                # we can't quantify -> leave as unmatched
                unmatched.append({"original_line": raw})
                continue
            # scale quantity by servings used
            qty_scaled = qty * scale if qty is not None else None
            canon_name, base_qty, base_unit, conf = normalize_need_to_base(raw, qty_scaled, unit, conn)
            if base_qty is None or not base_unit:
                unmatched.append({"original_line": raw})
                continue
            needs.append({"canonical_name": canon_name, "unit": base_unit, "qty": float(base_qty), "raw": raw})

        if not needs:
            return DeductOut(
                plan_id=plan_id,
                servings_used=used_servings,
                deducted=[],
                shortages=[],
                unmatched=unmatched,
                notes="No quantifiable ingredients to deduct.",
            )

        # 5) Load pantry rows and ensure normalization
        cur.execute(
            """SELECT id, user_id, name, qty, unit, canonical_name, norm_qty, norm_unit, norm_conf,
                      DATE_FORMAT(expires_on,'%%Y-%%m-%%d') AS expires_on,
                      DATE_FORMAT(added_at,'%%Y-%%m-%%d %%H:%%i:%%s') AS added_at
               FROM pantry_items WHERE user_id=%s
               ORDER BY COALESCE(expires_on, '9999-12-31') ASC, added_at ASC, id ASC""",
            (uid,),
        )
        pantry_rows = cur.fetchall() or []
        for pr in pantry_rows:
            _ensure_pantry_row_normalized(cur, pr)

        # Group pantry by (canonical_name, unit)
        by_key = {}
        for pr in pantry_rows:
            key = (pr.get("canonical_name") or _canon_name(pr.get("name")), pr.get("norm_unit"))
            if key not in by_key: by_key[key] = []
            by_key[key].append(pr)

        # 6) Deduct across pantry rows
        deducted = []
        shortages = []
        if not body.dry_run:
            conn.begin()

        for need in needs:
            key = (need["canonical_name"], need["unit"])
            remaining_need = need["qty"]
            rows = by_key.get(key, [])
            for pr in rows:
                if remaining_need <= 0: break
                available = float(pr["norm_qty"] or 0.0)
                if available <= 0: continue
                use = min(available, remaining_need)
                remaining_need -= use
                new_qty = max(0.0, available - use)

                if not body.dry_run:
                    cur.execute(
                        "UPDATE pantry_items SET norm_qty=%s WHERE id=%s AND user_id=%s",
                        (new_qty, pr["id"], uid),
                    )

                deducted.append({
                    "pantry_item_id": pr["id"],
                    "canonical_name": key[0],
                    "unit": key[1],
                    "amount_used": float(use),
                    "remaining": float(new_qty),
                })

            if remaining_need > 1e-9:
                shortages.append({
                    "canonical_name": key[0],
                    "unit": key[1],
                    "amount_short": float(remaining_need),
                })

        if not body.dry_run:
            conn.commit()

        return DeductOut(
            plan_id=plan_id,
            servings_used=used_servings,
            deducted=deducted,
            shortages=shortages,
            unmatched=unmatched,
            notes=None,
        )
    

@app.post("/api/mealplan/{plan_id}/cook")
def cook_mealplan_item(plan_id: int, user=Depends(bearer_user)):
    """
    Deduct pantry quantities for the chosen meal plan item.
    - Normalize each recipe ingredient with llm_normalize_line
    - Use LLM to choose the best pantry item (no synonym dicts)
    - Convert units with llm_convert_between if needed
    - Deduct only if enough stock; otherwise report shortage (no partial)
    """
    uid = int(user["sub"])

    with get_conn() as conn, conn.cursor() as cur:
        # Load the meal plan row
        cur.execute(
            """SELECT id, recipe_id, title, ingredients, directions, servings
               FROM meal_plan
               WHERE id=%s AND user_id=%s
               LIMIT 1""",
            (plan_id, uid),
        )
        plan = cur.fetchone()
        if not plan:
            raise HTTPException(status_code=404, detail="Meal plan not found")

        # Parse ingredients from plan (already stored there)
        ing_lines = _to_list_jsonish(plan.get("ingredients"))

        # Load pantry rows for user (and ensure they are normalized)
        cur.execute(
            """SELECT id, user_id, name, qty, unit,
                    canonical_name, norm_qty, norm_unit, norm_conf, norm_source
            FROM pantry_items
            WHERE user_id=%s
            ORDER BY id ASC""",
            (uid,),
        )
        pantry_rows = cur.fetchall() or []

        # Fill canonical_name / norm_qty / norm_unit if missing
        for pr in pantry_rows:
            _ensure_pantry_row_normalized(cur, pr)



        deducted = []
        shortages = []

        # Multiplier based on servings (optional; defaults to 1)
        servings_mult = float(plan.get("servings") or 1)

        for raw_line in ing_lines:
            # Step 1: normalize the recipe line via LLM
            norm = llm_normalize_line(raw_line)
            r_name = norm.get("name") or raw_line
            r_qty  = norm.get("qty")
            r_unit = norm.get("unit")

            if r_qty is None or r_unit is None:
                shortages.append({"ingredient": raw_line, "reason": "no quantity parsed"})
                continue

            # scale by servings if desired
            use_qty  = float(r_qty) * servings_mult
            use_unit = r_unit

            # ---------- SUBSTRING-FIRST MATCHING ----------
            # 1) Try substring/word-boundary candidates from the raw recipe line
            cand_idxs = _substring_candidates(raw_line, pantry_rows)

            if len(cand_idxs) == 1:
                best_idx = cand_idxs[0]
                conf = 0.90
            elif len(cand_idxs) > 1:
                # tie-break: prefer pantry name with the longest cleaned text (more specific)
                def _plen(i):
                    pname = (pantry_rows[i].get("canonical_name") or pantry_rows[i].get("name") or "")
                    return len(_strip_prep_words_from_text(pname))
                cand_idxs.sort(key=_plen, reverse=True)
                best_idx = cand_idxs[0]
                conf = 0.80
            else:
                # 2) No substring match → optional LLM/fuzzy fallback among all pantry names
                pantry_names = [(r.get("canonical_name") or r.get("name") or "").strip() for r in pantry_rows]
                best_idx, conf = llm_best_pantry_match(r_name, pantry_names)
                if best_idx < 0 or conf < 0.50:
                    fb_idx, fb_conf = _fallback_best_pantry_match(r_name, pantry_names)
                    if fb_idx >= 0 and fb_conf >= 0.70:
                        best_idx, conf = fb_idx, fb_conf

            # 3) If still nothing, mark shortage
            if best_idx < 0:
                shortages.append({"ingredient": raw_line, "reason": "no matching pantry item"})
                continue

            # 4) Pull the winning pantry row
            prow  = pantry_rows[best_idx]
            p_id  = int(prow["id"])
            p_name = (prow.get("canonical_name") or prow.get("name") or "").strip()
            p_qty  = prow.get("norm_qty")
            p_unit = prow.get("norm_unit")

            if p_qty is None or p_unit is None:
                shortages.append({"ingredient": raw_line, "reason": f"pantry item '{p_name}' missing normalized qty/unit"})
                continue


            # Step 3: convert the recipe need to pantry unit using LLM
            need_in_pantry_unit = llm_convert_between(r_name, use_qty, use_unit, p_unit)
            if need_in_pantry_unit is None or not np.isfinite(need_in_pantry_unit):
                # last-resort: assume same numeric amount if units match; else pass through qty
                need_in_pantry_unit = float(use_qty) if (use_unit == p_unit) else float(use_qty)

            # Step 4: compare and deduct
            if float(p_qty) >= float(need_in_pantry_unit):
                new_qty = float(p_qty) - float(need_in_pantry_unit)
                cur.execute(
                    "UPDATE pantry_items SET norm_qty=%s WHERE id=%s AND user_id=%s",
                    (new_qty, p_id, uid),
                )
                deducted.append({
                    "ingredient": raw_line,
                    "matched_pantry": p_name,
                    "used": f"{round(need_in_pantry_unit, 2)} {p_unit}",
                    "remaining": f"{round(new_qty, 2)} {p_unit}",
                    "match_conf": round(conf, 2),
                })
            else:
                need_disp = f"{round(need_in_pantry_unit, 2)} {p_unit}"
                have_disp = f"{round(float(p_qty), 2)} {p_unit}"
                diff = round(float(need_in_pantry_unit) - float(p_qty), 2)
                shortages.append({
                    "ingredient": raw_line,
                    "reason": f"need {need_disp}, have {have_disp}, short by ~{diff} {p_unit}",
                    "matched_pantry": p_name,
                    "match_conf": round(conf, 2),
                })

        conn.commit()

    return {
        "ok": True,
        "plan_id": plan_id,
        "deducted": deducted,
        "shortages": shortages,
    }
