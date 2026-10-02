"""Validated follow-up and manual history DTOs."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class FollowUpStatus(StrEnum):
    PLANNED = "planned"
    DUE = "due"
    DRAFT_READY = "draft_ready"
    APPROVED = "approved"
    DEFERRED = "deferred"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    SENT = "sent"
    DELIVERY_FAILED = "delivery_failed"


class ManualOutcome(StrEnum):
    REPLIED = "replied"
    INTERVIEW = "interview"
    PROJECT_DISCUSSION = "project_discussion"
    CONSULTING_DISCUSSION = "consulting_discussion"
    REJECTED = "rejected"
    OFFER = "offer"
    AGREEMENT = "agreement"


class FollowUpRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    contact_id: UUID
    campaign_id: UUID
    original_message_id: UUID
    sequence_number: int
    status: str
    timezone: str
    due_at: datetime
    subject: str | None
    body: str | None
    content_hash: str | None
    validation_report: dict[str, Any]
    approved_at: datetime | None
    approved_by: str | None
    approval_comment: str | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class FollowUpDecisionCreate(BaseModel):
    version: int = Field(ge=1)
    confirmed: bool
    comment: str | None = Field(default=None, max_length=2000)


class FollowUpDeferCreate(BaseModel):
    version: int = Field(ge=1)
    due_at: datetime
    comment: str | None = Field(default=None, max_length=2000)


class ManualReplyCreate(BaseModel):
    company_id: UUID
    contact_id: UUID
    outcome: ManualOutcome
    summary: ShortText
    occurred_at: datetime | None = None

    @field_validator("occurred_at")
    @classmethod
    def require_explicit_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("occurred_at must include a timezone")
        return value


class ManualReplyRead(BaseModel):
    company_id: UUID
    contact_id: UUID
    outcome: ManualOutcome
    cancelled_followups: int
    occurred_at: datetime


class FollowUpRefreshRequest(BaseModel):
    limit: int = Field(default=100, ge=1, le=500)
