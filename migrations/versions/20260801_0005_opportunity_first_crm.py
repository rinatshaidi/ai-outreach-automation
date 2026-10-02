"""Add opportunity-first Mini-CRM foundation and guarded decision data.

Revision ID: 20260801_0005
Revises: 20260801_0004
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260801_0005"
down_revision: str | None = "20260801_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_list_column(name: str) -> sa.Column[object]:
    return sa.Column(
        name,
        postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text("'[]'::jsonb"),
        nullable=False,
    )


def _version_columns() -> list[sa.Column[object]]:
    return [
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    for name in (
        "operating_regions",
        "opportunity_types",
        "recommended_collaboration_formats",
        "recommended_workplace_formats",
    ):
        op.add_column("companies", _json_list_column(name))
    op.add_column("companies", sa.Column("company_size", sa.String(length=80)))
    op.add_column("companies", sa.Column("maturity_stage", sa.String(length=80)))
    op.add_column("companies", sa.Column("recommended_positioning", sa.String(length=40)))
    op.add_column("companies", sa.Column("recommended_role", sa.String(length=240)))
    for name in (
        "business_fit_score",
        "ai_automation_fit_score",
        "hybrid_fit_score",
        "format_fit_score",
        "geography_fit_score",
        "timing_signal_score",
        "contactability_score",
        "overall_opportunity_score",
    ):
        op.add_column("companies", sa.Column(name, sa.Float()))

    for name in ("opportunity_types", "positioning_strategies", "collaboration_formats"):
        op.add_column("campaigns", _json_list_column(name))

    op.create_table(
        "company_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=60), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
        sa.Column("http_status", sa.Integer()),
        sa.Column("content_hash", sa.String(length=128)),
        sa.Column("extracted_text", sa.Text()),
        sa.Column("language", sa.String(length=20)),
        sa.Column("trust_level", sa.String(length=30), server_default="unverified", nullable=False),
        sa.Column(
            "freshness_status", sa.String(length=30), server_default="unknown", nullable=False
        ),
        sa.Column("error", sa.Text()),
        *_version_columns(),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "url", name="uq_company_sources_url"),
    )
    op.create_index(op.f("ix_company_sources_company_id"), "company_sources", ["company_id"])

    op.add_column("contacts", sa.Column("decision_maker_role", sa.String(length=80)))
    op.add_column("contacts", sa.Column("decision_priority", sa.Integer()))
    op.add_column("contacts", sa.Column("source_id", sa.Uuid()))
    op.create_index(op.f("ix_contacts_decision_maker_role"), "contacts", ["decision_maker_role"])
    op.create_index(op.f("ix_contacts_source_id"), "contacts", ["source_id"])
    op.create_foreign_key(
        "fk_contacts_source_id_company_sources",
        "contacts",
        "company_sources",
        ["source_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("job_openings", sa.Column("source_id", sa.Uuid()))
    op.create_index(op.f("ix_job_openings_source_id"), "job_openings", ["source_id"])
    op.create_foreign_key(
        "fk_job_openings_source_id_company_sources",
        "job_openings",
        "company_sources",
        ["source_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "opportunity_signals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid()),
        sa.Column("signal_type", sa.String(length=60), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True)),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("exact_fragment", sa.Text()),
        sa.Column("status", sa.String(length=30), server_default="proposed", nullable=False),
        *_version_columns(),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["company_sources.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_opportunity_signals_company_id"), "opportunity_signals", ["company_id"]
    )
    op.create_index(op.f("ix_opportunity_signals_source_id"), "opportunity_signals", ["source_id"])
    op.create_index(
        op.f("ix_opportunity_signals_signal_type"), "opportunity_signals", ["signal_type"]
    )
    op.create_index(op.f("ix_opportunity_signals_status"), "opportunity_signals", ["status"])

    op.create_table(
        "company_opportunities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_type", sa.String(length=60), nullable=False),
        _json_list_column("source_ids"),
        _json_list_column("signal_ids"),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="proposed", nullable=False),
        *_version_columns(),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "opportunity_type", name="uq_company_opportunity_type"),
    )
    op.create_index(
        op.f("ix_company_opportunities_company_id"), "company_opportunities", ["company_id"]
    )
    op.create_index(
        op.f("ix_company_opportunities_opportunity_type"),
        "company_opportunities",
        ["opportunity_type"],
    )
    op.create_index(op.f("ix_company_opportunities_status"), "company_opportunities", ["status"])

    op.create_table(
        "opportunity_assessments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_profile_version", sa.Integer(), nullable=False),
        sa.Column("business_fit_score", sa.Float(), nullable=False),
        sa.Column("ai_automation_fit_score", sa.Float(), nullable=False),
        sa.Column("hybrid_fit_score", sa.Float(), nullable=False),
        sa.Column("format_fit_score", sa.Float(), nullable=False),
        sa.Column("geography_fit_score", sa.Float(), nullable=False),
        sa.Column("timing_signal_score", sa.Float(), nullable=False),
        sa.Column("contactability_score", sa.Float(), nullable=False),
        sa.Column("overall_opportunity_score", sa.Float(), nullable=False),
        sa.Column("score_breakdown", postgresql.JSONB(), nullable=False),
        _json_list_column("opportunity_ids"),
        _json_list_column("candidate_fact_ids"),
        _json_list_column("company_fact_ids"),
        _json_list_column("opportunity_signal_ids"),
        _json_list_column("source_ids"),
        _json_list_column("possible_business_tasks"),
        _json_list_column("candidate_value_hypotheses"),
        _json_list_column("recommended_collaboration_formats"),
        _json_list_column("recommended_workplace_formats"),
        _json_list_column("possible_roles"),
        _json_list_column("reasons_to_contact"),
        _json_list_column("reasons_not_to_contact"),
        _json_list_column("risks"),
        sa.Column("next_action", sa.String(length=500)),
        sa.Column("model_or_rule_version", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_opportunity_assessments_company_id"), "opportunity_assessments", ["company_id"]
    )
    op.create_index(
        op.f("ix_opportunity_assessments_created_at"), "opportunity_assessments", ["created_at"]
    )

    op.create_table(
        "positioning_recommendations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("primary_strategy", sa.String(length=40), nullable=False),
        sa.Column("primary_message_line", sa.Text(), nullable=False),
        sa.Column("secondary_advantage", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("value_proposition", sa.Text(), nullable=False),
        sa.Column("concrete_first_message_offer", sa.Text(), nullable=False),
        sa.Column("primary_decision_maker_role", sa.String(length=80), nullable=False),
        sa.Column("secondary_decision_maker_role", sa.String(length=80), nullable=False),
        sa.Column("collaboration_format", sa.String(length=60), nullable=False),
        _json_list_column("workplace_formats"),
        sa.Column("possible_role", sa.String(length=500), nullable=False),
        sa.Column("user_decision", sa.String(length=30), server_default="pending", nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        *_version_columns(),
        sa.ForeignKeyConstraint(
            ["assessment_id"], ["opportunity_assessments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_positioning_recommendations_company_id"),
        "positioning_recommendations",
        ["company_id"],
    )
    op.create_index(
        op.f("ix_positioning_recommendations_assessment_id"),
        "positioning_recommendations",
        ["assessment_id"],
    )
    op.create_index(
        op.f("ix_positioning_recommendations_primary_strategy"),
        "positioning_recommendations",
        ["primary_strategy"],
    )

    op.create_table(
        "opportunity_decision_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=30), nullable=False),
        sa.Column("confirmed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["recommendation_id"], ["positioning_recommendations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_opportunity_decision_events_company_id"),
        "opportunity_decision_events",
        ["company_id"],
    )
    op.create_index(
        op.f("ix_opportunity_decision_events_recommendation_id"),
        "opportunity_decision_events",
        ["recommendation_id"],
    )
    op.create_index(
        op.f("ix_opportunity_decision_events_decision"), "opportunity_decision_events", ["decision"]
    )

    op.execute(
        "UPDATE companies SET pipeline_status = 'opportunity_identified' "
        "WHERE pipeline_status = 'qualified'"
    )
    op.execute(
        "UPDATE companies SET relevance_status = 'opportunity_identified' "
        "WHERE relevance_status = 'qualified'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE companies SET pipeline_status = 'qualified' "
        "WHERE pipeline_status = 'opportunity_identified'"
    )
    op.execute(
        "UPDATE companies SET relevance_status = 'qualified' "
        "WHERE relevance_status = 'opportunity_identified'"
    )

    for table in (
        "opportunity_decision_events",
        "positioning_recommendations",
        "opportunity_assessments",
        "company_opportunities",
        "opportunity_signals",
    ):
        op.drop_table(table)

    op.drop_constraint(
        "fk_job_openings_source_id_company_sources", "job_openings", type_="foreignkey"
    )
    op.drop_index(op.f("ix_job_openings_source_id"), table_name="job_openings")
    op.drop_column("job_openings", "source_id")
    op.drop_constraint("fk_contacts_source_id_company_sources", "contacts", type_="foreignkey")
    op.drop_index(op.f("ix_contacts_source_id"), table_name="contacts")
    op.drop_index(op.f("ix_contacts_decision_maker_role"), table_name="contacts")
    op.drop_column("contacts", "source_id")
    op.drop_column("contacts", "decision_priority")
    op.drop_column("contacts", "decision_maker_role")
    op.drop_table("company_sources")

    for name in ("collaboration_formats", "positioning_strategies", "opportunity_types"):
        op.drop_column("campaigns", name)
    for name in (
        "overall_opportunity_score",
        "contactability_score",
        "timing_signal_score",
        "geography_fit_score",
        "format_fit_score",
        "hybrid_fit_score",
        "ai_automation_fit_score",
        "business_fit_score",
        "recommended_role",
        "recommended_positioning",
        "recommended_workplace_formats",
        "recommended_collaboration_formats",
        "opportunity_types",
        "maturity_stage",
        "company_size",
        "operating_regions",
    ):
        op.drop_column("companies", name)
