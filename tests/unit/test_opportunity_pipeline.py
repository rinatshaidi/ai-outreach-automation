from app.modules.crm.pipeline import (
    DECISION_PIPELINE_STATUS,
    draft_generation_allowed,
    transition_is_allowed,
)
from app.modules.crm.schemas import PipelineStatus
from app.modules.opportunities.schemas import OpportunityDecision


def test_pipeline_requires_ordered_research_transition() -> None:
    assert transition_is_allowed(PipelineStatus.NEW, PipelineStatus.RESEARCH_PENDING)
    assert not transition_is_allowed(PipelineStatus.NEW, PipelineStatus.RESEARCHED)


def test_approved_for_outreach_cannot_be_set_by_regular_patch() -> None:
    assert not transition_is_allowed(
        PipelineStatus.DECISION_PENDING,
        PipelineStatus.APPROVED_FOR_OUTREACH,
    )
    assert transition_is_allowed(
        PipelineStatus.DECISION_PENDING,
        PipelineStatus.APPROVED_FOR_OUTREACH,
        via_owner_decision=True,
    )


def test_every_final_owner_decision_has_a_pipeline_target() -> None:
    assert set(DECISION_PIPELINE_STATUS) == {
        OpportunityDecision.OUTREACH,
        OpportunityDecision.DEFER,
        OpportunityDecision.DEEPER_RESEARCH,
        OpportunityDecision.NOT_RELEVANT,
        OpportunityDecision.WATCHLIST,
    }


def test_draft_gate_requires_both_status_and_outreach_decision() -> None:
    assert draft_generation_allowed(
        PipelineStatus.APPROVED_FOR_OUTREACH,
        OpportunityDecision.OUTREACH,
    )
    assert draft_generation_allowed(PipelineStatus.DRAFT_READY, OpportunityDecision.OUTREACH)
    assert draft_generation_allowed(PipelineStatus.REVIEW, OpportunityDecision.OUTREACH)
    assert not draft_generation_allowed(
        PipelineStatus.DECISION_PENDING,
        OpportunityDecision.OUTREACH,
    )
    assert not draft_generation_allowed(
        PipelineStatus.APPROVED_FOR_OUTREACH,
        OpportunityDecision.WATCHLIST,
    )


def test_editing_approved_draft_returns_pipeline_to_review() -> None:
    assert transition_is_allowed(PipelineStatus.APPROVED, PipelineStatus.REVIEW)
