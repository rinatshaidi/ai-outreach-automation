"""Company-scoped opportunity foundation and owner decision API."""

from datetime import UTC, datetime
from typing import Annotated, Any, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.crm import add_event, ensure_version
from app.infrastructure.db.session import get_db_session
from app.modules.candidate_profile.models import CandidateProfile
from app.modules.crm.models import Company, CompanySource
from app.modules.crm.pipeline import DECISION_PIPELINE_STATUS, transition_is_allowed
from app.modules.crm.schemas import PipelineStatus
from app.modules.opportunities.models import (
    CompanyOpportunity,
    OpportunityAssessment,
    OpportunityDecisionEvent,
    OpportunitySignal,
    PositioningRecommendation,
)
from app.modules.opportunities.readiness import (
    OpportunityReadiness,
    evaluate_opportunity_readiness,
)
from app.modules.opportunities.schemas import (
    CompanyOpportunityCreate,
    CompanyOpportunityRead,
    CompanyOpportunityUpdate,
    CompanySourceCreate,
    CompanySourceRead,
    OpportunityAssessmentCreate,
    OpportunityAssessmentRead,
    OpportunityDecision,
    OpportunityDecisionCreate,
    OpportunityDecisionRead,
    OpportunitySignalCreate,
    OpportunitySignalRead,
    OpportunitySignalUpdate,
    PositioningRecommendationCreate,
    PositioningRecommendationRead,
)

router = APIRouter(prefix="/api/v1/companies/{company_id}", tags=["opportunities"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def normalize(values: dict[str, Any]) -> dict[str, Any]:
    def json_value(value: Any) -> Any:
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, list):
            return [json_value(item) for item in value]
        if isinstance(value, dict):
            return {key: json_value(item) for key, item in value.items()}
        if hasattr(value, "value"):
            return value.value
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        return value

    result: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, UUID):
            result[key] = value
        elif isinstance(value, list | dict):
            result[key] = json_value(value)
        elif hasattr(value, "value"):
            result[key] = value.value
        elif key == "url":
            result[key] = str(value)
        elif hasattr(value, "model_dump"):
            result[key] = value.model_dump(mode="json")
        else:
            result[key] = value
    return result


async def company_or_404(session: AsyncSession, company_id: UUID) -> Company:
    company = await session.get(Company, company_id)
    if company is None:
        raise api_error(404, "company_not_found", "Company was not found")
    return company


async def entity_or_404(session: AsyncSession, model: type[Any], entity_id: UUID) -> Any:
    entity = await session.get(model, entity_id)
    if entity is None:
        raise api_error(404, "not_found", "The record was not found")
    return entity


async def source_belongs_to_company(
    session: AsyncSession, company_id: UUID, source_id: UUID | None
) -> None:
    if source_id is None:
        return
    source = await entity_or_404(session, CompanySource, source_id)
    if source.company_id != company_id:
        raise api_error(422, "source_mismatch", "Source belongs to another company")


@router.get("/sources", response_model=list[CompanySourceRead])
async def list_sources(company_id: UUID, session: DbSession) -> list[CompanySource]:
    await company_or_404(session, company_id)
    return list(
        await session.scalars(
            select(CompanySource)
            .where(CompanySource.company_id == company_id)
            .order_by(CompanySource.created_at.desc())
        )
    )


@router.post("/sources", response_model=CompanySourceRead, status_code=status.HTTP_201_CREATED)
async def create_source(
    company_id: UUID, payload: CompanySourceCreate, session: DbSession
) -> CompanySource:
    await company_or_404(session, company_id)
    source = CompanySource(company_id=company_id, **normalize(payload.model_dump()))
    session.add(source)
    await session.commit()
    await session.refresh(source)
    return source


@router.get("/signals", response_model=list[OpportunitySignalRead])
async def list_signals(company_id: UUID, session: DbSession) -> list[OpportunitySignal]:
    await company_or_404(session, company_id)
    return list(
        await session.scalars(
            select(OpportunitySignal)
            .where(OpportunitySignal.company_id == company_id)
            .order_by(OpportunitySignal.detected_at.desc())
        )
    )


@router.post("/signals", response_model=OpportunitySignalRead, status_code=status.HTTP_201_CREATED)
async def create_signal(
    company_id: UUID, payload: OpportunitySignalCreate, session: DbSession
) -> OpportunitySignal:
    company = await company_or_404(session, company_id)
    await source_belongs_to_company(session, company_id, payload.source_id)
    signal = OpportunitySignal(company_id=company_id, **normalize(payload.model_dump()))
    session.add(signal)
    add_event(
        session,
        company_id=company_id,
        event_type="opportunity_signal_added",
        summary=f"Signal added: {signal.title}",
    )
    company.version += 1
    await session.commit()
    await session.refresh(signal)
    return signal


