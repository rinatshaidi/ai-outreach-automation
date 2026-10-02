"""Validated contracts for safe manual company research."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, model_validator

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class ResearchRunStatus(StrEnum):
    PENDING = "pending"
    FETCHING = "fetching"
    COMPLETED = "completed"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"


class CompanyFactStatus(StrEnum):
    EXTRACTED = "extracted"
    VERIFIED = "verified"
    REJECTED = "rejected"
    STALE = "stale"


class HypothesisStatus(StrEnum):
    HYPOTHESIS = "hypothesis"
    VERIFIED = "verified"
    REJECTED = "rejected"


class ResearchRequest(BaseModel):
    url: HttpUrl


class CompanyFactCreate(BaseModel):
    source_id: UUID
    fact_type: ShortText
    value: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=6000)]
    confidence: float = Field(ge=0, le=1)
    exact_fragment: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
    ]
    status: CompanyFactStatus = CompanyFactStatus.EXTRACTED


class CompanyFactUpdate(BaseModel):
    version: int = Field(ge=1)
    status: CompanyFactStatus | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class CompanyFactRead(CompanyFactCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    version: int
    created_at: datetime
    updated_at: datetime


class CompanyTaskHypothesisCreate(BaseModel):
    source_ids: list[UUID] = Field(min_length=1, max_length=50)
    title: ShortText
    description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=6000)
    ]
    rationale: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=6000)
    ]
    confidence: float = Field(ge=0, le=1)
    status: HypothesisStatus = HypothesisStatus.HYPOTHESIS
    risks: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def hypotheses_are_explicit(self) -> "CompanyTaskHypothesisCreate":
        if self.status == HypothesisStatus.HYPOTHESIS and not self.risks:
            raise ValueError("task hypotheses require at least one explicit risk")
        return self


class CompanyTaskHypothesisRead(CompanyTaskHypothesisCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    version: int
    created_at: datetime
    updated_at: datetime


class CompanyTaskHypothesisUpdate(BaseModel):
    version: int = Field(ge=1)
    status: HypothesisStatus


class ResearchRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    requested_url: str
    normalized_url: str
    source_id: UUID | None
    status: ResearchRunStatus
    content_type: str | None
    content_bytes: int | None
    language: str | None
    redirect_chain: list[str]
    result_summary: dict[str, object]
    error_code: str | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None


class ResearchResult(BaseModel):
    run: ResearchRunRead
    facts: list[CompanyFactRead]
    hypotheses: list[CompanyTaskHypothesisRead]
    signal_ids: list[UUID]
    opportunity_ids: list[UUID]
