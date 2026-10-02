"""Create candidate profile, permissions and consent tables.

Revision ID: 20260801_0002
Revises: 20260731_0001
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260801_0002"
down_revision: str | None = "20260731_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _permission_columns() -> list[sa.Column[bool]]:
    return [
        sa.Column("store_private", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("use_for_ai_analysis", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("use_in_draft", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("send_externally", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("publish_publicly", sa.Boolean(), server_default=sa.false(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "candidate_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_key", sa.String(length=40), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=True),
        sa.Column("professional_title", sa.String(length=200), nullable=True),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "desired_roles",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "preferred_countries",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "work_formats",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("language_level", sa.String(length=80), nullable=True),
        sa.Column("profile_status", sa.String(length=30), server_default="draft", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_key"),
    )

    op.create_table(
        "consent_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("action_type", sa.String(length=80), nullable=False),
        sa.Column("data_scope", sa.String(length=80), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("destination", sa.String(length=240), nullable=True),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_consent_events_action_type"), "consent_events", ["action_type"])
    op.create_index(op.f("ix_consent_events_request_id"), "consent_events", ["request_id"])

    op.create_table(
        "candidate_facts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("fact_type", sa.String(length=60), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("source_link", sa.Text(), nullable=True),
        sa.Column("verified", sa.Boolean(), server_default=sa.false(), nullable=False),
        *_permission_columns(),
        sa.Column(
            "sensitivity_level",
            sa.String(length=30),
            server_default="private",
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["candidate_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_candidate_facts_profile_id"), "candidate_facts", ["profile_id"])

    op.create_table(
        "candidate_contacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("contact_type", sa.String(length=40), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("verified", sa.Boolean(), server_default=sa.false(), nullable=False),
        *_permission_columns(),
        sa.Column("allowed_in_signature", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["candidate_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_candidate_contacts_profile_id"), "candidate_contacts", ["profile_id"])

    op.create_table(
        "candidate_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("rule_type", sa.String(length=60), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=20), server_default="block", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="100", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["candidate_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_candidate_rules_profile_id"), "candidate_rules", ["profile_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_candidate_rules_profile_id"), table_name="candidate_rules")
    op.drop_table("candidate_rules")
    op.drop_index(op.f("ix_candidate_contacts_profile_id"), table_name="candidate_contacts")
    op.drop_table("candidate_contacts")
    op.drop_index(op.f("ix_candidate_facts_profile_id"), table_name="candidate_facts")
    op.drop_table("candidate_facts")
    op.drop_index(op.f("ix_consent_events_request_id"), table_name="consent_events")
    op.drop_index(op.f("ix_consent_events_action_type"), table_name="consent_events")
    op.drop_table("consent_events")
    op.drop_table("candidate_profiles")
