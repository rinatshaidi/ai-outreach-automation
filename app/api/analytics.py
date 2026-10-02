"""Filtered opportunity, portfolio and outcome analytics API."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.infrastructure.db.session import get_db_session
from app.modules.analytics.schemas import AnalyticsResponse
from app.modules.analytics.service import build_analytics

router = APIRouter(prefix="/api/v1", tags=["analytics"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]


@router.get("/analytics", response_model=AnalyticsResponse)
async def analytics(
    session: DbSession,
    settings: AppSettings,
    q: str | None = Query(default=None, max_length=200),
    opportunity_type: str | None = Query(default=None, max_length=60),
    positioning_strategy: str | None = Query(default=None, max_length=40),
    vacancy: str | None = Query(default=None, pattern="^(with|without)$"),
    company_size: str | None = Query(default=None, max_length=80),
    maturity_stage: str | None = Query(default=None, max_length=80),
    country: str | None = Query(default=None, max_length=120),
    collaboration_format: str | None = Query(default=None, max_length=60),
    workplace_format: str | None = Query(default=None, max_length=60),
    decision_maker_role: str | None = Query(default=None, max_length=80),
    source_trust: str | None = Query(default=None, max_length=30),
    signal_freshness: str | None = Query(default=None, max_length=30),
    pipeline_status: str | None = Query(default=None, max_length=40),
    user_decision: str | None = Query(default=None, max_length=30),
    outcome: str | None = Query(default=None, max_length=40),
) -> AnalyticsResponse:
    return await build_analytics(
        session,
        timezone_name=settings.user_timezone,
        filters={
            "q": q,
            "opportunity_type": opportunity_type,
            "positioning_strategy": positioning_strategy,
            "vacancy": vacancy,
            "company_size": company_size,
            "maturity_stage": maturity_stage,
            "country": country,
            "collaboration_format": collaboration_format,
            "workplace_format": workplace_format,
            "decision_maker_role": decision_maker_role,
            "source_trust": source_trust,
            "signal_freshness": signal_freshness,
            "pipeline_status": pipeline_status,
            "user_decision": user_decision,
            "outcome": outcome,
        },
    )
