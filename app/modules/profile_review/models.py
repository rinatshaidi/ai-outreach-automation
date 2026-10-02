"""Persistence for profile sections, import previews and pilot calibration."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class CandidateProfileSection(Base):
    __tablename__ = "candidate_profile_sections"
    __table_args__ = (UniqueConstraint("profile_id", "section_type"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", index=True)
    content_draft: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    user_comment: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ProfileReviewEvent(Base):
    __tablename__ = "profile_review_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    profile_section_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_profile_sections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_status: Mapped[str] = mapped_column(String(30), nullable=False)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    safe_diff: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ProfileImportBatch(Base):
    __tablename__ = "profile_import_batches"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_filename: Mapped[str] = mapped_column(String(240), nullable=False)
    source_format: Mapped[str] = mapped_column(String(30), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="uploaded", index=True)
    validation_report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProfileImportItem(Base):
    __tablename__ = "profile_import_items"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("profile_import_batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(40), nullable=False)
    target_entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_entity_id: Mapped[UUID | None] = mapped_column(Uuid)
    proposed_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    current_data_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    validation_messages: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    default_permissions: Mapped[dict[str, bool]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    decision: Mapped[str] = mapped_column(String(30), nullable=False, default="pending", index=True)
    applied_entity_id: Mapped[UUID | None] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class PilotCalibrationNote(Base):
    __tablename__ = "pilot_calibration_notes"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    company_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    category: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    observation: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_change: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open")
    rule_version: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
