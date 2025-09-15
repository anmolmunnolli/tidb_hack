# server/app.py
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from routes import recommend_routes
from routes import auth_routes, pantry_routes, recipe_routes, mealplan_routes, mealplan_cook_routes # keep yours if present

app = FastAPI(title="Recipe API (Agentic)")
# Allow frontend origin (8081)
origins = [
    "http://localhost:8081",  # frontend dev server
    "http://127.0.0.1:8081",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # or ["*"] to allow all
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    print("REQ", request.method, request.url)
    resp = await call_next(request)
    print("RES", resp.status_code)
    return resp

# mount routes
app.include_router(recommend_routes.router)
app.include_router(auth_routes.router)
app.include_router(pantry_routes.router)
app.include_router(recipe_routes.router)
app.include_router(mealplan_routes.router)
app.include_router(mealplan_cook_routes.router)

@app.get("/healthz")
def healthz(): return {"ok": True}
