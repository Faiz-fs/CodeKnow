"""SQLAlchemy models for the Knowledge Graph — nodes and edges."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

import enum


class NodeType(str, enum.Enum):
    file = "file"
    function = "function"
    api_route = "api_route"
    db_table = "db_table"


class EdgeType(str, enum.Enum):
    imports = "imports"
    calls = "calls"
    writes_to = "writes_to"
    reads_from = "reads_from"


class GraphNode(Base):
    __tablename__ = "graph_nodes"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    repo_analysis_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("repo_analyses.id", ondelete="CASCADE"),
        index=True,
    )
    node_type: Mapped[str] = mapped_column(String(50))  # NodeType values
    name: Mapped[str] = mapped_column(String(512))
    path: Mapped[str] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint("repo_analysis_id", "node_type", "path", name="uq_node_per_analysis"),
    )


class GraphEdge(Base):
    __tablename__ = "graph_edges"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    repo_analysis_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("repo_analyses.id", ondelete="CASCADE"),
        index=True,
    )
    source_node_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("graph_nodes.id", ondelete="CASCADE"),
        index=True,
    )
    target_node_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("graph_nodes.id", ondelete="CASCADE"),
        index=True,
    )
    edge_type: Mapped[str] = mapped_column(String(50))  # EdgeType values
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )