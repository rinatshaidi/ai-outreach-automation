"""Analytics and portfolio response DTOs."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class BreakdownItem(BaseModel):
    key: str
    companies: int


class FunnelStage(BaseModel):
    key: str
    label: str
    companies: int


class PortfolioCompany(BaseModel):
    id: UUID
    name: str
    domain: str
    country: str | None
    company_size: str | None
    maturity_stage: str | None
    overall_score: float | None
    opportunity_types: list[str]
    positioning_strategy: str | None
    collaboration_formats: list[str]
    workplace_formats: list[str]
    pipeline_status: str
    has_active_vacancy: bool
    verified_contacts: int
    primary_decision_maker_role: str | None
    drafts: int
    real_messages: int
    outcome: str | None
    followup_status: str | None
    next_action: str | None


class AnalyticsResponse(BaseModel):
    metrics: dict[str, int | float]
    funnel: list[FunnelStage]
    breakdowns: dict[str, list[BreakdownItem]]
    portfolio: list[PortfolioCompany]
    applied_filters: dict[str, Any] = Field(default_factory=dict)
