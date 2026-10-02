"""Minimal immutable audit model for the baseline schema."""

from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base, UuidTimestampMixin


class AuditEvent(UuidTimestampMixin, Base):
    __tablename__ = "audit_events"

    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    action: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(120))
    result: Mapped[str] = mapped_column(String(40), nullable=False)
    safe_diff: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
