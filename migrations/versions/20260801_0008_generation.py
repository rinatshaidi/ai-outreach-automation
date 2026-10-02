"""Add privacy-safe generation runs and immutable A/B message drafts.

Revision ID: 20260801_0008
Revises: 20260801_0007
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260801_0008"
down_revision: str | None = "20260801_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "generation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("prompt_version", sa.String(length=80), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False),
        sa.Column("input_entity_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("validation_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["assessment_id"], ["opportunity_assessments.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["recommendation_id"], ["positioning_recommendations.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    run_indexes = (
        "company_id",
        "contact_id",
        "recommendation_id",
        "assessment_id",
        "status",
        "created_at",
    )
    for column in run_indexes:
        op.create_index(op.f(f"ix_generation_runs_{column}"), "generation_runs", [column])

    op.create_table(
        "message_drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("generation_run_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("variant", sa.String(length=20), nullable=False),
        sa.Column("tone", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("subject", sa.String(length=240), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=20), nullable=False),
        sa.Column("language_confidence", sa.Float(), nullable=False),
        sa.Column("language_reason", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("opportunity_type_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "opportunity_signal_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("positioning_strategy", sa.String(length=40), nullable=False),
        sa.Column("collaboration_format", sa.String(length=60), nullable=False),
        sa.Column("value_proposition", sa.Text(), nullable=False),
        sa.Column("candidate_fact_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("company_fact_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("validation_report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("prompt_version", sa.String(length=80), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["assessment_id"], ["opportunity_assessments.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["generation_run_id"], ["generation_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["recommendation_id"], ["positioning_recommendations.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("generation_run_id", "variant", name="uq_message_draft_run_variant"),
    )
    for column in ("generation_run_id", "company_id", "contact_id", "status", "created_at"):
        op.create_index(op.f(f"ix_message_drafts_{column}"), "message_drafts", [column])


def downgrade() -> None:
    op.drop_table("message_drafts")
    op.drop_table("generation_runs")
