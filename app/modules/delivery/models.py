"""Persistence for outbound messages and append-only delivery attempts."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class OutboundMessage(Base):
    __tablename__ = "outbound_messages"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contact_id: Mapped[UUID] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    draft_id: Mapped[UUID] = mapped_column(
        ForeignKey("message_drafts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    approval_id: Mapped[UUID] = mapped_column(
        ForeignKey("draft_approvals.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    direction: Mapped[str] = mapped_column(String(20), nullable=False, default="outbound")
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="email")
    delivery_mode: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    recipient_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    recipient_masked: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(240), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    delivery_status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    external_message_id: Mapped[str | None] = mapped_column(String(500))
    external_thread_id: Mapped[str | None] = mapped_column(String(500), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    safe_error_code: Mapped[str | None] = mapped_column(String(80))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, index=True
    )


class DeliveryAttempt(Base):
    __tablename__ = "delivery_attempts"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("outbound_messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False)
    safe_error_code: Mapped[str | None] = mapped_column(String(80))
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, index=True
    )
