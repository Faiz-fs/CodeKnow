"""RepoAnalysis model — persists analysis results."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class RepoAnalysis(Base):
    __tablename__ = "repo_analyses"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    repo_full_name: Mapped[str] = mapped_column(String(512), index=True)
    platform: Mapped[str] = mapped_column(String(50), default="github")
    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    raw_result: Mapped[dict] = mapped_column(JSONB)

    __table_args__ = (
        UniqueConstraint("user_id", "repo_full_name", name="uq_user_repo"),
    )
