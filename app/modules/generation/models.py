"""Persistence for privacy-safe generation runs and immutable generated drafts."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class SenderVoiceProfile(Base):
    """Personal voice and motivation, deliberately separate from factual Candidate Profile."""

    __tablename__ = "sender_voice_profiles"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    candidate_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    communication_style: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    values: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    motivations: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    interests: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    preferred_tone: Mapped[str] = mapped_column(String(80), nullable=False, default="personal")
    preferred_openings: Mapped[dict[str, list[str]]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    things_to_avoid: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class ApprovedWritingExample(Base):
    """Owner-approved style reference; content is guidance, never a factual source."""

    __tablename__ = "approved_writing_examples"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    sender_voice_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("sender_voice_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    language: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    company_context: Mapped[str] = mapped_column(String(300), nullable=False)
    purpose: Mapped[str] = mapped_column(String(120), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class GenerationRun(Base):
    __tablename__ = "generation_runs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contact_id: Mapped[UUID] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recommendation_id: Mapped[UUID] = mapped_column(
        ForeignKey("positioning_recommendations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    assessment_id: Mapped[UUID] = mapped_column(
        ForeignKey("opportunity_assessments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    input_entity_ids: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    validation_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, index=True
    )


class MessageDraft(Base):
    __tablename__ = "message_drafts"
    __table_args__ = (
        UniqueConstraint(
            "generation_run_id",
            "variant",
            "revision",
            name="uq_message_draft_run_variant_revision",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    generation_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("generation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contact_id: Mapped[UUID] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contact_version: Mapped[int] = mapped_column(Integer, nullable=False)
    recommendation_id: Mapped[UUID] = mapped_column(
        ForeignKey("positioning_recommendations.id", ondelete="RESTRICT"), nullable=False
    )
    assessment_id: Mapped[UUID] = mapped_column(
        ForeignKey("opportunity_assessments.id", ondelete="RESTRICT"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    variant: Mapped[str] = mapped_column(String(20), nullable=False)
    message_format: Mapped[str] = mapped_column(
        String(30), nullable=False, default="expanded"
    )
    tone: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(240), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(20), nullable=False)
    language_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    language_reason: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    opportunity_type_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    opportunity_signal_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    positioning_strategy: Mapped[str] = mapped_column(String(40), nullable=False)
    collaboration_format: Mapped[str] = mapped_column(String(60), nullable=False)
    value_proposition: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_fact_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    company_fact_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    source_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    warnings: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    validation_report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, index=True
    )


class DraftApproval(Base):
    __tablename__ = "draft_approvals"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    draft_id: Mapped[UUID] = mapped_column(
        ForeignKey("message_drafts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    draft_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    approved_by: Mapped[str] = mapped_column(String(120), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    comment: Mapped[str | None] = mapped_column(Text)
    one_time_token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidation_reason: Mapped[str | None] = mapped_column(String(240))
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)


class DraftReviewEvent(Base):
    __tablename__ = "draft_review_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    draft_id: Mapped[UUID] = mapped_column(
        ForeignKey("message_drafts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    safe_diff: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, index=True
    )
