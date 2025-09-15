# server/agents/pantry_scoring.py
from typing import Iterable, List, Dict, Tuple, Set
from db import _norm_text

def pantry_overlap(
    pantry_terms: Set[str],
    recipe_ingredients: Iterable[str],
) -> Tuple[List[str], float, float]:
    """
    Returns:
      have_names: list[str]  -> ingredients that are in both pantry and recipe (normalized, unique, original cased if possible)
      overlap: float         -> fraction of recipe ingredients present in pantry (|hits| / |recipe_uniq|)
      cover: float           -> fraction of pantry covered by recipe      (|hits| / |pantry_uniq|)  [matches your old semantics]
    """
    # normalize recipe ingredients
    recipe_norm_map = {}
    for ing in recipe_ingredients or []:
        n = _norm_text(ing)
        if not n:
            continue
        # keep first original text we saw for UI chip text
        recipe_norm_map.setdefault(n, ing)

    recipe_uniq = set(recipe_norm_map.keys())
    if not recipe_uniq:
        return ([], 0.0, 0.0)

    hits_norm = sorted(recipe_uniq & pantry_terms)
    have_names = [recipe_norm_map[h] for h in hits_norm]

    overlap = len(hits_norm) / max(1, len(recipe_uniq))
    cover   = len(hits_norm) / max(1, len(pantry_terms))
    return (have_names, round(overlap, 2), round(cover, 2))
