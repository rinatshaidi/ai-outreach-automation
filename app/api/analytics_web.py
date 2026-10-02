"""Server-rendered analytics and opportunity portfolio."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.api.crm import DbSession
from app.api.web import templates
from app.config import Settings, get_settings
from app.modules.analytics.service import build_analytics

router = APIRouter(include_in_schema=False)
AppSettings = Annotated[Settings, Depends(get_settings)]
FILTER_KEYS = (
    "q",
    "opportunity_type",
    "positioning_strategy",
    "vacancy",
    "company_size",
    "maturity_stage",
    "country",
    "collaboration_format",
    "workplace_format",
    "decision_maker_role",
    "source_trust",
    "signal_freshness",
    "pipeline_status",
    "user_decision",
    "outcome",
)


@router.get("/analytics", response_class=HTMLResponse)
async def analytics_page(
    request: Request,
    session: DbSession,
    settings: AppSettings,
) -> HTMLResponse:
    filters = {key: request.query_params.get(key) or None for key in FILTER_KEYS}
    report = await build_analytics(
        session,
        timezone_name=settings.user_timezone,
        filters=filters,
    )
    max_funnel = max((item.companies for item in report.funnel), default=0)
    return templates.TemplateResponse(
        request=request,
        name="analytics.html",
        context={
            "report": report,
            "filters": filters,
            "max_funnel": max_funnel,
        },
    )
