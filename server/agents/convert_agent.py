from services.pantry_rules import normalize_rules, parse_line, NormResult, ureg, Q_
from agents.llm import get_chat
import re

def to_pantry_unit_with_rules_then_llm(name: str, qty: float, from_unit: str, to_unit: str) -> float | None:
    # If units are same → done
    if (from_unit or "").lower() == (to_unit or "").lower():
        return float(qty)
    # Try Pint conversion directly
    try:
        q = Q_(qty, from_unit)
        t = float(q.to(to_unit).magnitude)
        return t
    except Exception:
        pass
    # Last resort: ask LLM for a number only
    llm = get_chat()
    msg = f"Convert quantity using typical culinary density assumptions.\nIngredient: {name}\nFrom: {qty} {from_unit}\nTo: {to_unit}\nReturn ONLY a number."
    text = llm.invoke(msg).content
    m = re.search(r"-?\d+(?:\.\d+)?", text or "")
    try:
        return float(m.group(0)) if m else None
    except Exception:
        return None
