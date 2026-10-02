"""Validated DTOs for candidate profile and permission operations."""

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, model_validator

from app.modules.opportunities.schemas import CollaborationFormat, WorkplaceFormat

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class ProfileStatus(StrEnum):
    DRAFT = "draft"
    REVIEW_REQUIRED = "review_required"
    USER_APPROVED = "user_approved"
    VERIFIED = "verified"


class FactType(StrEnum):
    EXPERIENCE = "experience"
    PROJECT = "project"
    SKILL = "skill"
    TECHNOLOGY = "technology"
    LANGUAGE = "language"
    ACHIEVEMENT = "achievement"
    EDUCATION = "education"
    OTHER = "other"


class ContactType(StrEnum):
    EMAIL = "email"
    TELEGRAM = "telegram"
    LINKEDIN = "linkedin"
    GITHUB = "github"
    FACEBOOK = "facebook"
    PHONE = "phone"
    WEBSITE = "website"


class RuleSeverity(StrEnum):
    WARNING = "warning"
    BLOCK = "block"


class SkillGroup(StrEnum):
    BUSINESS = "business"
    MANAGEMENT = "management"
    OPERATIONS = "operations"
    AI = "ai"
    TECHNOLOGY = "technology"
    LANGUAGE = "language"
    OTHER = "other"


class SkillLevel(StrEnum):
    LEARNING = "learning"
    FOUNDATIONAL = "foundational"
    PRACTICAL = "practical"
    PROFICIENT = "proficient"
    ADVANCED = "advanced"


class StrengthType(StrEnum):
    MANAGEMENT = "management"
    ORGANIZATION = "organization"
    NEGOTIATION = "negotiation"
    RESPONSIBILITY = "responsibility"
    PROJECT_LAUNCH = "project_launch"
    STRUCTURING_CHAOS = "structuring_chaos"
    BUSINESS_TECH_BRIDGE = "business_tech_bridge"
    BUSINESS_PROCESS_UNDERSTANDING = "business_process_understanding"
    TEAM_BUILDING = "team_building"
    DELIVERY = "delivery"
    OTHER = "other"


