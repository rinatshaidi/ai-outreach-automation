"""Add evidence qualification and company decision synthesis.

Revision ID: 20260814_0022
Revises: 20260812_0021
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260814_0022"
down_revision: str | None = "20260812_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column(
            "identity_verification_status",
            sa.String(40),
            nullable=False,
            server_default="unconfirmed",
        ),
    )
    op.add_column("companies", sa.Column("identity_source_id", sa.Uuid()))
    op.add_column(
        "companies",
        sa.Column(
            "geography_verification_status",
            sa.String(40),
            nullable=False,
            server_default="unconfirmed",
        ),
    )
    op.add_column("companies", sa.Column("geography_source_id", sa.Uuid()))
    op.create_index(
        "ix_companies_identity_verification_status",
        "companies",
        ["identity_verification_status"],
    )
    op.create_index("ix_companies_identity_source_id", "companies", ["identity_source_id"])
    op.create_index(
        "ix_companies_geography_verification_status",
        "companies",
        ["geography_verification_status"],
    )
    op.create_index("ix_companies_geography_source_id", "companies", ["geography_source_id"])
    op.create_foreign_key(
        "fk_companies_identity_source",
        "companies",
        "company_sources",
        ["identity_source_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_companies_geography_source",
        "companies",
        "company_sources",
        ["geography_source_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "search_task_results",
        sa.Column(
            "qualification_status",
            sa.String(50),
            nullable=False,
            server_default="PENDING",
        ),
    )
    op.add_column("search_task_results", sa.Column("rejection_reason", sa.Text()))
    op.add_column(
        "search_task_results",
        sa.Column(
            "qualification_evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(
        "ix_search_task_results_qualification_status",
        "search_task_results",
        ["qualification_status"],
    )

    op.create_table(
        "company_decision_syntheses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("locale", sa.String(16), nullable=False, server_default="ru"),
        sa.Column("status", sa.String(30), nullable=False, server_default="ready"),
        sa.Column("recommendation", sa.String(40), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "source_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("provider", sa.String(80), nullable=False, server_default="deterministic"),
        sa.Column("error_message", sa.String(500)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "locale", name="uq_company_decision_synthesis_locale"),
    )
    op.create_index(
        "ix_company_decision_syntheses_company_id",
        "company_decision_syntheses",
        ["company_id"],
    )
    op.create_index(
        "ix_company_decision_syntheses_status",
        "company_decision_syntheses",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_company_decision_syntheses_status", table_name="company_decision_syntheses")
    op.drop_index(
        "ix_company_decision_syntheses_company_id", table_name="company_decision_syntheses"
    )
    op.drop_table("company_decision_syntheses")
    op.drop_index("ix_search_task_results_qualification_status", table_name="search_task_results")
    op.drop_column("search_task_results", "qualification_evidence")
    op.drop_column("search_task_results", "rejection_reason")
    op.drop_column("search_task_results", "qualification_status")
    op.drop_constraint("fk_companies_geography_source", "companies", type_="foreignkey")
    op.drop_constraint("fk_companies_identity_source", "companies", type_="foreignkey")
    op.drop_index("ix_companies_geography_source_id", table_name="companies")
    op.drop_index("ix_companies_geography_verification_status", table_name="companies")
    op.drop_index("ix_companies_identity_source_id", table_name="companies")
    op.drop_index("ix_companies_identity_verification_status", table_name="companies")
    op.drop_column("companies", "geography_source_id")
    op.drop_column("companies", "geography_verification_status")
    op.drop_column("companies", "identity_source_id")
    op.drop_column("companies", "identity_verification_status")
