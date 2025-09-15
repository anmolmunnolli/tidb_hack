# server/app (or a shared db.py)
import os, pymysql
from pymysql.cursors import DictCursor

DB_CFG = dict(
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT", "4000")),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    database=os.getenv("DB_DATABASE"),
    cursorclass=DictCursor,
    autocommit=False,  # we'll control commits explicitly
    ssl={"ssl": {}},
)

def get_conn():
    conn = pymysql.connect(**DB_CFG)
    with conn.cursor() as cur:
        cur.execute("SELECT DATABASE() AS db")
        row = cur.fetchone()
        print(f"[DB] Connected to database={row['db']}")
    return conn

# server/db.py  (add this near your other helpers)
from typing import List, Tuple, Set
import re

_WORD = re.compile(r"[a-zA-Z]+")
def _norm_text(s: str) -> str:
    # very close to what your main.py did: lowercase + keep letters only
    return " ".join(_WORD.findall((s or "").lower()))

def get_user_pantry_names(conn, user_id: int) -> Set[str]:
    """
    Returns a set of normalized pantry ingredient names for the user,
    excluding expired or zero-quantity items.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT name
            FROM pantry_items
            WHERE user_id = %s
              AND (expires_on IS NULL OR expires_on >= CURRENT_DATE())
              AND COALESCE(qty,0) > 0
            """,
            (user_id,),
        )
        rows = [r[0] for r in cur.fetchall()]
    return {_norm_text(r) for r in rows if r}

# server/db.py
import os, pymysql
from dotenv import load_dotenv
load_dotenv()

DB_CFG = dict(
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT", "4000")),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    database=os.getenv("DB_DATABASE"),
    ssl={"ssl": {}},  # OK for TiDB Cloud and local TiDB
    cursorclass=pymysql.cursors.DictCursor,
)

def get_conn():
    return pymysql.connect(**DB_CFG)
