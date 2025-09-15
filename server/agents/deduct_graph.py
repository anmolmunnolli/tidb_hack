from typing import Dict, Any, List
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from agents.normalizer_agent import normalize_line_llm
from agents.match_agent import best_match_substring_first
from agents.convert_agent import to_pantry_unit_with_rules_then_llm
from services.pantry_rules import normalize_rules, parse_line
from db import get_conn

# State
class S(dict): pass

def load_plan(state: S) -> S:
    plan_id, uid = state["plan_id"], state["user_id"]
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""SELECT id, recipe_id, title, ingredients, directions, servings
                       FROM meal_plan WHERE id=%s AND user_id=%s LIMIT 1""", (plan_id, uid))
        row = cur.fetchone()
        if not row: raise ValueError("Meal plan not found")
        state["plan"] = row
    return state

def load_pantry(state: S) -> S:
    uid = state["user_id"]
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""SELECT id, name, canonical_name, norm_qty, norm_unit
                       FROM pantry_items WHERE user_id=%s ORDER BY id ASC""", (uid,))
        rows = cur.fetchall() or []
    state["pantry_rows"] = rows
    state["pantry_names"] = [(r.get("canonical_name") or r.get("name") or "").strip() for r in rows]
    return state

def plan_ingredients(state: S) -> S:
    import json, re
    raw = state["plan"].get("ingredients")
    if raw is None: ings = []
    else:
        if isinstance(raw, (list,tuple)): ings = [str(x) for x in raw]
        else:
            try:
                j = json.loads(raw)
                ings = j if isinstance(j,list) else [str(raw)]
            except Exception:
                parts = re.split(r"(?:\r?\n|\.\s+|;|,)", str(raw))
                ings = [p.strip() for p in parts if p.strip()]
    state["ing_lines"] = ings
    return state

def compute_scale(state: S) -> S:
    planned = int(state["plan"].get("servings") or 1)
    used = int(state.get("servings") or planned or 1)
    state["servings_used"] = used
    state["scale"] = (used / planned) if planned else 1.0
    return state

def normalize_needs(state: S) -> S:
    needs, unmatched = [], []
    scale = state["scale"]
    with get_conn() as conn:
        for raw in state["ing_lines"]:
            # LLM normalize line
            norm = normalize_line_llm(raw)
            qty, unit = norm.qty, norm.unit
            if qty is None or unit is None:
                unmatched.append({"original_line": raw}); continue
            qty_scaled = float(qty) * scale
            # Rules-based canonical base unit (g/ml/count) using your tables/pint
            res = normalize_rules(norm.name, qty_scaled, unit, conn)
            if res.norm_qty is None or not res.norm_unit:
                unmatched.append({"original_line": raw}); continue
            needs.append({"canonical_name": res.canonical_name,
                          "unit": res.norm_unit, "qty": float(res.norm_qty), "raw": raw})
    state["needs"] = needs
    state["unmatched"] = unmatched
    return state

def match_and_deduct(state: S) -> S:
    uid = state["user_id"]
    rows = state["pantry_rows"]
    names = state["pantry_names"]
    needs = state["needs"]
    dry = bool(state.get("dry_run"))

    deducted, shortages = [], []
    if not dry:
        conn = get_conn(); conn.begin(); cur = conn.cursor()
    else:
        conn = None; cur = None

    try:
        for need in needs:
            ing_name = need["canonical_name"]
            idx, conf = best_match_substring_first(ing_name, names)
            if idx < 0 or conf < 0.55:
                shortages.append({"canonical_name": ing_name, "unit": need["unit"],
                                  "amount_short": float(need["qty"]), "reason": "no matching pantry item"})
                continue
            pr = rows[idx]
            p_qty, p_unit = pr.get("norm_qty"), pr.get("norm_unit")
            if p_qty is None or p_unit is None:
                shortages.append({"canonical_name": ing_name, "reason":"pantry item missing normalized qty/unit"}); continue
            # convert need to pantry unit
            need_in_pu = to_pantry_unit_with_rules_then_llm(ing_name, need["qty"], need["unit"], p_unit)
            if need_in_pu is None:
                shortages.append({"canonical_name": ing_name, "reason":"cannot convert units"}); continue
            if float(p_qty) >= float(need_in_pu):
                new_qty = float(p_qty) - float(need_in_pu)
                if not dry:
                    cur.execute("UPDATE pantry_items SET norm_qty=%s WHERE id=%s AND user_id=%s",
                                (new_qty, pr["id"], uid))
                deducted.append({
                    "pantry_item_id": int(pr["id"]),
                    "canonical_name": ing_name,
                    "unit": p_unit,
                    "amount_used": float(need_in_pu),
                    "remaining": float(new_qty),
                    "match_conf": round(conf, 2),
                })
            else:
                diff = float(need_in_pu) - float(p_qty)
                shortages.append({
                    "canonical_name": ing_name,
                    "unit": p_unit,
                    "amount_short": float(diff),
                    "matched_pantry": (pr.get("canonical_name") or pr.get("name") or "").strip(),
                    "match_conf": round(conf, 2),
                })
        if not dry and conn: conn.commit()
    finally:
        if cur: cur.close()
        if conn: conn.close()

    state["deducted"] = deducted
    state["shortages"] = shortages
    return state

# Build the graph
def build_graph():
    g = StateGraph(S)
    g.add_node("load_plan", load_plan)
    g.add_node("load_pantry", load_pantry)
    g.add_node("plan_ingredients", plan_ingredients)
    g.add_node("compute_scale", compute_scale)
    g.add_node("normalize_needs", normalize_needs)
    g.add_node("match_and_deduct", match_and_deduct)

    g.set_entry_point("load_plan")
    g.add_edge("load_plan", "load_pantry")
    g.add_edge("load_pantry", "plan_ingredients")
    g.add_edge("plan_ingredients", "compute_scale")
    g.add_edge("compute_scale", "normalize_needs")
    g.add_edge("normalize_needs", "match_and_deduct")
    g.add_edge("match_and_deduct", END)

    return g.compile(checkpointer=MemorySaver())

graph = build_graph()

def run_deduct(user_id: int, plan_id: int, servings: int | None, dry_run: bool = False):
    state = {"user_id": user_id, "plan_id": plan_id, "servings": servings, "dry_run": dry_run}
    out = graph.invoke(state)
    return {
        "plan_id": plan_id,
        "servings_used": int(out["servings_used"]),
        "deducted": out["deducted"],
        "shortages": out["shortages"],
        "unmatched": out["unmatched"],
        "notes": None,
    }
