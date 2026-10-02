"""Add immutable owner overrides for deterministic opportunity assessments.

Revision ID: 20260801_0007
Revises: 20260801_0006
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260801_0007"
down_revision: str | None = "20260801_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "opportunity_assessment_overrides",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("original_score", sa.Float(), nullable=False),
        sa.Column("overridden_score", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["assessment_id"], ["opportunity_assessments.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_opportunity_assessment_overrides_company_id"),
        "opportunity_assessment_overrides",
        ["company_id"],
    )
    op.create_index(
        op.f("ix_opportunity_assessment_overrides_assessment_id"),
        "opportunity_assessment_overrides",
        ["assessment_id"],
    )


def downgrade() -> None:
    op.drop_table("opportunity_assessment_overrides")
