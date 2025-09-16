# server/models.py
from typing import List, Literal, Optional
from pydantic import BaseModel, condecimal

class RecommendIn(BaseModel):
    query: str
    k: int = 5
    m: int = 50
    w1_query: float = 0.70
    w2_overlap: float = 0.20
    w3_cover: float = 0.10
    min_cover: float | None = None

class PantryOut(BaseModel):
    id: int
    name: str
    qty: Optional[float] = None
    unit: Optional[str] = None
    expires_on: Optional[str] = None
    added_at: Optional[str] = None

    # NEW optional fields (must exist to pass through)
    canonical_name: Optional[str] = None
    norm_qty: Optional[float] = None
    norm_unit: Optional[str] = None
    norm_conf: Optional[float] = None
    norm_source: Optional[str] = None

class PantryIn(BaseModel):
    name: str
    qty: Optional[condecimal(max_digits=10, decimal_places=2)] = None
    unit: Optional[str] = None
    # keep as string (YYYY-MM-DD) so the existing frontend doesn't need changes
    expires_on: Optional[str] = None

class RecItem(BaseModel):
    id: str
    title: str | None = None
    dist: float
    query_score: float | None = None
    overlap_score: float | None = None
    cover_score: float | None = None
    final: float | None = None
    used_from_pantry: List[str] | None = None
    missing: List[str] | None = None
    # optional: uncomment to drive green highlighting per ingredient
    # tags: List[dict] | None = None

class RecommendOut(BaseModel):
    items: List[RecItem]
