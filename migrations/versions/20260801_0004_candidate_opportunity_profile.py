"""Expand Candidate Profile for opportunity-first assessment.

Revision ID: 20260801_0004
Revises: 20260801_0003
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260801_0004"
down_revision: str | None = "20260801_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_list_column(name: str) -> sa.Column[object]:
    return sa.Column(
        name,
        postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text("'[]'::jsonb"),
        nullable=False,
    )


def _permission_columns() -> list[sa.Column[object]]:
    return [
        sa.Column("store_private", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("use_for_ai_analysis", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("use_in_draft", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("send_externally", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("publish_publicly", sa.Boolean(), server_default=sa.false(), nullable=False),
    ]


def _version_columns() -> list[sa.Column[object]]:
    return [
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.add_column("candidate_profiles", sa.Column("total_years_experience", sa.Float()))
    op.add_column("candidate_profiles", sa.Column("management_years_experience", sa.Float()))
    for name in (
        "adjacent_roles",
        "excluded_roles",
        "preferred_industries",
        "excluded_industries",
        "remote_work_countries",
        "relocation_countries",
        "business_trip_countries",
        "preferred_regions",
        "collaboration_formats",
        "workplace_formats",
        "preferred_company_types",
    ):
        op.add_column("candidate_profiles", _json_list_column(name))
    op.add_column("candidate_profiles", sa.Column("geography_constraints", sa.Text()))
    op.add_column("candidate_profiles", sa.Column("visa_or_sponsorship_required", sa.Boolean()))
    op.add_column(
        "candidate_profiles",
        sa.Column(
            "temporary_relocation_allowed",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "candidate_profiles",
        sa.Column(
            "on_the_ground_launch_allowed",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column("candidate_profiles", sa.Column("target_income", sa.String(length=160)))
    op.add_column(
        "candidate_profiles", sa.Column("desired_responsibility_level", sa.String(length=160))
    )
    op.add_column("candidate_profiles", sa.Column("preferred_culture", sa.Text()))

    op.create_table(
        "candidate_experiences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.String(length=200), nullable=False),
        sa.Column("organization_label", sa.String(length=200)),
        sa.Column("industry", sa.String(length=160)),
        sa.Column("started_at", sa.Date()),
        sa.Column("ended_at", sa.Date()),
        _json_list_column("project_types"),
        sa.Column("responsibility_level", sa.String(length=160)),
        sa.Column("team_size_max", sa.Integer()),
        _json_list_column("budget_ranges"),
        _json_list_column("project_geographies"),
        sa.Column("contractor_management", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("negotiations", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("territory_development", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("launches", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("operations_management", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("crisis_or_complex_situations", sa.Text()),
        _json_list_column("achievement_fact_ids"),
        sa.Column("verified", sa.Boolean(), server_default=sa.false(), nullable=False),
        *_permission_columns(),
        *_version_columns(),
        sa.ForeignKeyConstraint(["profile_id"], ["candidate_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_candidate_experiences_profile_id"), "candidate_experiences", ["profile_id"]
    )

    op.create_table(
        "candidate_skills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("skill_group", sa.String(length=40), nullable=False),
        sa.Column("actual_level", sa.String(length=40), nullable=False),
        sa.Column("duration_months", sa.Integer()),
        sa.Column("evidence", sa.Text()),
        _json_list_column("implemented_project_fact_ids"),
        sa.Column("verified_results", sa.Text()),
        sa.Column("limitations", sa.Text()),
        sa.Column("verified", sa.Boolean(), server_default=sa.false(), nullable=False),
        *_permission_columns(),
        *_version_columns(),
        sa.ForeignKeyConstraint(["profile_id"], ["candidate_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_candidate_skills_profile_id"), "candidate_skills", ["profile_id"])

    op.create_table(
        "candidate_strengths",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("strength_type", sa.String(length=80), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text()),
        sa.Column("verified", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="100", nullable=False),
        *_permission_columns(),
        *_version_columns(),
        sa.ForeignKeyConstraint(["profile_id"], ["candidate_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_candidate_strengths_profile_id"), "candidate_strengths", ["profile_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_candidate_strengths_profile_id"), table_name="candidate_strengths")
    op.drop_table("candidate_strengths")
    op.drop_index(op.f("ix_candidate_skills_profile_id"), table_name="candidate_skills")
    op.drop_table("candidate_skills")
    op.drop_index(op.f("ix_candidate_experiences_profile_id"), table_name="candidate_experiences")
    op.drop_table("candidate_experiences")

    for name in (
        "preferred_culture",
        "desired_responsibility_level",
        "target_income",
        "preferred_company_types",
        "on_the_ground_launch_allowed",
        "temporary_relocation_allowed",
        "visa_or_sponsorship_required",
        "geography_constraints",
        "workplace_formats",
        "collaboration_formats",
        "preferred_regions",
        "business_trip_countries",
        "relocation_countries",
        "remote_work_countries",
        "excluded_industries",
        "preferred_industries",
        "excluded_roles",
        "adjacent_roles",
        "management_years_experience",
        "total_years_experience",
    ):
        op.drop_column("candidate_profiles", name)
