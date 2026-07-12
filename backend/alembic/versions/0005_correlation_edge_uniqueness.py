"""Correlation Layer: add unique constraint to graph_edges for edge uniqueness

Revision ID: 0005_correlation_edge_uniqueness
Revises: 0004_correlation_layer
Create Date: 2026-07-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_correlation_edge_uniqueness"
down_revision: Union[str, None] = "0004_correlation_layer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_graph_edges_per_analysis",
        "graph_edges",
        ["repo_analysis_id", "source_node_id", "target_node_id", "edge_type"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_graph_edges_per_analysis", "graph_edges", type_="unique"
    )