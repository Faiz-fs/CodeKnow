"""Correlation Layer (Engine 3): add weight to graph_edges, create node_risk_scores

Revision ID: 0004_correlation_layer
Revises: 0003_uq_user_repo
Create Date: 2026-07-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0004_correlation_layer"
down_revision: Union[str, None] = "0003_uq_user_repo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add weight column to graph_edges with default 1.0
    op.add_column(
        "graph_edges",
        sa.Column("weight", sa.Float(), nullable=False, server_default=sa.text("1.0")),
    )

    # Create node_risk_scores table
    op.create_table(
        "node_risk_scores",
        sa.Column("id", postgresql.UUID(), nullable=False),
        sa.Column("repo_analysis_id", postgresql.UUID(), nullable=False),
        sa.Column("node_id", postgresql.UUID(), nullable=False),
        sa.Column("blast_radius_score", sa.Float(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["repo_analysis_id"],
            ["repo_analyses.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["graph_nodes.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "repo_analysis_id", "node_id", name="uq_node_risk_per_analysis"
        ),
    )
    op.create_index(
        "ix_node_risk_scores_repo_analysis_id",
        "node_risk_scores",
        ["repo_analysis_id"],
    )
    op.create_index(
        "ix_node_risk_scores_node_id",
        "node_risk_scores",
        ["node_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_node_risk_scores_node_id", table_name="node_risk_scores")
    op.drop_index("ix_node_risk_scores_repo_analysis_id", table_name="node_risk_scores")
    op.drop_table("node_risk_scores")
    op.drop_column("graph_edges", "weight")