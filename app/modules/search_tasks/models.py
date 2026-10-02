"""Persistence for isolated manual search tasks and their CRM results."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base, UuidTimestampMixin


class SearchTask(UuidTimestampMixin, Base):
    __tablename__ = "search_tasks"

    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    original_query: Mapped[str] = mapped_column(Text, nullable=False)
    query_language: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    task_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    parsed_country: Mapped[str | None] = mapped_column(String(120))
    parsed_region: Mapped[str | None] = mapped_column(String(160))
    parsed_industry: Mapped[str | None] = mapped_column(String(160))
    parsed_focus: Mapped[str | None] = mapped_column(String(200))
    company_name_or_url: Mapped[str | None] = mapped_column(Text)
    result_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual", index=True)
    scheduled_for_date: Mapped[date | None] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="QUEUED", index=True)
    current_stage: Mapped[str | None] = mapped_column(String(80))
    failure_code: Mapped[str | None] = mapped_column(String(80))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    found_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accepted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class SearchTaskResult(Base):
    __tablename__ = "search_task_results"
    __table_args__ = (
        UniqueConstraint("search_task_id", "company_id", name="uq_search_task_result_company"),
    )

    search_task_id: Mapped[UUID] = mapped_column(
        ForeignKey("search_tasks.id", ondelete="CASCADE"), primary_key=True
    )
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    accepted: Mapped[bool] = mapped_column(nullable=False, default=False)
    qualification_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="PENDING", index=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    qualification_evidence: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
