"""Health check endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/health/detailed")
async def health_detailed(db: AsyncSession = Depends(get_db)):
    """Detailed health check with dependency verification."""
    settings = get_settings()
    checks: dict[str, str] = {}
    status = "ok"

    # Check database
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {str(e)[:100]}"
        status = "degraded"

    # Check GitHub OAuth configuration
    if settings.github_client_id:
        checks["github_oauth"] = "ok"
    else:
        checks["github_oauth"] = "not configured"
        status = "degraded"

    return {
        "status": status,
        "version": "0.1.0",
        "checks": checks,
    }