@router.patch("/signals/{signal_id}", response_model=OpportunitySignalRead)
async def update_signal(
    company_id: UUID,
    signal_id: UUID,
    payload: OpportunitySignalUpdate,
    session: DbSession,
) -> OpportunitySignal:
    signal = cast(OpportunitySignal, await entity_or_404(session, OpportunitySignal, signal_id))
    if signal.company_id != company_id:
        raise api_error(404, "signal_not_found", "Signal was not found")
    ensure_version(signal.version, payload.version)
    changes = normalize(payload.model_dump(exclude_unset=True, exclude={"version"}))
    if "source_id" in changes:
        await source_belongs_to_company(session, company_id, payload.source_id)
    merged = OpportunitySignalCreate.model_validate(
        {
            "signal_type": signal.signal_type,
            "title": changes.get("title", signal.title),
            "description": changes.get("description", signal.description),
            "source_id": changes.get("source_id", signal.source_id),
            "detected_at": signal.detected_at,
            "effective_at": changes.get("effective_at", signal.effective_at),
            "confidence": changes.get("confidence", signal.confidence),
            "exact_fragment": changes.get("exact_fragment", signal.exact_fragment),
            "status": changes.get("status", signal.status),
        }
    )
    for key, value in normalize(merged.model_dump()).items():
        setattr(signal, key, value)
    signal.version += 1
    await session.commit()
    await session.refresh(signal)
    return signal


@router.get("/opportunities", response_model=list[CompanyOpportunityRead])
async def list_opportunities(company_id: UUID, session: DbSession) -> list[CompanyOpportunity]:
    await company_or_404(session, company_id)
    return list(
        await session.scalars(
            select(CompanyOpportunity)
            .where(CompanyOpportunity.company_id == company_id)
            .order_by(CompanyOpportunity.created_at.desc())
        )
    )


@router.post(
    "/opportunities", response_model=CompanyOpportunityRead, status_code=status.HTTP_201_CREATED
)
async def create_opportunity(
    company_id: UUID, payload: CompanyOpportunityCreate, session: DbSession
) -> CompanyOpportunity:
    company = await company_or_404(session, company_id)
    opportunity = CompanyOpportunity(company_id=company_id, **normalize(payload.model_dump()))
    session.add(opportunity)
    company.opportunity_types = list(
        dict.fromkeys([*company.opportunity_types, payload.opportunity_type.value])
    )
    add_event(
        session,
        company_id=company_id,
        event_type="opportunity_added",
        summary=f"Opportunity identified: {payload.opportunity_type.value}",
    )
    company.version += 1
    await session.commit()
    await session.refresh(opportunity)
    return opportunity


@router.patch("/opportunities/{opportunity_id}", response_model=CompanyOpportunityRead)
async def update_opportunity(
    company_id: UUID,
    opportunity_id: UUID,
    payload: CompanyOpportunityUpdate,
    session: DbSession,
) -> CompanyOpportunity:
    opportunity = cast(
        CompanyOpportunity,
        await entity_or_404(session, CompanyOpportunity, opportunity_id),
    )
    if opportunity.company_id != company_id:
        raise api_error(404, "opportunity_not_found", "Opportunity was not found")
    ensure_version(opportunity.version, payload.version)
    changes = normalize(payload.model_dump(exclude_unset=True, exclude={"version"}))
    merged = CompanyOpportunityCreate.model_validate(
        {
            "opportunity_type": opportunity.opportunity_type,
            "rationale": changes.get("rationale", opportunity.rationale),
            "confidence": changes.get("confidence", opportunity.confidence),
            "source_ids": changes.get("source_ids", opportunity.source_ids),
            "signal_ids": changes.get("signal_ids", opportunity.signal_ids),
            "status": changes.get("status", opportunity.status),
        }
    )
    for key, value in normalize(merged.model_dump(exclude={"opportunity_type"})).items():
        setattr(opportunity, key, value)
    opportunity.version += 1
    await session.commit()
    await session.refresh(opportunity)
    return opportunity


@router.get("/assessments", response_model=list[OpportunityAssessmentRead])
async def list_assessments(company_id: UUID, session: DbSession) -> list[OpportunityAssessment]:
    await company_or_404(session, company_id)
    return list(
        await session.scalars(
            select(OpportunityAssessment)
            .where(OpportunityAssessment.company_id == company_id)
            .order_by(OpportunityAssessment.created_at.desc())
        )
    )


