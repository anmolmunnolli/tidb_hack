from pydantic import BaseModel, EmailStr, condecimal
from typing import Optional, List, Literal

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

class PlanCreate(BaseModel):
    recipe_id: str
    planned_for: str | None = None
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

class RecommendIn(BaseModel):
    query: str
    k: int = 5
    m: int = 50
    w1_query: float = 0.70
    w2_overlap: float = 0.20
    w3_cover: float = 0.10
    min_cover: float | None = None

class RecItem(BaseModel):
    id: str
    title: str | None = None
    dist: float
    query_score: float | None = None
    overlap_score: float | None = None
    cover_score: float | None = None
    final: float | None = None
    used_from_pantry: list[str] | None = None
    missing: list[str] | None = None

class RecommendOut(BaseModel):
    items: list[RecItem]

class DeductIn(BaseModel):
    servings: int | None = None
    dry_run: bool | None = False

class DeductOut(BaseModel):
    plan_id: int
    servings_used: int
    deducted: list[dict]
    shortages: list[dict]
    unmatched: list[dict]
    notes: str | None = None
