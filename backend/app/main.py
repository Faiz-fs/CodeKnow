"""CodeKnow FastAPI application entrypoint."""

from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import analyze, auth, github, health

settings = get_settings()

app = FastAPI(
    title="CodeKnow",
    description="Codebase intelligence & knowledge-retention platform.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/codeknow"

api_route = APIRouter(prefix=API_PREFIX)
api_route.include_router(health.router)
api_route.include_router(auth.router, prefix="/auth")
api_route.include_router(analyze.router, prefix="/analyze")
api_route.include_router(github.router, prefix="/github")

app.include_router(api_route)


@app.get("/")
def root():
    return {"service": "CodeKnow", "version": "0.1.0", "docs": "/docs"}
