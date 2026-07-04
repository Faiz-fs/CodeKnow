"""Add Knowledge Graph tables: graph_nodes, graph_edges

Revision ID: 0002_graph
Revises: 0001_initial
Create Date: 2026-07-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_graph"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "graph_nodes",
        sa.Column("id", postgresql.UUID(), nullable=False),
        sa.Column("repo_analysis_id", postgresql.UUID(), nullable=False),
        sa.Column("node_type", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["repo_analysis_id"], ["repo_analyses.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "repo_analysis_id", "node_type", "path", name="uq_node_per_analysis"
        ),
    )
    op.create_index("ix_graph_nodes_repo_analysis_id", "graph_nodes", ["repo_analysis_id"])
    op.create_index("ix_graph_nodes_node_type", "graph_nodes", ["node_type"])

    op.create_table(
        "graph_edges",
        sa.Column("id", postgresql.UUID(), nullable=False),
        sa.Column("repo_analysis_id", postgresql.UUID(), nullable=False),
        sa.Column("source_node_id", postgresql.UUID(), nullable=False),
        sa.Column("target_node_id", postgresql.UUID(), nullable=False),
        sa.Column("edge_type", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["repo_analysis_id"], ["repo_analyses.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_node_id"], ["graph_nodes.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_node_id"], ["graph_nodes.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_graph_edges_repo_analysis_id", "graph_edges", ["repo_analysis_id"])
    op.create_index("ix_graph_edges_source_node_id", "graph_edges", ["source_node_id"])
    op.create_index("ix_graph_edges_target_node_id", "graph_edges", ["target_node_id"])


def downgrade() -> None:
    op.drop_index("ix_graph_edges_target_node_id", table_name="graph_edges")
    op.drop_index("ix_graph_edges_source_node_id", table_name="graph_edges")
    op.drop_index("ix_graph_edges_repo_analysis_id", table_name="graph_edges")
    op.drop_table("graph_edges")
    op.drop_index("ix_graph_nodes_node_type", table_name="graph_nodes")
    op.drop_index("ix_graph_nodes_repo_analysis_id", table_name="graph_nodes")
    op.drop_table("graph_nodes")