"""Enums and DTOs for opportunity classification, assessment and owner decisions."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, model_validator

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
LongText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=6000),
]


class OpportunityType(StrEnum):
    OPEN_VACANCY = "open_vacancy"
    BUSINESS_EXPANSION = "business_expansion"
    MARKET_ENTRY = "market_entry"
    OPERATIONS_IMPROVEMENT = "operations_improvement"
    AI_ADOPTION = "ai_adoption"
    PROCESS_AUTOMATION = "process_automation"
    NEW_PRODUCT_OR_DIRECTION = "new_product_or_direction"
    ACTIVE_HIRING = "active_hiring"
    INVESTMENT_OR_GROWTH = "investment_or_growth"
    PROJECT_WORK = "project_work"
    CONSULTING = "consulting"
    LOCAL_REPRESENTATION = "local_representation"
    GENERAL_COMPETENCE_FIT = "general_competence_fit"
    HYBRID_OPPORTUNITY = "hybrid_opportunity"


class OpportunitySignalType(StrEnum):
    OPEN_VACANCY = "open_vacancy"
    MARKET_ENTRY = "market_entry"
    OFFICE_OPENING = "office_opening"
    BRANCH_OPENING = "branch_opening"
    INVESTMENT = "investment"
    PRODUCT_LAUNCH = "product_launch"
    SCALING = "scaling"
    ACTIVE_HIRING = "active_hiring"
    AI_ADOPTION = "ai_adoption"
    PROCESS_AUTOMATION = "process_automation"
    LEADERSHIP_CHANGE = "leadership_change"
    PARTNERSHIP_PROGRAM = "partnership_program"
    FRANCHISE_DEVELOPMENT = "franchise_development"
    MAJOR_NEW_PROJECT = "major_new_project"
    INTERNATIONAL_EXPANSION = "international_expansion"
    LEADERSHIP_GOAL_OR_PROBLEM = "leadership_goal_or_problem"
    GENERAL_COMPETENCE_MATCH = "general_competence_match"


class EvidenceStatus(StrEnum):
    PROPOSED = "proposed"
    EXTRACTED = "extracted"
    VERIFIED = "verified"
    REJECTED = "rejected"
    STALE = "stale"


class PositioningStrategy(StrEnum):
    BUSINESS_FIRST = "business_first"
    AI_FIRST = "ai_first"
    HYBRID = "hybrid"


class CollaborationFormat(StrEnum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    PROJECT_BASED = "project_based"
    CONTRACT = "contract"
    CONSULTING = "consulting"
    ADVISORY = "advisory"
    TEMPORARY_LAUNCH_ROLE = "temporary_launch_role"
    LOCAL_REPRESENTATIVE = "local_representative"
    BUSINESS_DEVELOPMENT = "business_development"
    OPERATIONS_MANAGEMENT = "operations_management"


class WorkplaceFormat(StrEnum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ON_SITE = "on_site"
    RELOCATION = "relocation"


class OpportunityDecision(StrEnum):
    PENDING = "pending"
    OUTREACH = "outreach"
    DEFER = "defer"
    DEEPER_RESEARCH = "deeper_research"
    NOT_RELEVANT = "not_relevant"
    WATCHLIST = "watchlist"


class DecisionMakerRole(StrEnum):
    CEO = "ceo"
    FOUNDER = "founder"
    CO_FOUNDER = "co_founder"
    COO = "coo"
    MANAGING_DIRECTOR = "managing_director"
    COUNTRY_MANAGER = "country_manager"
    REGIONAL_DIRECTOR = "regional_director"
    HEAD_OF_OPERATIONS = "head_of_operations"
    HEAD_OF_EXPANSION = "head_of_expansion"
    HEAD_OF_BUSINESS_DEVELOPMENT = "head_of_business_development"
    HEAD_OF_PROJECTS = "head_of_projects"
    HEAD_OF_TRANSFORMATION = "head_of_transformation"
    CTO = "cto"
    HEAD_OF_AI = "head_of_ai"
    HEAD_OF_AUTOMATION = "head_of_automation"
    HEAD_OF_PRODUCT = "head_of_product"
    RECRUITER = "recruiter"
    TALENT_ACQUISITION = "talent_acquisition"
    HIRING_MANAGER = "hiring_manager"


class CompanySourceCreate(BaseModel):
    url: HttpUrl
    source_type: ShortText
    fetched_at: datetime | None = None
    http_status: int | None = Field(default=None, ge=100, le=599)
    content_hash: str | None = Field(default=None, max_length=128)
    extracted_text: str | None = Field(default=None, max_length=100_000)
    language: str | None = Field(default=None, max_length=20)
    trust_level: str = Field(default="unverified", max_length=30)
    freshness_status: str = Field(default="unknown", max_length=30)
    error: str | None = Field(default=None, max_length=4000)


class CompanySourceRead(CompanySourceCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    version: int
    created_at: datetime
    updated_at: datetime


class OpportunitySignalCreate(BaseModel):
    signal_type: OpportunitySignalType
    title: ShortText
    description: LongText
    source_id: UUID | None = None
    detected_at: datetime
    effective_at: datetime | None = None
    confidence: float = Field(ge=0, le=1)
    exact_fragment: str | None = Field(default=None, max_length=4000)
    status: EvidenceStatus = EvidenceStatus.PROPOSED

    @model_validator(mode="after")
    def verified_signal_requires_provenance(self) -> "OpportunitySignalCreate":
        if self.status == EvidenceStatus.VERIFIED and (
            self.source_id is None or not self.exact_fragment
        ):
            raise ValueError("verified signals require source_id and exact_fragment")
        return self


class OpportunitySignalUpdate(BaseModel):
    version: int = Field(ge=1)
    title: ShortText | None = None
    description: LongText | None = None
    source_id: UUID | None = None
    effective_at: datetime | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    exact_fragment: str | None = Field(default=None, max_length=4000)
    status: EvidenceStatus | None = None


class OpportunitySignalRead(OpportunitySignalCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    version: int
    created_at: datetime
    updated_at: datetime


class CompanyOpportunityCreate(BaseModel):
    opportunity_type: OpportunityType
    rationale: LongText
    confidence: float = Field(ge=0, le=1)
    source_ids: list[UUID] = Field(default_factory=list, max_length=100)
    signal_ids: list[UUID] = Field(default_factory=list, max_length=100)
    status: EvidenceStatus = EvidenceStatus.PROPOSED

    @model_validator(mode="after")
    def verified_opportunity_requires_evidence(self) -> "CompanyOpportunityCreate":
        if self.status == EvidenceStatus.VERIFIED and not (self.source_ids or self.signal_ids):
            raise ValueError("verified opportunities require a source or signal")
        return self


class CompanyOpportunityUpdate(BaseModel):
    version: int = Field(ge=1)
    rationale: LongText | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    source_ids: list[UUID] | None = Field(default=None, max_length=100)
    signal_ids: list[UUID] | None = Field(default=None, max_length=100)
    status: EvidenceStatus | None = None


class CompanyOpportunityRead(CompanyOpportunityCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    version: int
    created_at: datetime
    updated_at: datetime


class ScoreContribution(BaseModel):
    factor: ShortText
    points: float
    rationale: ShortText
    candidate_fact_ids: list[UUID] = Field(default_factory=list)
    company_fact_ids: list[UUID] = Field(default_factory=list)
    source_ids: list[UUID] = Field(default_factory=list)


class ScoreBreakdown(BaseModel):
    formula_version: str = Field(min_length=1, max_length=80)
    weights: dict[str, float]
    contributions: dict[str, list[ScoreContribution]]
    excluded_inputs: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class OpportunityAssessmentCreate(BaseModel):
    candidate_profile_version: int = Field(ge=1)
    business_fit_score: float = Field(ge=0, le=100)
    ai_automation_fit_score: float = Field(ge=0, le=100)
    hybrid_fit_score: float = Field(ge=0, le=100)
    format_fit_score: float = Field(ge=0, le=100)
    geography_fit_score: float = Field(ge=0, le=100)
    timing_signal_score: float = Field(ge=0, le=100)
    contactability_score: float = Field(ge=0, le=100)
    overall_opportunity_score: float = Field(ge=0, le=100)
    score_breakdown: ScoreBreakdown
    opportunity_ids: list[UUID] = Field(default_factory=list)
    candidate_fact_ids: list[UUID] = Field(default_factory=list)
    company_fact_ids: list[UUID] = Field(default_factory=list)
    opportunity_signal_ids: list[UUID] = Field(default_factory=list)
    source_ids: list[UUID] = Field(default_factory=list)
    possible_business_tasks: list[str] = Field(default_factory=list)
    candidate_value_hypotheses: list[str] = Field(default_factory=list)
    recommended_collaboration_formats: list[CollaborationFormat] = Field(default_factory=list)
    recommended_workplace_formats: list[WorkplaceFormat] = Field(default_factory=list)
    possible_roles: list[str] = Field(default_factory=list)
    reasons_to_contact: list[str] = Field(default_factory=list)
    reasons_not_to_contact: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_action: str | None = Field(default=None, max_length=500)
    model_or_rule_version: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_formula_version(self) -> "OpportunityAssessmentCreate":
        if self.score_breakdown.formula_version != self.model_or_rule_version:
            raise ValueError("score breakdown and assessment formula versions must match")
        return self


class OpportunityAssessmentRead(OpportunityAssessmentCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    created_at: datetime


class PositioningRecommendationCreate(BaseModel):
    assessment_id: UUID
    primary_strategy: PositioningStrategy
    primary_message_line: LongText
    secondary_advantage: LongText
    rationale: LongText
    value_proposition: LongText
    concrete_first_message_offer: LongText
    primary_decision_maker_role: DecisionMakerRole
    secondary_decision_maker_role: DecisionMakerRole
    collaboration_format: CollaborationFormat
    workplace_formats: list[WorkplaceFormat] = Field(default_factory=list)
    possible_role: ShortText

    @model_validator(mode="after")
    def validate_recommendation(self) -> "PositioningRecommendationCreate":
        if self.primary_decision_maker_role == self.secondary_decision_maker_role:
            raise ValueError("primary and secondary decision-makers must differ")
        if self.primary_strategy == PositioningStrategy.HYBRID and (
            not self.primary_message_line or not self.secondary_advantage
        ):
            raise ValueError("hybrid positioning requires primary and secondary message lines")
        return self


class PositioningRecommendationRead(PositioningRecommendationCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    user_decision: OpportunityDecision = OpportunityDecision.PENDING
    version: int
    decided_at: datetime | None
    created_at: datetime
    updated_at: datetime


class OpportunityDecisionCreate(BaseModel):
    version: int = Field(ge=1)
    decision: OpportunityDecision
    confirmed: bool = False
    comment: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def outreach_requires_explicit_confirmation(self) -> "OpportunityDecisionCreate":
        if self.decision == OpportunityDecision.OUTREACH and not self.confirmed:
            raise ValueError("outreach requires explicit confirmation")
        return self


class OpportunityDecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    recommendation_id: UUID
    decision: OpportunityDecision
    confirmed: bool
    comment: str | None
    request_id: str
    decided_at: datetime


class OpportunityResultRead(BaseModel):
    company_id: UUID
    summary: LongText
    opportunity_types: list[OpportunityType]
    signals: list[OpportunitySignalRead]
    assessment: OpportunityAssessmentRead
    recommendation: PositioningRecommendationRead
    has_open_vacancy: bool
    user_decision: OpportunityDecision
    draft_generation_allowed: bool = False

    @model_validator(mode="after")
    def enforce_draft_decision_gate(self) -> "OpportunityResultRead":
        if self.draft_generation_allowed and self.user_decision != OpportunityDecision.OUTREACH:
            raise ValueError("draft generation requires an outreach decision")
        return self
