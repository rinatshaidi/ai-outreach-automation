"""Add durable Search Task executor progress and failure state.

Revision ID: 20260808_0017
Revises: 20260808_0016
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260808_0017"
down_revision: str | None = "20260808_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("search_tasks", sa.Column("current_stage", sa.String(length=80)))
    op.add_column("search_tasks", sa.Column("failure_code", sa.String(length=80)))
    op.add_column("search_tasks", sa.Column("failure_reason", sa.Text()))
    op.add_column(
        "search_tasks",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("search_tasks", "attempt_count")
    op.drop_column("search_tasks", "failure_reason")
    op.drop_column("search_tasks", "failure_code")
    op.drop_column("search_tasks", "current_stage")
