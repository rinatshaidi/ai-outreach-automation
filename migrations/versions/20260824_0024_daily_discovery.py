"""Persist source and scheduled day for automatic daily discovery.

Revision ID: 20260824_0024
Revises: 20260818_0023
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0024"
down_revision: str | None = "20260818_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "search_tasks",
        sa.Column("source", sa.String(length=20), nullable=False, server_default="manual"),
    )
    op.add_column("search_tasks", sa.Column("scheduled_for_date", sa.Date(), nullable=True))
    op.create_index("ix_search_tasks_source", "search_tasks", ["source"])
    op.create_index(
        "ix_search_tasks_scheduled_for_date", "search_tasks", ["scheduled_for_date"]
    )
    op.create_unique_constraint(
        "uq_search_task_daily_owner_date",
        "search_tasks",
        ["owner_id", "source", "scheduled_for_date"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_search_task_daily_owner_date", "search_tasks", type_="unique")
    op.drop_index("ix_search_tasks_scheduled_for_date", table_name="search_tasks")
    op.drop_index("ix_search_tasks_source", table_name="search_tasks")
    op.drop_column("search_tasks", "scheduled_for_date")
    op.drop_column("search_tasks", "source")
