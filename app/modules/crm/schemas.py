"""Validated DTOs for the Mini-CRM API."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.modules.opportunities.schemas import (
    CollaborationFormat,
    DecisionMakerRole,
    OpportunityType,
    PositioningStrategy,
    WorkplaceFormat,
)

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]


class PipelineStatus(StrEnum):
    NEW = "new"
    RESEARCH_PENDING = "research_pending"
    RESEARCHED = "researched"
    OPPORTUNITY_IDENTIFIED = "opportunity_identified"
    STRATEGY_SELECTED = "strategy_selected"
    DECISION_PENDING = "decision_pending"
    APPROVED_FOR_OUTREACH = "approved_for_outreach"
    DEFERRED = "deferred"
    WATCHLIST = "watchlist"
    NEEDS_REVIEW = "needs_review"
    NOT_RELEVANT = "not_relevant"
    CONTACT_FOUND = "contact_found"
    CONTACT_MISSING = "contact_missing"
    CONTACT_RESEARCH_REQUIRED = "contact_research_required"
    DRAFT_READY = "draft_ready"
    REVIEW = "review"
    APPROVED = "approved"
    SENT = "sent"
    WAITING_REPLY = "waiting_reply"
    REPLIED = "replied"
    INTERVIEW = "interview"
    PROJECT_DISCUSSION = "project_discussion"
    CONSULTING_DISCUSSION = "consulting_discussion"
    REJECTED = "rejected"
    OFFER = "offer"
    AGREEMENT = "agreement"
    CLOSED = "closed"


class RelevanceStatus(StrEnum):
    UNSCORED = "unscored"
    OPPORTUNITY_IDENTIFIED = "opportunity_identified"
    NEEDS_REVIEW = "needs_review"
    NOT_RELEVANT = "not_relevant"


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    VERIFIED_PUBLIC = "verified_public"
    PROVIDER_VERIFIED = "provider_verified"
    INVALID = "invalid"
    SUPPRESSED = "suppressed"
    # Backward-compatible value from v1.2 records.
    VERIFIED = "verified"
    REJECTED = "rejected"


class ContactValidationStatus(StrEnum):
    VERIFIED = "VERIFIED_CONTACT"
    PARTIAL = "PARTIAL_CONTACT"
    UNVERIFIED = "UNVERIFIED_CONTACT"
    INVALID = "INVALID_CONTACT"


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class CampaignTone(StrEnum):
    PROFESSIONAL = "professional"
    FRIENDLY = "friendly"


class CompanyCreate(BaseModel):
    name: ShortText
    normalized_domain: str = Field(min_length=1, max_length=253)
    is_synthetic: bool = False
    country: str | None = Field(default=None, max_length=120)
    operating_regions: list[str] = Field(default_factory=list, max_length=100)
    industry: str | None = Field(default=None, max_length=160)
    company_size: str | None = Field(default=None, max_length=80)
    maturity_stage: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=6000)
    language_signals: list[str] = Field(default_factory=list, max_length=20)
    opportunity_types: list[OpportunityType] = Field(default_factory=list)
    recommended_positioning: PositioningStrategy | None = None
    recommended_collaboration_formats: list[CollaborationFormat] = Field(default_factory=list)
    recommended_workplace_formats: list[WorkplaceFormat] = Field(default_factory=list)
    recommended_role: str | None = Field(default=None, max_length=240)
    business_fit_score: float | None = Field(default=None, ge=0, le=100)
    ai_automation_fit_score: float | None = Field(default=None, ge=0, le=100)
    hybrid_fit_score: float | None = Field(default=None, ge=0, le=100)
    format_fit_score: float | None = Field(default=None, ge=0, le=100)
    geography_fit_score: float | None = Field(default=None, ge=0, le=100)
    timing_signal_score: float | None = Field(default=None, ge=0, le=100)
    contactability_score: float | None = Field(default=None, ge=0, le=100)
    overall_opportunity_score: float | None = Field(default=None, ge=0, le=100)
    relevance_score: float | None = Field(default=None, ge=0, le=100)
    relevance_status: RelevanceStatus = RelevanceStatus.UNSCORED
    pipeline_status: PipelineStatus = PipelineStatus.NEW
    next_action: str | None = Field(default=None, max_length=240)
    note: str | None = Field(default=None, max_length=4000)

    @field_validator("normalized_domain")
    @classmethod
    def normalize_domain(cls, value: str) -> str:
        domain = value.strip().lower().removeprefix("https://").removeprefix("http://")
        domain = domain.split("/", maxsplit=1)[0].rstrip(".")
        if not domain or "." not in domain or " " in domain:
            raise ValueError("a valid bare domain is required")
        return domain


class CompanyUpdate(BaseModel):
    version: int = Field(ge=1)
    name: ShortText | None = None
    normalized_domain: str | None = Field(default=None, min_length=1, max_length=253)
    is_synthetic: bool | None = None
    country: str | None = Field(default=None, max_length=120)
    operating_regions: list[str] | None = Field(default=None, max_length=100)
    industry: str | None = Field(default=None, max_length=160)
    company_size: str | None = Field(default=None, max_length=80)
    maturity_stage: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=6000)
    language_signals: list[str] | None = Field(default=None, max_length=20)
    opportunity_types: list[OpportunityType] | None = None
    recommended_positioning: PositioningStrategy | None = None
    recommended_collaboration_formats: list[CollaborationFormat] | None = None
    recommended_workplace_formats: list[WorkplaceFormat] | None = None
    recommended_role: str | None = Field(default=None, max_length=240)
    relevance_score: float | None = Field(default=None, ge=0, le=100)
    relevance_status: RelevanceStatus | None = None
    pipeline_status: PipelineStatus | None = None
    next_action: str | None = Field(default=None, max_length=240)
    note: str | None = Field(default=None, max_length=4000)

    @field_validator("normalized_domain")
    @classmethod
    def normalize_domain(cls, value: str | None) -> str | None:
        return None if value is None else CompanyCreate.normalize_domain(value)


class CompanyRead(CompanyCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version: int
    last_researched_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ContactCreate(BaseModel):
    company_id: UUID
    name: ShortText
    role: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    telegram: str | None = Field(default=None, max_length=160)
    linkedin: HttpUrl | None = None
    other_public_link: HttpUrl | None = None
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    confidence: float | None = Field(default=None, ge=0, le=1)
    lawful_public_source_note: str | None = Field(default=None, max_length=2000)
    decision_maker_role: DecisionMakerRole | None = None
    decision_priority: int | None = Field(default=None, ge=1, le=2)
    source_id: UUID | None = None
    do_not_contact: bool = False

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        email = value.strip().lower()
        if email.count("@") != 1 or "." not in email.rsplit("@", maxsplit=1)[1]:
            raise ValueError("a valid email is required")
        return email

    @model_validator(mode="after")
    def require_public_channel(self) -> "ContactCreate":
        if not any((self.email, self.telegram, self.linkedin, self.other_public_link)):
            raise ValueError("at least one public professional contact channel is required")
        if (
            self.verification_status
            in {
                VerificationStatus.VERIFIED,
                VerificationStatus.VERIFIED_PUBLIC,
                VerificationStatus.PROVIDER_VERIFIED,
            }
            and not self.lawful_public_source_note
        ):
            raise ValueError("verified contacts require a lawful public source note")
        return self


class ContactUpdate(BaseModel):
    version: int = Field(ge=1)
    name: ShortText | None = None
    role: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    telegram: str | None = Field(default=None, max_length=160)
    linkedin: HttpUrl | None = None
    other_public_link: HttpUrl | None = None
    verification_status: VerificationStatus | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    lawful_public_source_note: str | None = Field(default=None, max_length=2000)
    decision_maker_role: DecisionMakerRole | None = None
    decision_priority: int | None = Field(default=None, ge=1, le=2)
    source_id: UUID | None = None
    do_not_contact: bool | None = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        return ContactCreate.normalize_email(value)


class ContactRead(ContactCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version: int
    validation_status: ContactValidationStatus
    validated_at: datetime | None
    validation_http_status: int | None
    validation_final_url: HttpUrl | None
    validation_error: str | None
    created_at: datetime
    updated_at: datetime


class JobCreate(BaseModel):
    company_id: UUID
    source_id: UUID | None = None
    title: ShortText
    location: str | None = Field(default=None, max_length=200)
    url: HttpUrl
    description: str | None = Field(default=None, max_length=10000)
    required_skills: list[str] = Field(default_factory=list, max_length=100)
    published_at: datetime | None = None
    active: bool = True


class JobUpdate(BaseModel):
    version: int = Field(ge=1)
    title: ShortText | None = None
    location: str | None = Field(default=None, max_length=200)
    url: HttpUrl | None = None
    description: str | None = Field(default=None, max_length=10000)
    required_skills: list[str] | None = Field(default=None, max_length=100)
    published_at: datetime | None = None
    active: bool | None = None
    source_id: UUID | None = None


class JobRead(JobCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version: int
    detected_at: datetime
    created_at: datetime
    updated_at: datetime


class CampaignCreate(BaseModel):
    name: ShortText
    goal: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    criteria: dict[str, Any] = Field(default_factory=dict)
    opportunity_types: list[OpportunityType] = Field(default_factory=list)
    positioning_strategies: list[PositioningStrategy] = Field(default_factory=list)
    collaboration_formats: list[CollaborationFormat] = Field(default_factory=list)
    preferred_language: str = Field(default="auto", max_length=20)
    tone_defaults: CampaignTone = CampaignTone.PROFESSIONAL
    daily_limit: int = Field(default=10, ge=0, le=500)
    followup_policy: dict[str, Any] = Field(default_factory=dict)
    status: CampaignStatus = CampaignStatus.DRAFT


class CampaignUpdate(BaseModel):
    version: int = Field(ge=1)
    name: ShortText | None = None
    goal: str | None = Field(default=None, min_length=1, max_length=4000)
    criteria: dict[str, Any] | None = None
    opportunity_types: list[OpportunityType] | None = None
    positioning_strategies: list[PositioningStrategy] | None = None
    collaboration_formats: list[CollaborationFormat] | None = None
    preferred_language: str | None = Field(default=None, max_length=20)
    tone_defaults: CampaignTone | None = None
    daily_limit: int | None = Field(default=None, ge=0, le=500)
    followup_policy: dict[str, Any] | None = None
    status: CampaignStatus | None = None


class CampaignRead(CampaignCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version: int
    created_at: datetime
    updated_at: datetime


class TimelineEventCreate(BaseModel):
    company_id: UUID
    contact_id: UUID | None = None
    event_type: ShortText
    occurred_at: datetime | None = None
    summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class TimelineEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    contact_id: UUID | None
    event_type: str
    occurred_at: datetime
    summary: str
    metadata_json: dict[str, Any]
    created_at: datetime


class PageMeta(BaseModel):
    page: int
    page_size: int
    total: int
    pages: int


class CompanyPage(BaseModel):
    items: list[CompanyRead]
    meta: PageMeta


class DashboardSummary(BaseModel):
    companies: int
    researched: int
    opportunities_identified: int
    opportunities_with_vacancy: int
    opportunities_without_vacancy: int
    business_first: int
    ai_first: int
    hybrid: int
    remote_opportunities: int
    relocation_opportunities: int
    project_opportunities: int
    watchlist: int
    decision_pending: int
    verified_contacts: int
    active_jobs: int
    active_campaigns: int
    waiting_review: int
    sent: int
    replies: int
    interviews: int
    project_discussions: int
    consulting_discussions: int
    offers_or_agreements: int
    followups_due: int
    recent_events: list[TimelineEventRead]
