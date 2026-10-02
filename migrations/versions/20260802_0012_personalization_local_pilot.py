"""Add authentication, profile review, safe import and pilot calibration.

Revision ID: 20260802_0012
Revises: 20260801_0011
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260802_0012"
down_revision: str | None = "20260801_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROFILE_SECTIONS = (
    "positioning",
    "title_summary",
    "management_business_experience",
    "roles_periods_industries",
    "projects_achievements",
    "teams_budgets_responsibility",
    "experience_geography",
    "contractors_partners_negotiations",
    "ai_projects",
    "technical_skills",
    "strengths",
    "desired_adjacent_roles",
    "excluded_roles",
    "employment_project_formats",
    "consulting_contract",
    "workplace_formats",
    "relocation_travel",
    "countries_regions",
    "income_constraints",
    "languages",
    "contacts",
    "positioning_constraints",
    "permissions_consent",
)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("login_identifier", sa.String(length=200), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("login_identifier"),
    )
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("login_hash", sa.String(length=64), nullable=False),
        sa.Column("result", sa.String(length=30), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=False),
        sa.Column("client_fingerprint", sa.String(length=64)),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("login_hash", "result", "client_fingerprint", "request_id", "occurred_at"):
        op.create_index(op.f(f"ix_login_attempts_{column}"), "login_attempts", [column])
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("client_fingerprint", sa.String(length=64)),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("user_id", "token_hash", "expires_at"):
        op.create_index(
            op.f(f"ix_auth_sessions_{column}"),
            "auth_sessions",
            [column],
            unique=column == "token_hash",
        )
    op.create_table(
        "candidate_profile_sections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("section_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("content_hash", sa.String(length=64)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("user_comment", sa.Text()),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by", sa.String(length=120)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["candidate_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", "section_type"),
    )
    op.create_index(
        op.f("ix_candidate_profile_sections_profile_id"),
        "candidate_profile_sections",
        ["profile_id"],
    )
    op.create_index(
        op.f("ix_candidate_profile_sections_section_type"),
        "candidate_profile_sections",
        ["section_type"],
    )
    op.create_index(
        op.f("ix_candidate_profile_sections_status"),
        "candidate_profile_sections",
        ["status"],
    )
    op.create_table(
        "profile_review_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_section_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(length=30), nullable=False),
        sa.Column("to_status", sa.String(length=30), nullable=False),
        sa.Column("decision", sa.String(length=30), nullable=False),
        sa.Column("actor", sa.String(length=120), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column("safe_diff", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_section_id"], ["candidate_profile_sections.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_profile_review_events_profile_section_id"),
        "profile_review_events",
        ["profile_section_id"],
    )
    op.create_index(
        op.f("ix_profile_review_events_request_id"),
        "profile_review_events",
        ["request_id"],
    )
    op.create_table(
        "profile_import_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("source_filename", sa.String(length=240), nullable=False),
        sa.Column("source_format", sa.String(length=30), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("validation_report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["profile_id"], ["candidate_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("profile_id", "source_hash", "status"):
        op.create_index(
            op.f(f"ix_profile_import_batches_{column}"), "profile_import_batches", [column]
        )
    op.create_table(
        "profile_import_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("section_type", sa.String(length=80), nullable=False),
        sa.Column("operation", sa.String(length=40), nullable=False),
        sa.Column("target_entity_type", sa.String(length=80), nullable=False),
        sa.Column("target_entity_id", sa.Uuid()),
        sa.Column("proposed_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("current_data_snapshot", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("validation_messages", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("default_permissions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("decision", sa.String(length=30), nullable=False),
        sa.Column("applied_entity_id", sa.Uuid()),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["profile_import_batches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("batch_id", "section_type", "decision"):
        op.create_index(op.f(f"ix_profile_import_items_{column}"), "profile_import_items", [column])
    op.create_table(
        "pilot_calibration_notes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid()),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("observation", sa.Text(), nullable=False),
        sa.Column("proposed_change", sa.Text()),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("rule_version", sa.String(length=80)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_pilot_calibration_notes_company_id"),
        "pilot_calibration_notes",
        ["company_id"],
    )
    op.create_index(
        op.f("ix_pilot_calibration_notes_category"),
        "pilot_calibration_notes",
        ["category"],
    )
    for table in (
        "candidate_experiences",
        "candidate_skills",
        "candidate_strengths",
        "candidate_facts",
        "candidate_contacts",
    ):
        op.add_column(
            table,
            sa.Column("use_in_scoring", sa.Boolean(), server_default=sa.false(), nullable=False),
        )
        op.add_column(
            table,
            sa.Column("use_in_signature", sa.Boolean(), server_default=sa.false(), nullable=False),
        )

    values = ", ".join(f"('{value}')" for value in PROFILE_SECTIONS)
    op.execute(  # noqa: S608 - values are fixed constants declared in this migration
        sa.text(
            "INSERT INTO candidate_profile_sections "  # noqa: S608
            "(id, profile_id, section_type, status, version, created_at, updated_at) "
            "SELECT gen_random_uuid(), p.id, s.section_type, 'review_required', 1, now(), now() "
            f"FROM candidate_profiles p CROSS JOIN (VALUES {values}) AS s(section_type)"  # noqa: S608
        )
    )


def downgrade() -> None:
    for table in (
        "candidate_contacts",
        "candidate_facts",
        "candidate_strengths",
        "candidate_skills",
        "candidate_experiences",
    ):
        op.drop_column(table, "use_in_signature")
        op.drop_column(table, "use_in_scoring")
    op.drop_table("pilot_calibration_notes")
    op.drop_table("profile_import_items")
    op.drop_table("profile_import_batches")
    op.drop_table("profile_review_events")
    op.drop_table("candidate_profile_sections")
    op.drop_table("auth_sessions")
    op.drop_table("login_attempts")
    op.drop_table("users")
