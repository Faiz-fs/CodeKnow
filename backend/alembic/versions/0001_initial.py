"""Initial schema: users, repo_analyses

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("github_id", sa.BigInteger(), nullable=True),
        sa.Column("github_access_token_encrypted", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_github_id"), "users", ["github_id"], unique=True)

    op.create_table(
        "repo_analyses",
        sa.Column("id", postgresql.UUID(), nullable=False),
        sa.Column("user_id", postgresql.UUID(), nullable=False),
        sa.Column("repo_full_name", sa.String(length=512), nullable=False),
        sa.Column("platform", sa.String(length=50), nullable=False, server_default="github"),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_repo_analyses_repo_full_name"), "repo_analyses", ["repo_full_name"])
    op.create_index(op.f("ix_repo_analyses_user_id"), "repo_analyses", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_repo_analyses_user_id"), table_name="repo_analyses")
    op.drop_index(op.f("ix_repo_analyses_repo_full_name"), table_name="repo_analyses")
    op.drop_table("repo_analyses")
    op.drop_index(op.f("ix_users_github_id"), table_name="users")
    op.drop_table("users")
