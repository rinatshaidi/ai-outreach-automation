"""Persistence for explicit owner overrides of deterministic assessments."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class OpportunityAssessmentOverride(Base):
    __tablename__ = "opportunity_assessment_overrides"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assessment_id: Mapped[UUID] = mapped_column(
        ForeignKey("opportunity_assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    original_score: Mapped[float] = mapped_column(Float, nullable=False)
    overridden_score: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
