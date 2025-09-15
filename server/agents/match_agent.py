from rapidfuzz import fuzz
from typing import List, Tuple, Optional
import re, json

_WORDS = re.compile(r"[a-z0-9]+")

def _cheap_overlap(a: str, b: str) -> int:
    A = set(_WORDS.findall((a or "").lower()))
    B = set(_WORDS.findall((b or "").lower()))
    return len(A & B)

def _wb_contains(hay: str, ned: str) -> bool:
    """word-boundary or substring containment"""
    h = f" {re.sub(r'[^a-z0-9 ]',' ', (hay or '').lower()).strip()} "
    n = re.sub(r'[^a-z0-9 ]',' ', (ned or '').lower()).strip()
    if not n: return False
    # every token appears as a word OR raw substring hit
    toks = [t for t in n.split() if t]
    return (all(re.search(rf"\b{re.escape(t)}\b", h) for t in toks)) or (n in h)

def best_match_substring_first(
    ingredient: str,
    pantry_names: List[str],
    *,
    llm: Optional[callable] = None,   # callable that takes a prompt and returns text
    use_llm: bool = True,
    fuzzy_accept: float = 0.82,
    debug: Optional[dict] = None
) -> Tuple[int, float]:
    """
    Returns (best_index, confidence 0..1).
    - Fast path: word-boundary / substring match → 0.95
    - Fallback: RapidFuzz token_set/partial → if >= fuzzy_accept
    - Optional: LLM shortlist (0..1), only if llm is provided and use_llm=True
    """
    ing = (ingredient or "").lower().strip()
    if debug is not None:
        debug.clear()
        debug.update({"ingredient": ing, "candidates": pantry_names, "steps": []})

    if not pantry_names:
        if debug is not None: debug["steps"].append({"stage":"empty", "result":(-1,0.0)})
        return (-1, 0.0)

    # 1) Word boundary / substring fast check
    for i, p in enumerate(pantry_names):
        p2 = (p or "").lower().strip()
        if not p2: 
            continue
        if _wb_contains(p2, ing) or _wb_contains(ing, p2):
            if debug is not None: debug["steps"].append({"stage":"wb/substring", "pick":i, "conf":0.95, "hit":p2})
            return (i, 0.95)

    # 2) Fuzzy (RapidFuzz)
    best_i, best_sc = -1, 0.0
    for i, p in enumerate(pantry_names):
        p2 = (p or "").lower().strip()
        if not p2:
            continue
        sc = max(fuzz.token_set_ratio(ing, p2), fuzz.partial_ratio(ing, p2)) / 100.0
        if sc > best_sc:
            best_sc, best_i = sc, i
    if debug is not None: debug["steps"].append({"stage":"fuzzy", "best_i":best_i, "best_sc":best_sc})

    if best_sc >= fuzzy_accept:
        return (best_i, best_sc)

    # 3) Optional LLM shortlist (only if provided)
    if use_llm and callable(llm):
        scored = sorted(
            [(i, _cheap_overlap(ing, p or ""), (p or "")) for i, p in enumerate(pantry_names)],
            key=lambda x: x[1], reverse=True
        )[: max(10, min(40, len(pantry_names)))]
        if scored:
            opts = [name for _,__,name in scored]
            prompt = (
                "You are matching a recipe ingredient to a user's pantry item.\n"
                "Pick the single best match index from the numbered list (0-based), or -1 if none fits.\n"
                "Return ONLY JSON: {\"index\": int, \"confidence\": 0..1}\n\n"
                f"Ingredient: {ing}\n\n"
                "Pantry options:\n" +
                "\n".join(f"{i}: {n}" for i, n in enumerate(opts)) +
                "\n\nJSON:"
            )
            try:
                text = llm(prompt)  # must return string
                m = re.search(r"\{.*\}", text, flags=re.S)
                if m:
                    obj = json.loads(m.group(0))
                    local_idx = int(obj.get("index", -1))
                    conf = float(obj.get("confidence", 0.0))
                    if 0 <= local_idx < len(opts):
                        global_idx = [i for i,_,_ in scored][local_idx]
                        if debug is not None: debug["steps"].append({"stage":"llm", "pick":global_idx, "conf":conf})
                        return (global_idx, max(0.0, min(1.0, conf)))
            except Exception as e:
                if debug is not None: debug["steps"].append({"stage":"llm_error", "error": str(e)})

    # 4) Nothing strong → return fuzzy best (even if below threshold)
    if debug is not None: debug["steps"].append({"stage":"fallback", "pick":best_i, "conf":best_sc})
    return (best_i, best_sc)
