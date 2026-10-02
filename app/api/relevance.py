"""Deterministic relevance calculation and explicit owner override API."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.crm import add_event
from app.api.opportunities import create_assessment
from app.infrastructure.db.session import get_db_session
from app.modules.candidate_profile.models import (
    CandidateExperience,
    CandidateFact,
    CandidateProfile,
    CandidateSkill,
)
from app.modules.crm.models import Company, Contact
from app.modules.opportunities.models import (
    CompanyOpportunity,
    OpportunityAssessment,
    OpportunitySignal,
)
from app.modules.opportunities.quality import build_match_theses
from app.modules.opportunities.schemas import OpportunityAssessmentRead
from app.modules.relevance.models import OpportunityAssessmentOverride
from app.modules.relevance.schemas import (
    AssessmentOverrideCreate,
    AssessmentOverrideRead,
    RelevanceCalculationRequest,
    ScoringThresholds,
)
from app.modules.relevance.scoring import (
    FORMULA_VERSION,
    THRESHOLD_OPPORTUNITY,
    THRESHOLD_REVIEW,
    calculate_assessment,
    relevance_status,
)
from app.modules.research.models import CompanyFact, CompanyTaskHypothesis

router = APIRouter(prefix="/api/v1/companies/{company_id}/relevance", tags=["relevance"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


async def require_company(session: AsyncSession, company_id: UUID) -> Company:
    company = await session.get(Company, company_id)
    if company is None:
        raise api_error(404, "company_not_found", "Company was not found")
    return company


@router.get("/thresholds", response_model=ScoringThresholds)
async def read_thresholds(company_id: UUID, session: DbSession) -> ScoringThresholds:
    await require_company(session, company_id)
    return ScoringThresholds(
        opportunity_identified=THRESHOLD_OPPORTUNITY,
        needs_review=THRESHOLD_REVIEW,
        formula_version=FORMULA_VERSION,
    )


@router.post(
    "/calculate",
    response_model=OpportunityAssessmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def calculate_company_relevance(
    company_id: UUID,
    session: DbSession,
    calculation: Annotated[RelevanceCalculationRequest | None, Body()] = None,
) -> OpportunityAssessment:
    company = await require_company(session, company_id)
    profile = await session.scalar(
        select(CandidateProfile).where(CandidateProfile.owner_key == "primary")
    )
    if profile is None:
        raise api_error(409, "profile_missing", "Candidate Profile must exist before scoring")

    experiences = list(
        await session.scalars(
            select(CandidateExperience).where(CandidateExperience.profile_id == profile.id)
        )
    )
    skills = list(
        await session.scalars(select(CandidateSkill).where(CandidateSkill.profile_id == profile.id))
    )
    candidate_facts = list(
        await session.scalars(select(CandidateFact).where(CandidateFact.profile_id == profile.id))
    )
    opportunities = list(
        await session.scalars(
            select(CompanyOpportunity).where(CompanyOpportunity.company_id == company_id)
        )
    )
    signals = list(
        await session.scalars(
            select(OpportunitySignal).where(OpportunitySignal.company_id == company_id)
        )
    )
    contacts = list(await session.scalars(select(Contact).where(Contact.company_id == company_id)))
    company_facts = list(
        await session.scalars(select(CompanyFact).where(CompanyFact.company_id == company_id))
    )
    hypotheses = list(
        await session.scalars(
            select(CompanyTaskHypothesis).where(CompanyTaskHypothesis.company_id == company_id)
        )
    )
    payload = calculate_assessment(
        company=company,
        profile=profile,
        experiences=experiences,
        skills=skills,
        candidate_facts=candidate_facts,
        opportunities=opportunities,
        signals=signals,
        contacts=contacts,
        company_facts=company_facts,
        hypotheses=hypotheses,
        weights=(calculation or RelevanceCalculationRequest()).weights.model_dump(),
    )
    match_theses = build_match_theses(
        [*experiences, *skills, *candidate_facts],
        company_facts,
        opportunities,
        signals,
        contacts,
        "en",
    )
    assessment = await create_assessment(company_id, payload, session)
    target = relevance_status(
        payload.overall_opportunity_score,
        evidence_sufficient=bool(match_theses),
    )
    company.relevance_status = target
    if company.pipeline_status in {
        "research_pending",
        "researched",
        "needs_review",
        "not_relevant",
        "opportunity_identified",
    }:
        company.pipeline_status = target
    company.version += 1
    add_event(
        session,
        company_id=company_id,
        event_type="relevance_calculated",
        summary=f"Deterministic relevance calculated: {payload.overall_opportunity_score:.2f}",
        metadata={
            "formula_version": FORMULA_VERSION,
            "status": target,
            "evidence_backed_match_count": len(match_theses),
        },
    )
    await session.commit()
    await session.refresh(assessment)
    return assessment


@router.get("/overrides", response_model=list[AssessmentOverrideRead])
async def list_assessment_overrides(
    company_id: UUID, session: DbSession
) -> list[OpportunityAssessmentOverride]:
    await require_company(session, company_id)
    return list(
        await session.scalars(
            select(OpportunityAssessmentOverride)
            .where(OpportunityAssessmentOverride.company_id == company_id)
            .order_by(OpportunityAssessmentOverride.created_at.desc())
        )
    )


@router.post(
    "/assessments/{assessment_id}/override",
    response_model=AssessmentOverrideRead,
    status_code=status.HTTP_201_CREATED,
)
async def override_assessment(
    company_id: UUID,
    assessment_id: UUID,
    payload: AssessmentOverrideCreate,
    request: Request,
    session: DbSession,
) -> OpportunityAssessmentOverride:
    company = await require_company(session, company_id)
    assessment = cast(
        OpportunityAssessment | None,
        await session.get(OpportunityAssessment, assessment_id),
    )
    if assessment is None or assessment.company_id != company_id:
        raise api_error(404, "assessment_not_found", "Assessment was not found")
    override = OpportunityAssessmentOverride(
        company_id=company_id,
        assessment_id=assessment_id,
        original_score=assessment.overall_opportunity_score,
        overridden_score=payload.overridden_score,
        reason=payload.reason,
        request_id=str(getattr(request.state, "request_id", "missing-request-id")),
    )
    session.add(override)
    target = relevance_status(payload.overridden_score)
    company.overall_opportunity_score = payload.overridden_score
    company.relevance_score = payload.overridden_score
    company.relevance_status = target
    if company.pipeline_status in {"opportunity_identified", "needs_review", "not_relevant"}:
        company.pipeline_status = target
    company.version += 1
    add_event(
        session,
        company_id=company_id,
        event_type="relevance_overridden",
        summary=(
            f"Owner override: {assessment.overall_opportunity_score:.2f} "
            f"→ {payload.overridden_score:.2f}"
        ),
        metadata={"assessment_id": str(assessment_id), "reason": payload.reason},
    )
    await session.commit()
    await session.refresh(override)
    return override
