"""Add unique constraint on repo_analyses (user_id, repo_full_name)

Revision ID: 0003_uq_user_repo
Revises: 0002_graph
Create Date: 2026-07-04

BEFORE running this migration, operators must manually run against existing data:
    UPDATE repo_analyses SET repo_full_name = LOWER(repo_full_name);
    DELETE FROM repo_analyses a USING repo_analyses b
    WHERE a.user_id = b.user_id AND a.repo_full_name = b.repo_full_name
    AND a.analyzed_at < b.analyzed_at;
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003_uq_user_repo"
down_revision: Union[str, None] = "0002_graph"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_user_repo", "repo_analyses", ["user_id", "repo_full_name"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_user_repo", "repo_analyses", type_="unique")
