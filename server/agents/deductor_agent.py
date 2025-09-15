from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
import json, re

# Load once
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

# Prompt template
prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a helpful ingredient parsing assistant. "
               "Extract structured fields from messy ingredient lines."),
    ("human", "Line: {line}\n\nReturn JSON with keys: name, qty, unit. "
              "If qty missing, set null. If unit missing, set null.")
])

def parse_with_agent(line: str) -> dict:
    """Agent parses ingredient lines into structured JSON"""
    try:
        response = (prompt | llm).invoke({"line": line})
        text = response.content.strip()

        # Extract first JSON-looking substring
        m = re.search(r"\{.*\}", text, flags=re.S)
        if not m:
            return {"name": line, "qty": None, "unit": None}

        return json.loads(m.group(0))
    except Exception as e:
        print("[Agent Parse Error]", e)
        return {"name": line, "qty": None, "unit": None}
