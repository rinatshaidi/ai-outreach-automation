"""Persistent owner-controlled safety gates.

Deployment configuration only makes a capability available.  These records are
the independent, fail-closed owner decision required before external delivery.
"""

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base, UuidTimestampMixin


def utc_now() -> datetime:
    return datetime.now(UTC)


class OwnerSafetyPolicy(UuidTimestampMixin, Base):
    __tablename__ = "owner_safety_policies"

    owner_key: Mapped[str] = mapped_column(
        String(80), nullable=False, unique=True, default="primary"
    )
    real_send_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    real_send_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    real_send_disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
