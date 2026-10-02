"""Contracts for deterministic scoring and owner overrides."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


class ScoringWeights(BaseModel):
    core_fit: float = Field(default=0.40, ge=0, le=1)
    format_fit_score: float = Field(default=0.15, ge=0, le=1)
    geography_fit_score: float = Field(default=0.10, ge=0, le=1)
    timing_signal_score: float = Field(default=0.10, ge=0, le=1)
    contactability_score: float = Field(default=0.10, ge=0, le=1)
    value_proposition_realism: float = Field(default=0.15, ge=0, le=1)

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> "ScoringWeights":
        if abs(sum(self.model_dump().values()) - 1.0) > 0.000001:
            raise ValueError("Scoring weights must sum to 1.0")
        return self


class RelevanceCalculationRequest(BaseModel):
    weights: ScoringWeights = Field(default_factory=ScoringWeights)


class AssessmentOverrideCreate(BaseModel):
    overridden_score: float = Field(ge=0, le=100)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=4000)]


class AssessmentOverrideRead(AssessmentOverrideCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    assessment_id: UUID
    original_score: float
    request_id: str
    created_at: datetime


class ScoringThresholds(BaseModel):
    opportunity_identified: float
    needs_review: float
    formula_version: str
