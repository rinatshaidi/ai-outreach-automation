"""Add isolated owner manual search tasks and result linkage.

Revision ID: 20260808_0016
Revises: 20260808_0015
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260808_0016"
down_revision: str | None = "20260808_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "search_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("original_query", sa.Text(), nullable=False),
        sa.Column("query_language", sa.String(length=16), nullable=False, server_default="unknown"),
        sa.Column("task_type", sa.String(length=40), nullable=False),
        sa.Column("parsed_country", sa.String(length=120)),
        sa.Column("parsed_region", sa.String(length=160)),
        sa.Column("parsed_industry", sa.String(length=160)),
        sa.Column("parsed_focus", sa.String(length=200)),
        sa.Column("company_name_or_url", sa.Text()),
        sa.Column("result_limit", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="QUEUED"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("found_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("accepted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_search_tasks_owner_id", "search_tasks", ["owner_id"])
    op.create_index("ix_search_tasks_status", "search_tasks", ["status"])
    op.create_index("ix_search_tasks_task_type", "search_tasks", ["task_type"])
    op.create_table(
        "search_task_results",
        sa.Column("search_task_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["search_task_id"], ["search_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("search_task_id", "company_id"),
        sa.UniqueConstraint("search_task_id", "company_id", name="uq_search_task_result_company"),
    )
    op.create_index("ix_search_task_results_company_id", "search_task_results", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_search_task_results_company_id", table_name="search_task_results")
    op.drop_table("search_task_results")
    op.drop_index("ix_search_tasks_task_type", table_name="search_tasks")
    op.drop_index("ix_search_tasks_status", table_name="search_tasks")
    op.drop_index("ix_search_tasks_owner_id", table_name="search_tasks")
    op.drop_table("search_tasks")
