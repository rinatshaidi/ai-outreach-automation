"""Persistence models for companies, contacts, jobs, campaigns and timeline events."""

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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    normalized_domain: Mapped[str] = mapped_column(String(253), nullable=False, unique=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    country: Mapped[str | None] = mapped_column(String(120))
    identity_verification_status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="unconfirmed", index=True
    )
    identity_source_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("company_sources.id", ondelete="SET NULL"), index=True
    )
    geography_verification_status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="unconfirmed", index=True
    )
    geography_source_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("company_sources.id", ondelete="SET NULL"), index=True
    )
    operating_regions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    industry: Mapped[str | None] = mapped_column(String(160))
    company_size: Mapped[str | None] = mapped_column(String(80))
    maturity_stage: Mapped[str | None] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text)
    language_signals: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    opportunity_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    recommended_positioning: Mapped[str | None] = mapped_column(String(40))
    recommended_collaboration_formats: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    recommended_workplace_formats: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    recommended_role: Mapped[str | None] = mapped_column(String(240))
    business_fit_score: Mapped[float | None] = mapped_column(Float)
    ai_automation_fit_score: Mapped[float | None] = mapped_column(Float)
    hybrid_fit_score: Mapped[float | None] = mapped_column(Float)
    format_fit_score: Mapped[float | None] = mapped_column(Float)
    geography_fit_score: Mapped[float | None] = mapped_column(Float)
    timing_signal_score: Mapped[float | None] = mapped_column(Float)
    contactability_score: Mapped[float | None] = mapped_column(Float)
    overall_opportunity_score: Mapped[float | None] = mapped_column(Float)
    relevance_score: Mapped[float | None] = mapped_column(Float)
    relevance_status: Mapped[str] = mapped_column(String(30), nullable=False, default="unscored")
    pipeline_status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="new", index=True
    )
    next_action: Mapped[str | None] = mapped_column(String(240))
    note: Mapped[str | None] = mapped_column(Text)
    last_researched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    contact_discovery_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="not_started", index=True
    )
    contact_discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    contacts: Mapped[list["Contact"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    jobs: Mapped[list["JobOpening"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    events: Mapped[list["CommunicationEvent"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    sources: Mapped[list["CompanySource"]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        foreign_keys="CompanySource.company_id",
    )


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("company_id", "email", name="uq_contacts_company_email"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    telegram: Mapped[str | None] = mapped_column(String(160))
    linkedin: Mapped[str | None] = mapped_column(Text)
    other_public_link: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="unverified", index=True
    )
    validation_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="UNVERIFIED_CONTACT", index=True
    )
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    validation_http_status: Mapped[int | None] = mapped_column(Integer)
    validation_final_url: Mapped[str | None] = mapped_column(Text)
    validation_error: Mapped[str | None] = mapped_column(String(500))
    confidence: Mapped[float | None] = mapped_column(Float)
    lawful_public_source_note: Mapped[str | None] = mapped_column(Text)
    decision_maker_role: Mapped[str | None] = mapped_column(String(80), index=True)
    decision_priority: Mapped[int | None] = mapped_column(Integer)
    source_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("company_sources.id", ondelete="SET NULL"), index=True
    )
    do_not_contact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    why_relevant: Mapped[str | None] = mapped_column(Text)
    discovery_score: Mapped[float | None] = mapped_column(Float, index=True)
    rank_label: Mapped[str | None] = mapped_column(String(30), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    company: Mapped[Company] = relationship(back_populates="contacts")
    channels: Mapped[list["ContactChannel"]] = relationship(
        back_populates="contact", cascade="all, delete-orphan"
    )


class ContactChannel(Base):
    __tablename__ = "contact_channels"
    __table_args__ = (
        UniqueConstraint("contact_id", "channel_type", "value", name="uq_contact_channels_value"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    contact_id: Mapped[UUID] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(60), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    validation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="UNVERIFIED", index=True
    )
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    validation_http_status: Mapped[int | None] = mapped_column(Integer)
    validation_final_url: Mapped[str | None] = mapped_column(Text)
    validation_error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    contact: Mapped[Contact] = relationship(back_populates="channels")


class JobOpening(Base):
    __tablename__ = "job_openings"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("company_sources.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    location: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    required_skills: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    company: Mapped[Company] = relationship(back_populates="jobs")


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    criteria: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    opportunity_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    positioning_strategies: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    collaboration_formats: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    preferred_language: Mapped[str] = mapped_column(String(20), nullable=False, default="auto")
    tone_defaults: Mapped[str] = mapped_column(String(40), nullable=False, default="professional")
    daily_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    followup_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class CommunicationEvent(Base):
    __tablename__ = "communication_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    company: Mapped[Company] = relationship(back_populates="events")


class CompanySource(Base):
    __tablename__ = "company_sources"
    __table_args__ = (UniqueConstraint("company_id", "url", name="uq_company_sources_url"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(60), nullable=False)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str | None] = mapped_column(String(128))
    extracted_text: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(20))
    trust_level: Mapped[str] = mapped_column(String(30), nullable=False, default="unverified")
    freshness_status: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown")
    error: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    company: Mapped[Company] = relationship(back_populates="sources", foreign_keys=[company_id])
