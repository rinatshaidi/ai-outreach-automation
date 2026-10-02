"""DTOs for owner-controlled profile review, import and pilot calibration."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProfileSectionType(StrEnum):
    POSITIONING = "positioning"
    TITLE_SUMMARY = "title_summary"
    MANAGEMENT_BUSINESS_EXPERIENCE = "management_business_experience"
    ROLES_PERIODS_INDUSTRIES = "roles_periods_industries"
    PROJECTS_ACHIEVEMENTS = "projects_achievements"
    TEAMS_BUDGETS_RESPONSIBILITY = "teams_budgets_responsibility"
    EXPERIENCE_GEOGRAPHY = "experience_geography"
    CONTRACTORS_PARTNERS_NEGOTIATIONS = "contractors_partners_negotiations"
    AI_PROJECTS = "ai_projects"
    TECHNICAL_SKILLS = "technical_skills"
    STRENGTHS = "strengths"
    DESIRED_ADJACENT_ROLES = "desired_adjacent_roles"
    EXCLUDED_ROLES = "excluded_roles"
    EMPLOYMENT_PROJECT_FORMATS = "employment_project_formats"
    CONSULTING_CONTRACT = "consulting_contract"
    WORKPLACE_FORMATS = "workplace_formats"
    RELOCATION_TRAVEL = "relocation_travel"
    COUNTRIES_REGIONS = "countries_regions"
    INCOME_CONSTRAINTS = "income_constraints"
    LANGUAGES = "languages"
    CONTACTS = "contacts"
    POSITIONING_CONSTRAINTS = "positioning_constraints"
    PERMISSIONS_CONSENT = "permissions_consent"


class ProfileSectionStatus(StrEnum):
    DRAFT = "draft"
    REVIEW_REQUIRED = "review_required"
    USER_APPROVED = "user_approved"
    VERIFIED = "verified"


class ReviewDecision(StrEnum):
    APPROVE = "approve"
    VERIFY = "verify"
    CORRECT = "correct"
    DEFER = "defer"
    REJECT = "reject"


class ProfileSectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    profile_id: UUID
    section_type: str
    status: str
    content_draft: str | None
    content_hash: str | None
    version: int
    user_comment: str | None
    approved_at: datetime | None
    verified_at: datetime | None
    approved_by: str | None
    created_at: datetime
    updated_at: datetime


class ProfileSectionReview(BaseModel):
    version: int = Field(ge=1)
    decision: ReviewDecision
    comment: str | None = Field(default=None, max_length=4000)
    content_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class CandidateRecordVerification(BaseModel):
    section_type: ProfileSectionType
    version: int = Field(ge=1)
    confirmed: Literal[True]
    comment: str | None = Field(default=None, min_length=3, max_length=4000)


class ImportItemInput(BaseModel):
    section_type: ProfileSectionType
    entity_type: Literal["fact", "contact", "experience", "skill", "strength"]
    data: dict[str, Any]


class ProfileImportCreate(BaseModel):
    source_filename: str = Field(min_length=1, max_length=240)
    items: list[ImportItemInput] = Field(min_length=1, max_length=500)


class ImportItemDecision(BaseModel):
    version: int = Field(ge=1)
    decision: Literal["approved", "corrected", "deferred", "rejected"]
    corrected_data: dict[str, Any] | None = None


class ImportSectionDecision(BaseModel):
    decision: Literal["approved", "deferred", "rejected"]


class ProfileImportItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    batch_id: UUID
    section_type: str
    operation: str
    target_entity_type: str
    target_entity_id: UUID | None
    proposed_data: dict[str, Any]
    current_data_snapshot: dict[str, Any] | None
    validation_messages: list[str]
    default_permissions: dict[str, bool]
    decision: str
    applied_entity_id: UUID | None
    version: int


class ProfileImportBatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    profile_id: UUID
    source_filename: str
    source_format: str
    source_hash: str
    status: str
    validation_report: dict[str, Any]
    created_at: datetime
    reviewed_at: datetime | None
    applied_at: datetime | None
    items: list[ProfileImportItemRead] = Field(default_factory=list)


class CalibrationNoteCreate(BaseModel):
    company_id: UUID | None = None
    category: Literal[
        "score_high",
        "score_low",
        "profile_gap",
        "positioning",
        "work_format",
        "management_understated",
        "ai_overstated",
        "sources",
        "contact",
        "draft_quality",
        "other",
    ]
    observation: str = Field(min_length=1, max_length=4000)
    proposed_change: str | None = Field(default=None, max_length=4000)


class CalibrationNoteRead(CalibrationNoteCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    rule_version: str | None
    created_at: datetime
    resolved_at: datetime | None
