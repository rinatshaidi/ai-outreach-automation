"""Add safe research runs, company facts and explicit task hypotheses.

Revision ID: 20260801_0006
Revises: 20260801_0005
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260801_0006"
down_revision: str | None = "20260801_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_list_column(name: str) -> sa.Column[object]:
    return sa.Column(
        name,
        postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text("'[]'::jsonb"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "company_facts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("fact_type", sa.String(length=80), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("exact_fragment", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="extracted", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["company_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_company_facts_company_id"), "company_facts", ["company_id"])
    op.create_index(op.f("ix_company_facts_source_id"), "company_facts", ["source_id"])
    op.create_index(op.f("ix_company_facts_fact_type"), "company_facts", ["fact_type"])
    op.create_index(op.f("ix_company_facts_status"), "company_facts", ["status"])

    op.create_table(
        "company_task_hypotheses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        _json_list_column("source_ids"),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="hypothesis", nullable=False),
        _json_list_column("risks"),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_company_task_hypotheses_company_id"),
        "company_task_hypotheses",
        ["company_id"],
    )
    op.create_index(
        op.f("ix_company_task_hypotheses_status"),
        "company_task_hypotheses",
        ["status"],
    )

    op.create_table(
        "research_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("requested_url", sa.Text(), nullable=False),
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Uuid()),
        sa.Column("status", sa.String(length=30), server_default="pending", nullable=False),
        sa.Column("content_type", sa.String(length=120)),
        sa.Column("content_bytes", sa.Integer()),
        sa.Column("language", sa.String(length=20)),
        _json_list_column("redirect_chain"),
        sa.Column(
            "result_summary",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=80)),
        sa.Column("error_message", sa.String(length=500)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["company_sources.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_research_runs_company_id"), "research_runs", ["company_id"])
    op.create_index(op.f("ix_research_runs_source_id"), "research_runs", ["source_id"])
    op.create_index(op.f("ix_research_runs_status"), "research_runs", ["status"])


def downgrade() -> None:
    op.drop_table("research_runs")
    op.drop_table("company_task_hypotheses")
    op.drop_table("company_facts")
