import os
from dotenv import load_dotenv
load_dotenv()

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret")
JWT_EXP_SECONDS = 7 * 24 * 3600

DB_CFG = dict(
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT", "4000")),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    database=os.getenv("DB_DATABASE"),
    ssl={"ssl": {}},
)

# vector table (unchanged)
REC_TABLE = os.getenv("DB_TABLE", "recipe.vector_db")

# LLM provider choices
# OLLAMA_* or HF_* envs decide which client we build in agents/llm.py
OLLAMA_HOST  = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", os.getenv("LLM_MODEL", "mistral"))
HF_TOKEN     = os.getenv("HUGGINGFACEHUB_API_TOKEN")
HF_MODEL     = os.getenv("HF_INSTRUCT_MODEL", "mistralai/Mixtral-8x7B-Instruct-v0.1")