@router.post(
    "/assessments", response_model=OpportunityAssessmentRead, status_code=status.HTTP_201_CREATED
)
async def create_assessment(
    company_id: UUID, payload: OpportunityAssessmentCreate, session: DbSession
) -> OpportunityAssessment:
    company = await company_or_404(session, company_id)
    profile = await session.scalar(
        select(CandidateProfile).where(CandidateProfile.owner_key == "primary")
    )
    if profile is None or profile.version != payload.candidate_profile_version:
        raise api_error(
            409,
            "profile_version_conflict",
            "Assessment must use the current Candidate Profile version",
        )
    assessment = OpportunityAssessment(company_id=company_id, **normalize(payload.model_dump()))
    session.add(assessment)
    for field in (
        "business_fit_score",
        "ai_automation_fit_score",
        "hybrid_fit_score",
        "format_fit_score",
        "geography_fit_score",
        "timing_signal_score",
        "contactability_score",
        "overall_opportunity_score",
    ):
        setattr(company, field, getattr(payload, field))
    company.relevance_score = payload.overall_opportunity_score
    company.next_action = payload.next_action
    company.version += 1
    add_event(
        session,
        company_id=company_id,
        event_type="opportunity_assessed",
        summary=f"Opportunity assessment saved: {payload.overall_opportunity_score:.1f}",
    )
    await session.commit()
    await session.refresh(assessment)
    return assessment


@router.get("/recommendations", response_model=list[PositioningRecommendationRead])
async def list_recommendations(
    company_id: UUID, session: DbSession
) -> list[PositioningRecommendation]:
    await company_or_404(session, company_id)
    return list(
        await session.scalars(
            select(PositioningRecommendation)
            .where(PositioningRecommendation.company_id == company_id)
            .order_by(PositioningRecommendation.created_at.desc())
        )
    )


@router.get("/readiness", response_model=OpportunityReadiness)
async def read_opportunity_readiness(
    company_id: UUID, session: DbSession
) -> OpportunityReadiness:
    company = await company_or_404(session, company_id)
    return await evaluate_opportunity_readiness(session, company)


@router.post(
    "/recommendations",
    response_model=PositioningRecommendationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_recommendation(
    company_id: UUID, payload: PositioningRecommendationCreate, session: DbSession
) -> PositioningRecommendation:
    company = await company_or_404(session, company_id)
    assessment = await entity_or_404(session, OpportunityAssessment, payload.assessment_id)
    if assessment.company_id != company_id:
        raise api_error(422, "assessment_mismatch", "Assessment belongs to another company")
    recommendation = PositioningRecommendation(
        company_id=company_id, **normalize(payload.model_dump())
    )
    session.add(recommendation)
    company.recommended_positioning = payload.primary_strategy.value
    company.recommended_collaboration_formats = [payload.collaboration_format.value]
    company.recommended_workplace_formats = [item.value for item in payload.workplace_formats]
    company.recommended_role = payload.possible_role
    company.version += 1
    add_event(
        session,
        company_id=company_id,
        event_type="positioning_recommended",
        summary=f"Positioning selected: {payload.primary_strategy.value}",
    )
    await session.commit()
    await session.refresh(recommendation)
    return recommendation


@router.post(
    "/recommendations/{recommendation_id}/decision",
    response_model=OpportunityDecisionRead,
    status_code=status.HTTP_201_CREATED,
)
async def decide_recommendation(
    company_id: UUID,
    recommendation_id: UUID,
    payload: OpportunityDecisionCreate,
    request: Request,
    session: DbSession,
) -> OpportunityDecisionEvent:
    company = await company_or_404(session, company_id)
    recommendation = await entity_or_404(session, PositioningRecommendation, recommendation_id)
    if recommendation.company_id != company_id:
        raise api_error(404, "recommendation_not_found", "Recommendation was not found")
    ensure_version(recommendation.version, payload.version)
    if payload.decision == OpportunityDecision.OUTREACH:
        readiness = await evaluate_opportunity_readiness(session, company)
        if not readiness.actionable:
            raise api_error(
                409,
                "opportunity_not_actionable",
                "Outreach requires an actionable opportunity. "
                f"Current recommendation: {readiness.recommended_action.value}; "
                f"blockers: {', '.join(readiness.blockers)}",
            )
    if payload.decision not in DECISION_PIPELINE_STATUS:
        raise api_error(422, "invalid_decision", "A final owner decision is required")
    current = PipelineStatus(company.pipeline_status)
    target = DECISION_PIPELINE_STATUS[payload.decision]
    if not transition_is_allowed(current, target, via_owner_decision=True):
        raise api_error(
            409,
            "invalid_pipeline_transition",
            f"Decision cannot move {current.value} to {target.value}",
        )

    now = datetime.now(UTC)
    recommendation.user_decision = payload.decision.value
    recommendation.decided_at = now
    recommendation.version += 1
    company.pipeline_status = target.value
    company.version += 1
    decision = OpportunityDecisionEvent(
        id=uuid4(),
        company_id=company_id,
        recommendation_id=recommendation_id,
        decision=payload.decision.value,
        confirmed=payload.confirmed,
        comment=payload.comment,
        request_id=str(getattr(request.state, "request_id", "missing-request-id")),
        decided_at=now,
    )
    session.add(decision)
    add_event(
        session,
        company_id=company_id,
        event_type="opportunity_decision",
        summary=f"Owner decision: {payload.decision.value}",
        metadata={"decision": payload.decision.value, "recommendation_id": str(recommendation_id)},
    )
    await session.commit()
    await session.refresh(decision)
    return decision
