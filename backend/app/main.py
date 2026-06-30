"""CodeKnow FastAPI application entrypoint."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import analyze, auth, health

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

app.include_router(health.router)
app.include_router(auth.router, prefix="/auth")
app.include_router(analyze.router, prefix="/analyze")


@app.get("/")
def root():
    return {"service": "CodeKnow", "version": "0.1.0", "docs": "/docs"}
