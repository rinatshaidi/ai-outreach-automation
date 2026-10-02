"""Persistence models for the single-owner candidate profile."""

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class CandidatePermissionMixin:
    """Fail-closed permissions shared by new structured profile records."""

    store_private: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    use_for_ai_analysis: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    use_in_scoring: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    use_in_draft: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    send_externally: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    use_in_signature: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    publish_publicly: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_key: Mapped[str] = mapped_column(
        String(40), unique=True, nullable=False, default="primary"
    )
    display_name: Mapped[str | None] = mapped_column(String(160))
    professional_title: Mapped[str | None] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text)
    total_years_experience: Mapped[float | None] = mapped_column(Float)
    management_years_experience: Mapped[float | None] = mapped_column(Float)
    desired_roles: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    adjacent_roles: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    excluded_roles: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    preferred_industries: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    excluded_industries: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    preferred_countries: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    work_formats: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    remote_work_countries: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    relocation_countries: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    business_trip_countries: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    preferred_regions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    geography_constraints: Mapped[str | None] = mapped_column(Text)
    visa_or_sponsorship_required: Mapped[bool | None] = mapped_column(Boolean)
    temporary_relocation_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    on_the_ground_launch_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    collaboration_formats: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    workplace_formats: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    target_income: Mapped[str | None] = mapped_column(String(160))
    desired_responsibility_level: Mapped[str | None] = mapped_column(String(160))
    preferred_company_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    preferred_culture: Mapped[str | None] = mapped_column(Text)
    language_level: Mapped[str | None] = mapped_column(String(80))
    profile_status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    facts: Mapped[list["CandidateFact"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    contacts: Mapped[list["CandidateContact"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    rules: Mapped[list["CandidateRule"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    experiences: Mapped[list["CandidateExperience"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    skills: Mapped[list["CandidateSkill"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    strengths: Mapped[list["CandidateStrength"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


class CandidateExperience(CandidatePermissionMixin, Base):
    __tablename__ = "candidate_experiences"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[str] = mapped_column(String(200), nullable=False)
    organization_label: Mapped[str | None] = mapped_column(String(200))
    industry: Mapped[str | None] = mapped_column(String(160))
    started_at: Mapped[date | None] = mapped_column(Date)
    ended_at: Mapped[date | None] = mapped_column(Date)
    project_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    responsibility_level: Mapped[str | None] = mapped_column(String(160))
    team_size_max: Mapped[int | None] = mapped_column(Integer)
    budget_ranges: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    project_geographies: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    contractor_management: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    negotiations: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    territory_development: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    launches: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    operations_management: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    crisis_or_complex_situations: Mapped[str | None] = mapped_column(Text)
    achievement_fact_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    profile: Mapped[CandidateProfile] = relationship(back_populates="experiences")


class CandidateSkill(CandidatePermissionMixin, Base):
    __tablename__ = "candidate_skills"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    skill_group: Mapped[str] = mapped_column(String(40), nullable=False)
    actual_level: Mapped[str] = mapped_column(String(40), nullable=False)
    duration_months: Mapped[int | None] = mapped_column(Integer)
    evidence: Mapped[str | None] = mapped_column(Text)
    implemented_project_fact_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    verified_results: Mapped[str | None] = mapped_column(Text)
    limitations: Mapped[str | None] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    profile: Mapped[CandidateProfile] = relationship(back_populates="skills")


class CandidateStrength(CandidatePermissionMixin, Base):
    __tablename__ = "candidate_strengths"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True
    )
    strength_type: Mapped[str] = mapped_column(String(80), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str | None] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    profile: Mapped[CandidateProfile] = relationship(back_populates="strengths")


class CandidateFact(Base):
    __tablename__ = "candidate_facts"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True
    )
    fact_type: Mapped[str] = mapped_column(String(60), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str | None] = mapped_column(Text)
    source_link: Mapped[str | None] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    store_private: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    use_for_ai_analysis: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    use_in_scoring: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    use_in_draft: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    send_externally: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    use_in_signature: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    publish_publicly: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sensitivity_level: Mapped[str] = mapped_column(String(30), nullable=False, default="private")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    profile: Mapped[CandidateProfile] = relationship(back_populates="facts")


class CandidateContact(Base):
    __tablename__ = "candidate_contacts"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True
    )
    contact_type: Mapped[str] = mapped_column(String(40), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    store_private: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    use_for_ai_analysis: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    use_in_scoring: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    use_in_draft: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    send_externally: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    use_in_signature: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    publish_publicly: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allowed_in_signature: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    profile: Mapped[CandidateProfile] = relationship(back_populates="contacts")


class CandidateRule(Base):
    __tablename__ = "candidate_rules"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True
    )
    rule_type: Mapped[str] = mapped_column(String(60), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="block")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    profile: Mapped[CandidateProfile] = relationship(back_populates="rules")


class ConsentEvent(Base):
    __tablename__ = "consent_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    action_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    data_scope: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[UUID | None] = mapped_column(Uuid)
    destination: Mapped[str | None] = mapped_column(String(240))
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
