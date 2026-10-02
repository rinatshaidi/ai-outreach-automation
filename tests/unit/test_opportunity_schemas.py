"""Opportunity-first enum, DTO and safety invariant tests."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.crm.schemas import PipelineStatus
from app.modules.opportunities.schemas import (
    CompanyOpportunityCreate,
    DecisionMakerRole,
    EvidenceStatus,
    OpportunityAssessmentRead,
    OpportunityDecision,
    OpportunityDecisionCreate,
    OpportunityResultRead,
    OpportunitySignalCreate,
    OpportunitySignalType,
    OpportunityType,
    PositioningRecommendationCreate,
    PositioningRecommendationRead,
    PositioningStrategy,
    ScoreBreakdown,
)


def test_all_v13_opportunity_types_are_defined() -> None:
    assert {item.name for item in OpportunityType} == {
        "OPEN_VACANCY",
        "BUSINESS_EXPANSION",
        "MARKET_ENTRY",
        "OPERATIONS_IMPROVEMENT",
        "AI_ADOPTION",
        "PROCESS_AUTOMATION",
        "NEW_PRODUCT_OR_DIRECTION",
        "ACTIVE_HIRING",
        "INVESTMENT_OR_GROWTH",
        "PROJECT_WORK",
        "CONSULTING",
        "LOCAL_REPRESENTATION",
        "GENERAL_COMPETENCE_FIT",
        "HYBRID_OPPORTUNITY",
    }


def test_verified_signal_requires_full_provenance() -> None:
    with pytest.raises(ValidationError, match="source_id and exact_fragment"):
        OpportunitySignalCreate(
            signal_type=OpportunitySignalType.AI_ADOPTION,
            title="AI programme",
            description="Synthetic public signal",
            detected_at=datetime.now(UTC),
            confidence=0.8,
            status=EvidenceStatus.VERIFIED,
        )

    signal = OpportunitySignalCreate(
        signal_type=OpportunitySignalType.AI_ADOPTION,
        title="AI programme",
        description="Synthetic public signal",
        source_id=uuid4(),
        detected_at=datetime.now(UTC),
        confidence=0.8,
        exact_fragment="Synthetic exact fragment",
        status=EvidenceStatus.VERIFIED,
    )
    assert signal.status == EvidenceStatus.VERIFIED


def test_verified_opportunity_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="source or signal"):
        CompanyOpportunityCreate(
            opportunity_type=OpportunityType.GENERAL_COMPETENCE_FIT,
            rationale="Synthetic competence overlap",
            confidence=0.7,
            status=EvidenceStatus.VERIFIED,
        )


def test_outreach_decision_is_fail_closed() -> None:
    with pytest.raises(ValidationError, match="explicit confirmation"):
        OpportunityDecisionCreate(
            version=1,
            decision=OpportunityDecision.OUTREACH,
        )

    decision = OpportunityDecisionCreate(
        version=1,
        decision=OpportunityDecision.OUTREACH,
        confirmed=True,
    )
    assert decision.confirmed is True


def test_positioning_requires_distinct_decision_makers() -> None:
    with pytest.raises(ValidationError, match="must differ"):
        PositioningRecommendationCreate(
            assessment_id=uuid4(),
            primary_strategy=PositioningStrategy.HYBRID,
            primary_message_line="Business operations first",
            secondary_advantage="AI automation second",
            rationale="Both capabilities are relevant",
            value_proposition="Improve operations with practical automation",
            concrete_first_message_offer="Discuss a synthetic process review",
            primary_decision_maker_role=DecisionMakerRole.COO,
            secondary_decision_maker_role=DecisionMakerRole.COO,
            collaboration_format="consulting",
            possible_role="Operations automation lead",
        )


def test_scores_are_bounded() -> None:
    with pytest.raises(ValidationError):
        _assessment(overall_opportunity_score=101)


def test_draft_generation_requires_outreach_decision() -> None:
    assessment = _assessment()
    recommendation = PositioningRecommendationRead(
        id=uuid4(),
        company_id=assessment.company_id,
        assessment_id=assessment.id,
        primary_strategy=PositioningStrategy.BUSINESS_FIRST,
        primary_message_line="Business background first",
        secondary_advantage="AI automation as an efficiency tool",
        rationale="Synthetic operations fit",
        value_proposition="Improve delivery coordination",
        concrete_first_message_offer="Discuss a synthetic project review",
        primary_decision_maker_role=DecisionMakerRole.COO,
        secondary_decision_maker_role=DecisionMakerRole.HEAD_OF_OPERATIONS,
        collaboration_format="project_based",
        possible_role="Project lead",
        version=1,
        decided_at=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    common = {
        "company_id": assessment.company_id,
        "summary": "Synthetic company summary",
        "opportunity_types": [OpportunityType.GENERAL_COMPETENCE_FIT],
        "signals": [],
        "assessment": assessment,
        "recommendation": recommendation,
        "has_open_vacancy": False,
    }

    with pytest.raises(ValidationError, match="requires an outreach decision"):
        OpportunityResultRead(
            **common,
            user_decision=OpportunityDecision.WATCHLIST,
            draft_generation_allowed=True,
        )

    allowed = OpportunityResultRead(
        **common,
        user_decision=OpportunityDecision.OUTREACH,
        draft_generation_allowed=True,
    )
    assert allowed.draft_generation_allowed is True


def test_pipeline_supports_v13_after_legacy_backfill() -> None:
    assert PipelineStatus.OPPORTUNITY_IDENTIFIED.value == "opportunity_identified"
    assert PipelineStatus.APPROVED_FOR_OUTREACH.value == "approved_for_outreach"
    assert PipelineStatus.WATCHLIST.value == "watchlist"
    assert PipelineStatus.PROJECT_DISCUSSION.value == "project_discussion"
    assert PipelineStatus.CONSULTING_DISCUSSION.value == "consulting_discussion"
    assert PipelineStatus.AGREEMENT.value == "agreement"
    with pytest.raises(ValueError):
        PipelineStatus("qualified")


def _assessment(**overrides: object) -> OpportunityAssessmentRead:
    values: dict[str, object] = {
        "id": uuid4(),
        "company_id": uuid4(),
        "candidate_profile_version": 1,
        "business_fit_score": 78,
        "ai_automation_fit_score": 62,
        "hybrid_fit_score": 84,
        "format_fit_score": 80,
        "geography_fit_score": 75,
        "timing_signal_score": 20,
        "contactability_score": 50,
        "overall_opportunity_score": 72,
        "score_breakdown": ScoreBreakdown(
            formula_version="v1",
            weights={},
            contributions={},
        ),
        "model_or_rule_version": "v1",
        "created_at": datetime.now(UTC),
    }
    values.update(overrides)
    return OpportunityAssessmentRead.model_validate(values)
