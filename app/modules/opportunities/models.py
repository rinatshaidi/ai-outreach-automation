"""Persistence models for opportunity-first Mini-CRM decisions and provenance."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class OpportunitySignal(Base):
    __tablename__ = "opportunity_signals"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("company_sources.id", ondelete="SET NULL"), index=True
    )
    signal_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    exact_fragment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="proposed", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class CompanyOpportunity(Base):
    __tablename__ = "company_opportunities"
    __table_args__ = (
        UniqueConstraint("company_id", "opportunity_type", name="uq_company_opportunity_type"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    opportunity_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    source_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    signal_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="proposed", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class OpportunityAssessment(Base):
    __tablename__ = "opportunity_assessments"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    business_fit_score: Mapped[float] = mapped_column(Float, nullable=False)
    ai_automation_fit_score: Mapped[float] = mapped_column(Float, nullable=False)
    hybrid_fit_score: Mapped[float] = mapped_column(Float, nullable=False)
    format_fit_score: Mapped[float] = mapped_column(Float, nullable=False)
    geography_fit_score: Mapped[float] = mapped_column(Float, nullable=False)
    timing_signal_score: Mapped[float] = mapped_column(Float, nullable=False)
    contactability_score: Mapped[float] = mapped_column(Float, nullable=False)
    overall_opportunity_score: Mapped[float] = mapped_column(Float, nullable=False)
    score_breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    opportunity_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    candidate_fact_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    company_fact_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    opportunity_signal_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    source_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    possible_business_tasks: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    candidate_value_hypotheses: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    recommended_collaboration_formats: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    recommended_workplace_formats: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    possible_roles: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    reasons_to_contact: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    reasons_not_to_contact: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    risks: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    next_action: Mapped[str | None] = mapped_column(String(500))
    model_or_rule_version: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, index=True
    )


class PositioningRecommendation(Base):
    __tablename__ = "positioning_recommendations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assessment_id: Mapped[UUID] = mapped_column(
        ForeignKey("opportunity_assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    primary_strategy: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    primary_message_line: Mapped[str] = mapped_column(Text, nullable=False)
    secondary_advantage: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    value_proposition: Mapped[str] = mapped_column(Text, nullable=False)
    concrete_first_message_offer: Mapped[str] = mapped_column(Text, nullable=False)
    primary_decision_maker_role: Mapped[str] = mapped_column(String(80), nullable=False)
    secondary_decision_maker_role: Mapped[str] = mapped_column(String(80), nullable=False)
    collaboration_format: Mapped[str] = mapped_column(String(60), nullable=False)
    workplace_formats: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    possible_role: Mapped[str] = mapped_column(String(500), nullable=False)
    user_decision: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class OpportunityDecisionEvent(Base):
    __tablename__ = "opportunity_decision_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recommendation_id: Mapped[UUID] = mapped_column(
        ForeignKey("positioning_recommendations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    decision: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    confirmed: Mapped[bool] = mapped_column(nullable=False, default=False)
    comment: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
