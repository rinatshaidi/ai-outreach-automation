"""Structured contracts for safe A/B draft generation."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


class DraftVariant(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class DraftTone(StrEnum):
    PROFESSIONAL = "professional"
    FRIENDLY = "friendly"


class DraftFormat(StrEnum):
    EXPANDED = "expanded"
    SHORT = "short"


class DraftStatus(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"


class ValidationSeverity(StrEnum):
    BLOCK = "block"
    WARNING = "warning"


class ValidationIssue(BaseModel):
    code: str
    severity: ValidationSeverity
    message: str


class ValidationReport(BaseModel):
    passed: bool
    issues: list[ValidationIssue] = Field(default_factory=list)


class GenerationCreate(BaseModel):
    contact_id: UUID
    recommendation_id: UUID
    campaign_goal: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)
    ]
    language: str = Field(default="auto", pattern=r"^(auto|en|ru)$")
    min_words: int = Field(default=120, ge=40, le=300)
    max_words: int = Field(default=250, ge=40, le=300)
    prompt_version: str = Field(default="outreach-generation-v2", min_length=1, max_length=80)

    @model_validator(mode="after")
    def valid_word_range(self) -> "GenerationCreate":
        if self.min_words > self.max_words:
            raise ValueError("min_words cannot exceed max_words")
        return self


class AdapterDraft(BaseModel):
    variant: DraftVariant
    message_format: DraftFormat
    tone: DraftTone
    subject: str = Field(min_length=1, max_length=240)
    body: str = Field(min_length=1)
    language: str
    explanation: str
    opportunity_type_ids: list[UUID]
    opportunity_signal_ids: list[UUID]
    positioning_strategy: str
    collaboration_format: str
    value_proposition: str
    candidate_fact_ids: list[UUID]
    company_fact_ids: list[UUID]
    source_ids: list[UUID]
    warnings: list[str] = Field(default_factory=list)


class MessageDraftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    generation_run_id: UUID
    company_id: UUID
    contact_id: UUID
    contact_version: int
    recommendation_id: UUID
    assessment_id: UUID
    revision: int
    variant: DraftVariant
    message_format: DraftFormat
    tone: DraftTone
    status: DraftStatus
    subject: str
    body: str
    language: str
    language_confidence: float
    language_reason: str
    explanation: str
    opportunity_type_ids: list[UUID]
    opportunity_signal_ids: list[UUID]
    positioning_strategy: str
    collaboration_format: str
    value_proposition: str
    candidate_fact_ids: list[UUID]
    company_fact_ids: list[UUID]
    source_ids: list[UUID]
    warnings: list[str]
    validation_report: dict[str, Any]
    word_count: int
    prompt_version: str
    provider: str
    model: str
    content_hash: str
    created_at: datetime


class GenerationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    contact_id: UUID
    recommendation_id: UUID
    assessment_id: UUID
    status: str
    prompt_version: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    input_entity_ids: dict[str, Any]
    validation_summary: dict[str, Any]
    request_id: str
    created_at: datetime
    drafts: list[MessageDraftRead] = Field(default_factory=list)


class SenderVoiceProfileUpsert(BaseModel):
    communication_style: list[str] = Field(default_factory=list)
    values: list[str] = Field(default_factory=list)
    motivations: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    preferred_tone: str = Field(default="personal", min_length=1, max_length=80)
    preferred_openings: dict[str, list[str]] = Field(default_factory=dict)
    things_to_avoid: list[str] = Field(default_factory=list)
    active: bool = True


class SenderVoiceProfileRead(SenderVoiceProfileUpsert):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    candidate_profile_id: UUID
    version: int
    created_at: datetime
    updated_at: datetime


class ApprovedWritingExampleCreate(BaseModel):
    language: str = Field(pattern=r"^(en|ru)$")
    company_context: str = Field(min_length=1, max_length=300)
    purpose: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=20, max_length=20_000)
    approved: bool = False
    confirmed: bool = False
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def approved_requires_confirmation(self) -> "ApprovedWritingExampleCreate":
        if self.approved and not self.confirmed:
            raise ValueError("approved style examples require explicit owner confirmation")
        return self


class ApprovedWritingExampleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sender_voice_profile_id: UUID
    language: str
    company_context: str
    purpose: str
    text: str
    approved: bool
    notes: str | None
    created_at: datetime


class DraftEditCreate(BaseModel):
    revision: int = Field(ge=1)
    subject: str = Field(min_length=1, max_length=240)
    body: str = Field(min_length=1, max_length=20_000)
    comment: str | None = Field(default=None, max_length=2000)


class DraftRegenerateCreate(BaseModel):
    revision: int = Field(ge=1)
    campaign_goal: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)
    ]
    language: str = Field(default="same", pattern=r"^(same|en|ru)$")
    comment: str | None = Field(default=None, max_length=2000)


class DraftRestoreCreate(BaseModel):
    revision: int = Field(ge=1)
    source_draft_id: UUID
    confirmed: bool = False
    comment: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def explicit_confirmation(self) -> "DraftRestoreCreate":
        if not self.confirmed:
            raise ValueError("revision restore requires explicit confirmation")
        return self


class DraftRecipientChange(BaseModel):
    revision: int = Field(ge=1)
    contact_id: UUID
    confirmed: bool = False
    comment: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def explicit_confirmation(self) -> "DraftRecipientChange":
        if not self.confirmed:
            raise ValueError("recipient change requires explicit confirmation")
        return self


class DraftReviewDecisionCreate(BaseModel):
    revision: int = Field(ge=1)
    confirmed: bool = False
    comment: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def explicit_confirmation(self) -> "DraftReviewDecisionCreate":
        if not self.confirmed:
            raise ValueError("review decision requires explicit confirmation")
        return self


class DraftApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    draft_id: UUID
    draft_revision: int
    decision: str
    approved_by: str
    approved_at: datetime
    comment: str | None
    consumed_at: datetime | None
    invalidated_at: datetime | None
    invalidation_reason: str | None
    request_id: str
    valid: bool = False
    validity_reason: str = "unchecked"
    approval_token: str | None = None


class DraftReviewEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    draft_id: UUID
    action: str
    actor: str
    comment: str | None
    safe_diff: dict[str, Any]
    request_id: str
    created_at: datetime


class ReviewDraftDetail(BaseModel):
    current: MessageDraftRead
    revisions: list[MessageDraftRead]
    approvals: list[DraftApprovalRead]
    events: list[DraftReviewEventRead]
    company_name: str
    contact_name: str
    relevance_score: float | None
    positioning_context: dict[str, Any]
    sources: list[dict[str, Any]]
    candidate_permissions: list[dict[str, Any]]
