"""Validated delivery requests and privacy-safe responses."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints


class DeliveryCreate(BaseModel):
    approval_id: UUID
    approval_token: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=20, max_length=500)
    ]
    campaign_id: UUID


class OutboundMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    contact_id: UUID
    campaign_id: UUID
    draft_id: UUID
    approval_id: UUID
    direction: str
    channel: str
    delivery_mode: str
    recipient_masked: str
    subject: str
    delivery_status: str
    provider: str
    external_message_id: str | None
    idempotency_key: str
    safe_error_code: str | None
    sent_at: datetime | None
    created_at: datetime


class DeliveryAttemptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    message_id: UUID
    attempt_number: int
    result: str
    provider: str
    duration_ms: float
    safe_error_code: str | None
    request_id: str
    created_at: datetime
