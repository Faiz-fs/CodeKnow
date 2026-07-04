"""Apply Alembic migrations programmatically (used on app startup)."""

from __future__ import annotations

import logging
from pathlib import Path
import asyncio

from alembic import command
from alembic.config import Config

from app.config import get_settings

logger = logging.getLogger(__name__)


async def upgrade_db_schema() -> None:
    """Run `alembic upgrade head` using DATABASE_URL from settings."""
    settings = get_settings()
    backend_dir = Path(__file__).resolve().parent.parent
    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)
    try:
        await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
    except Exception:
        logger.exception(
            "Failed to apply database migrations on startup. "
            "Run `alembic upgrade head` manually. "
            "If migration 0003 fails, run the cleanup SQL documented in "
            "alembic/versions/0003_uq_user_repo.py first."
        )
    logger.info("Database schema is at Alembic head")
