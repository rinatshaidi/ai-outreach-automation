"""Create Mini-CRM core tables.

Revision ID: 20260801_0003
Revises: 20260801_0002
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260801_0003"
down_revision: str | None = "20260801_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _record_columns() -> list[sa.Column[object]]:
    return [
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("normalized_domain", sa.String(length=253), nullable=False),
        sa.Column("country", sa.String(length=120), nullable=True),
        sa.Column("industry", sa.String(length=160), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "language_signals",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("relevance_score", sa.Float(), nullable=True),
        sa.Column(
            "relevance_status", sa.String(length=30), server_default="unscored", nullable=False
        ),
        sa.Column("pipeline_status", sa.String(length=40), server_default="new", nullable=False),
        sa.Column("next_action", sa.String(length=240), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("last_researched_at", sa.DateTime(timezone=True), nullable=True),
        *_record_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_domain"),
    )
    op.create_index(op.f("ix_companies_name"), "companies", ["name"])
    op.create_index(op.f("ix_companies_pipeline_status"), "companies", ["pipeline_status"])

    op.create_table(
        "campaigns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column(
            "criteria",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "preferred_language", sa.String(length=20), server_default="auto", nullable=False
        ),
        sa.Column(
            "tone_defaults", sa.String(length=40), server_default="professional", nullable=False
        ),
        sa.Column("daily_limit", sa.Integer(), server_default="10", nullable=False),
        sa.Column(
            "followup_policy",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=30), server_default="draft", nullable=False),
        *_record_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_campaigns_status"), "campaigns", ["status"])

    op.create_table(
        "contacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=200), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("telegram", sa.String(length=160), nullable=True),
        sa.Column("linkedin", sa.Text(), nullable=True),
        sa.Column("other_public_link", sa.Text(), nullable=True),
        sa.Column(
            "verification_status", sa.String(length=30), server_default="unverified", nullable=False
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("lawful_public_source_note", sa.Text(), nullable=True),
        sa.Column("do_not_contact", sa.Boolean(), server_default=sa.false(), nullable=False),
        *_record_columns(),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "email", name="uq_contacts_company_email"),
    )
    op.create_index(op.f("ix_contacts_company_id"), "contacts", ["company_id"])
    op.create_index(op.f("ix_contacts_verification_status"), "contacts", ["verification_status"])

    op.create_table(
        "job_openings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "required_skills",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_record_columns(),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_job_openings_active"), "job_openings", ["active"])
    op.create_index(op.f("ix_job_openings_company_id"), "job_openings", ["company_id"])

    op.create_table(
        "communication_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_communication_events_company_id"), "communication_events", ["company_id"]
    )
    op.create_index(
        op.f("ix_communication_events_contact_id"), "communication_events", ["contact_id"]
    )
    op.create_index(
        op.f("ix_communication_events_event_type"), "communication_events", ["event_type"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_communication_events_event_type"), table_name="communication_events")
    op.drop_index(op.f("ix_communication_events_contact_id"), table_name="communication_events")
    op.drop_index(op.f("ix_communication_events_company_id"), table_name="communication_events")
    op.drop_table("communication_events")
    op.drop_index(op.f("ix_job_openings_company_id"), table_name="job_openings")
    op.drop_index(op.f("ix_job_openings_active"), table_name="job_openings")
    op.drop_table("job_openings")
    op.drop_index(op.f("ix_contacts_verification_status"), table_name="contacts")
    op.drop_index(op.f("ix_contacts_company_id"), table_name="contacts")
    op.drop_table("contacts")
    op.drop_index(op.f("ix_campaigns_status"), table_name="campaigns")
    op.drop_table("campaigns")
    op.drop_index(op.f("ix_companies_pipeline_status"), table_name="companies")
    op.drop_index(op.f("ix_companies_name"), table_name="companies")
    op.drop_table("companies")