class ConsentDecision(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"


class VerificationDecision(BaseModel):
    version: int = Field(ge=1)
    verified: bool
    confirmed: bool = False

    @model_validator(mode="after")
    def explicit_confirmation(self) -> "VerificationDecision":
        if not self.confirmed:
            raise ValueError("verification change requires explicit owner confirmation")
        return self


class BulkVerificationDecision(BaseModel):
    confirmed: bool = False

    @model_validator(mode="after")
    def explicit_confirmation(self) -> "BulkVerificationDecision":
        if not self.confirmed:
            raise ValueError("bulk verification requires explicit owner confirmation")
        return self


class FactPackPurpose(StrEnum):
    AI_ANALYSIS = "ai_analysis"
    SCORING = "scoring"
    DRAFT = "draft"
    EXTERNAL_SEND = "external_send"
    SIGNATURE = "signature"
    PUBLICATION = "publication"


class PermissionFields(BaseModel):
    store_private: bool = False
    use_for_ai_analysis: bool = False
    use_in_scoring: bool = False
    use_in_draft: bool = False
    send_externally: bool = False
    use_in_signature: bool = False
    publish_publicly: bool = False

    @model_validator(mode="after")
    def validate_dependencies(self) -> "PermissionFields":
        external_permissions = (
            self.use_for_ai_analysis,
            self.use_in_scoring,
            self.use_in_draft,
            self.send_externally,
            self.use_in_signature,
            self.publish_publicly,
        )
        if any(external_permissions) and not self.store_private:
            raise ValueError("store_private is required before any data-use permission")
        if self.send_externally and not self.use_in_draft:
            raise ValueError("use_in_draft is required before send_externally")
        return self


class CandidateProfileUpsert(BaseModel):
    display_name: str | None = Field(default=None, max_length=160)
    professional_title: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    summary: str | None = Field(default=None, max_length=4000)
    total_years_experience: float | None = Field(default=None, ge=0, le=80)
    management_years_experience: float | None = Field(default=None, ge=0, le=80)
    desired_roles: list[str] = Field(default_factory=list, max_length=30)
    adjacent_roles: list[str] = Field(default_factory=list, max_length=30)
    excluded_roles: list[str] = Field(default_factory=list, max_length=30)
    preferred_industries: list[str] = Field(default_factory=list, max_length=50)
    excluded_industries: list[str] = Field(default_factory=list, max_length=50)
    preferred_countries: list[str] = Field(default_factory=list, max_length=30)
    work_formats: list[str] = Field(default_factory=list, max_length=10)
    remote_work_countries: list[str] = Field(default_factory=list, max_length=100)
    relocation_countries: list[str] = Field(default_factory=list, max_length=100)
    business_trip_countries: list[str] = Field(default_factory=list, max_length=100)
    preferred_regions: list[str] = Field(default_factory=list, max_length=100)
    geography_constraints: str | None = Field(default=None, max_length=4000)
    visa_or_sponsorship_required: bool | None = None
    temporary_relocation_allowed: bool = False
    on_the_ground_launch_allowed: bool = False
    collaboration_formats: list[CollaborationFormat] = Field(default_factory=list)
    workplace_formats: list[WorkplaceFormat] = Field(default_factory=list)
    target_income: str | None = Field(default=None, max_length=160)
    desired_responsibility_level: str | None = Field(default=None, max_length=160)
    preferred_company_types: list[str] = Field(default_factory=list, max_length=30)
    preferred_culture: str | None = Field(default=None, max_length=4000)
    language_level: str | None = Field(default=None, max_length=80)
    profile_status: ProfileStatus = ProfileStatus.DRAFT
    version: int | None = Field(default=None, ge=1)


class CandidateProfileRead(CandidateProfileUpsert):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version: int
    created_at: datetime
    updated_at: datetime


class CandidateExperienceCreate(PermissionFields):
    position: ShortText
    organization_label: str | None = Field(default=None, max_length=200)
    industry: str | None = Field(default=None, max_length=160)
    started_at: date | None = None
    ended_at: date | None = None
    project_types: list[str] = Field(default_factory=list, max_length=50)
    responsibility_level: str | None = Field(default=None, max_length=160)
    team_size_max: int | None = Field(default=None, ge=0, le=1_000_000)
    budget_ranges: list[str] = Field(default_factory=list, max_length=20)
    project_geographies: list[str] = Field(default_factory=list, max_length=100)
    contractor_management: bool = False
    negotiations: bool = False
    territory_development: bool = False
    launches: bool = False
    operations_management: bool = False
    crisis_or_complex_situations: str | None = Field(default=None, max_length=4000)
    achievement_fact_ids: list[UUID] = Field(default_factory=list, max_length=100)
    verified: bool = False
    store_private: Literal[True]

    @model_validator(mode="after")
    def dates_are_ordered(self) -> "CandidateExperienceCreate":
        if self.started_at and self.ended_at and self.ended_at < self.started_at:
            raise ValueError("ended_at cannot be before started_at")
        return self


class CandidateExperienceUpdate(BaseModel):
    version: int = Field(ge=1)
    position: ShortText | None = None
    organization_label: str | None = Field(default=None, max_length=200)
    industry: str | None = Field(default=None, max_length=160)
    started_at: date | None = None
    ended_at: date | None = None
    project_types: list[str] | None = Field(default=None, max_length=50)
    responsibility_level: str | None = Field(default=None, max_length=160)
    team_size_max: int | None = Field(default=None, ge=0, le=1_000_000)
    budget_ranges: list[str] | None = Field(default=None, max_length=20)
    project_geographies: list[str] | None = Field(default=None, max_length=100)
    contractor_management: bool | None = None
    negotiations: bool | None = None
    territory_development: bool | None = None
    launches: bool | None = None
    operations_management: bool | None = None
    crisis_or_complex_situations: str | None = Field(default=None, max_length=4000)
    achievement_fact_ids: list[UUID] | None = Field(default=None, max_length=100)
    verified: bool | None = None
    store_private: bool | None = None
    use_for_ai_analysis: bool | None = None
    use_in_scoring: bool | None = None
    use_in_draft: bool | None = None
    send_externally: bool | None = None
    use_in_signature: bool | None = None
    publish_publicly: bool | None = None


class CandidateExperienceRead(CandidateExperienceCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    profile_id: UUID
    version: int
    created_at: datetime
    updated_at: datetime


class CandidateSkillCreate(PermissionFields):
    name: ShortText
    skill_group: SkillGroup
    actual_level: SkillLevel
    duration_months: int | None = Field(default=None, ge=0, le=960)
    evidence: str | None = Field(default=None, max_length=4000)
    implemented_project_fact_ids: list[UUID] = Field(default_factory=list, max_length=100)
    verified_results: str | None = Field(default=None, max_length=4000)
    limitations: str | None = Field(default=None, max_length=4000)
    verified: bool = False
    store_private: Literal[True]

    @model_validator(mode="after")
    def validate_skill_honesty(self) -> "CandidateSkillCreate":
        if self.actual_level in {SkillLevel.PROFICIENT, SkillLevel.ADVANCED} and not self.evidence:
            raise ValueError("proficient and advanced skills require evidence")
        if self.skill_group in {SkillGroup.AI, SkillGroup.TECHNOLOGY} and not self.limitations:
            raise ValueError("AI and technology skills require explicit limitations")
        return self


class CandidateSkillUpdate(BaseModel):
    version: int = Field(ge=1)
    name: ShortText | None = None
    skill_group: SkillGroup | None = None
    actual_level: SkillLevel | None = None
    duration_months: int | None = Field(default=None, ge=0, le=960)
    evidence: str | None = Field(default=None, max_length=4000)
    implemented_project_fact_ids: list[UUID] | None = Field(default=None, max_length=100)
    verified_results: str | None = Field(default=None, max_length=4000)
    limitations: str | None = Field(default=None, max_length=4000)
    verified: bool | None = None
    store_private: bool | None = None
    use_for_ai_analysis: bool | None = None
    use_in_scoring: bool | None = None
    use_in_draft: bool | None = None
    send_externally: bool | None = None
    use_in_signature: bool | None = None
    publish_publicly: bool | None = None


class CandidateSkillRead(CandidateSkillCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    profile_id: UUID
    version: int
    created_at: datetime
    updated_at: datetime


class CandidateStrengthCreate(PermissionFields):
    strength_type: StrengthType
    text: LongText
    evidence: str | None = Field(default=None, max_length=4000)
    verified: bool = False
    priority: int = Field(default=100, ge=0, le=1000)
    store_private: Literal[True]


class CandidateStrengthUpdate(BaseModel):
    version: int = Field(ge=1)
    strength_type: StrengthType | None = None
    text: LongText | None = None
    evidence: str | None = Field(default=None, max_length=4000)
    verified: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=1000)
    store_private: bool | None = None
    use_for_ai_analysis: bool | None = None
    use_in_scoring: bool | None = None
    use_in_draft: bool | None = None
    send_externally: bool | None = None
    use_in_signature: bool | None = None
    publish_publicly: bool | None = None


class CandidateStrengthRead(CandidateStrengthCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    profile_id: UUID
    version: int
    created_at: datetime
    updated_at: datetime


class CandidateFactCreate(PermissionFields):
    fact_type: FactType
    text: LongText
    evidence: str | None = Field(default=None, max_length=4000)
    source_link: HttpUrl | None = None
    verified: bool = False
    store_private: Literal[True]
    sensitivity_level: Literal["private", "sensitive"] = "private"


class CandidateFactUpdate(BaseModel):
    version: int = Field(ge=1)
    fact_type: FactType | None = None
    text: LongText | None = None
    evidence: str | None = Field(default=None, max_length=4000)
    source_link: HttpUrl | None = None
    verified: bool | None = None
    store_private: bool | None = None
    use_for_ai_analysis: bool | None = None
    use_in_scoring: bool | None = None
    use_in_draft: bool | None = None
    send_externally: bool | None = None
    use_in_signature: bool | None = None
    publish_publicly: bool | None = None
    sensitivity_level: Literal["private", "sensitive"] | None = None


class CandidateFactRead(PermissionFields):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    profile_id: UUID
    fact_type: str
    text: str
    evidence: str | None
    source_link: str | None
    verified: bool
    sensitivity_level: str
    version: int
    created_at: datetime
    updated_at: datetime


class CandidateContactCreate(PermissionFields):
    contact_type: ContactType
    value: ShortText
    verified: bool = False
    store_private: Literal[True]
    allowed_in_signature: bool = False


class CandidateContactUpdate(BaseModel):
    version: int = Field(ge=1)
    contact_type: ContactType | None = None
    value: ShortText | None = None
    verified: bool | None = None
    store_private: bool | None = None
    use_for_ai_analysis: bool | None = None
    use_in_scoring: bool | None = None
    use_in_draft: bool | None = None
    send_externally: bool | None = None
    use_in_signature: bool | None = None
    publish_publicly: bool | None = None
    allowed_in_signature: bool | None = None


class CandidateContactRead(PermissionFields):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    profile_id: UUID
    contact_type: str
    value: str
    verified: bool
    allowed_in_signature: bool
    version: int
    created_at: datetime
    updated_at: datetime


class CandidateRuleCreate(BaseModel):
    rule_type: ShortText
    text: LongText
    severity: RuleSeverity = RuleSeverity.BLOCK
    active: bool = True
    priority: int = Field(default=100, ge=0, le=1000)


class CandidateRuleRead(CandidateRuleCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    profile_id: UUID
    created_at: datetime
    updated_at: datetime


class ConsentEventCreate(BaseModel):
    action_type: ShortText
    data_scope: ShortText
    entity_type: ShortText
    entity_id: UUID | None = None
    destination: str | None = Field(default=None, max_length=240)
    decision: ConsentDecision
    expires_at: datetime | None = None
    comment: str | None = Field(default=None, max_length=1000)


class ConsentEventRead(ConsentEventCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    request_id: str
    granted_at: datetime


class FactPackFact(BaseModel):
    id: UUID
    fact_type: str
    text: str
    evidence: str | None
    source_link: str | None


class FactPackContact(BaseModel):
    id: UUID
    contact_type: str
    value: str
    allowed_in_signature: bool


class FactPackRule(BaseModel):
    id: UUID
    rule_type: str
    text: str
    severity: str
    priority: int


class FactPackPreview(BaseModel):
    purpose: FactPackPurpose
    profile_version: int
    facts: list[FactPackFact]
    contacts: list[FactPackContact]
    rules: list[FactPackRule]
    excluded_fact_ids: list[UUID]
    excluded_contact_ids: list[UUID]
