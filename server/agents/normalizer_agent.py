# server/agents/normalizer_agent.py

from pydantic import BaseModel, Field
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from agents.llm import get_chat

class NormalizedLine(BaseModel):
    name: str = Field(description="canonical ingredient name, lowercase")
    qty: float | None = Field(default=None, description="numeric quantity if present")
    unit: str | None = Field(default=None, description="unit like g, ml, cup, tbsp, tsp, count")

SYSTEM = """You normalize a single recipe ingredient line.
Rules:
- Prefer units from this small set: ["g","ml","cup","tbsp","tsp","count"].
- Use "g" for solids, "ml" for liquids, "count" for discrete items (eggs, cloves).
- If the amount is missing, set qty=null and unit=null.
- Lowercase the name. Keep it short and canonical (e.g., "granulated sugar" -> "sugar").
Return ONLY a single JSON object that conforms to the schema {{"name": str, "qty": number|null, "unit": str|null}}.
"""

PROMPT = PromptTemplate.from_template(
    SYSTEM + "\n\nLine: {line}\nJSON:"
)

parser = JsonOutputParser(pydantic_object=NormalizedLine)

def normalize_line_llm(line: str) -> NormalizedLine:
    llm = get_chat()
    # PROMPT -> LLM -> JSON (dict or pydantic) -> NormalizedLine
    try:
        parsed = (PROMPT | llm | parser).invoke({"line": line})
        # parser may already return a pydantic object, but be defensive:
        if isinstance(parsed, NormalizedLine):
            return parsed
        if isinstance(parsed, dict):
            return NormalizedLine(**parsed)
        # fallback
        return NormalizedLine(name=str(line).lower().strip(), qty=None, unit=None)
    except Exception:
        return NormalizedLine(name=str(line).lower().strip(), qty=None, unit=None)
