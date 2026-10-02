"""Guarded company pipeline transitions for the opportunity-first workflow."""

from app.modules.crm.schemas import PipelineStatus
from app.modules.opportunities.schemas import OpportunityDecision

ALLOWED_TRANSITIONS: dict[PipelineStatus, frozenset[PipelineStatus]] = {
    PipelineStatus.NEW: frozenset({PipelineStatus.RESEARCH_PENDING}),
    PipelineStatus.RESEARCH_PENDING: frozenset({PipelineStatus.RESEARCHED}),
    PipelineStatus.RESEARCHED: frozenset(
        {
            PipelineStatus.RESEARCH_PENDING,
            PipelineStatus.OPPORTUNITY_IDENTIFIED,
            PipelineStatus.NEEDS_REVIEW,
            PipelineStatus.NOT_RELEVANT,
        }
    ),
    PipelineStatus.OPPORTUNITY_IDENTIFIED: frozenset(
        {PipelineStatus.STRATEGY_SELECTED, PipelineStatus.NEEDS_REVIEW}
    ),
    PipelineStatus.NEEDS_REVIEW: frozenset(
        {
            PipelineStatus.RESEARCH_PENDING,
            PipelineStatus.RESEARCHED,
            PipelineStatus.OPPORTUNITY_IDENTIFIED,
            PipelineStatus.NOT_RELEVANT,
        }
    ),
    PipelineStatus.NOT_RELEVANT: frozenset({PipelineStatus.RESEARCH_PENDING}),
    PipelineStatus.STRATEGY_SELECTED: frozenset(
        {
            PipelineStatus.CONTACT_FOUND,
            PipelineStatus.CONTACT_MISSING,
            PipelineStatus.CONTACT_RESEARCH_REQUIRED,
        }
    ),
    PipelineStatus.CONTACT_FOUND: frozenset({PipelineStatus.DECISION_PENDING}),
    PipelineStatus.CONTACT_MISSING: frozenset(
        {PipelineStatus.CONTACT_RESEARCH_REQUIRED, PipelineStatus.DECISION_PENDING}
    ),
    PipelineStatus.CONTACT_RESEARCH_REQUIRED: frozenset(
        {
            PipelineStatus.RESEARCH_PENDING,
            PipelineStatus.CONTACT_FOUND,
            PipelineStatus.WATCHLIST,
        }
    ),
    PipelineStatus.DECISION_PENDING: frozenset(
        {
            PipelineStatus.APPROVED_FOR_OUTREACH,
            PipelineStatus.DEFERRED,
            PipelineStatus.WATCHLIST,
            PipelineStatus.REJECTED,
            PipelineStatus.NOT_RELEVANT,
            PipelineStatus.RESEARCH_PENDING,
            PipelineStatus.CONTACT_RESEARCH_REQUIRED,
        }
    ),
    PipelineStatus.APPROVED_FOR_OUTREACH: frozenset({PipelineStatus.DRAFT_READY}),
    PipelineStatus.DEFERRED: frozenset(
        {PipelineStatus.RESEARCH_PENDING, PipelineStatus.DECISION_PENDING}
    ),
    PipelineStatus.WATCHLIST: frozenset(
        {PipelineStatus.RESEARCH_PENDING, PipelineStatus.DECISION_PENDING}
    ),
    PipelineStatus.DRAFT_READY: frozenset({PipelineStatus.REVIEW}),
    PipelineStatus.REVIEW: frozenset(
        {PipelineStatus.APPROVED, PipelineStatus.DEFERRED, PipelineStatus.REJECTED}
    ),
    PipelineStatus.APPROVED: frozenset({PipelineStatus.REVIEW, PipelineStatus.SENT}),
    PipelineStatus.SENT: frozenset({PipelineStatus.WAITING_REPLY}),
    PipelineStatus.WAITING_REPLY: frozenset({PipelineStatus.REPLIED, PipelineStatus.CLOSED}),
    PipelineStatus.REPLIED: frozenset(
        {
            PipelineStatus.INTERVIEW,
            PipelineStatus.PROJECT_DISCUSSION,
            PipelineStatus.CONSULTING_DISCUSSION,
            PipelineStatus.REJECTED,
            PipelineStatus.OFFER,
            PipelineStatus.AGREEMENT,
            PipelineStatus.CLOSED,
        }
    ),
    PipelineStatus.INTERVIEW: frozenset(
        {PipelineStatus.OFFER, PipelineStatus.REJECTED, PipelineStatus.CLOSED}
    ),
    PipelineStatus.PROJECT_DISCUSSION: frozenset(
        {PipelineStatus.AGREEMENT, PipelineStatus.REJECTED, PipelineStatus.CLOSED}
    ),
    PipelineStatus.CONSULTING_DISCUSSION: frozenset(
        {PipelineStatus.AGREEMENT, PipelineStatus.REJECTED, PipelineStatus.CLOSED}
    ),
    PipelineStatus.OFFER: frozenset(
        {PipelineStatus.AGREEMENT, PipelineStatus.REJECTED, PipelineStatus.CLOSED}
    ),
    PipelineStatus.AGREEMENT: frozenset({PipelineStatus.CLOSED}),
    PipelineStatus.REJECTED: frozenset({PipelineStatus.CLOSED}),
    PipelineStatus.CLOSED: frozenset(),
}

DECISION_PIPELINE_STATUS: dict[OpportunityDecision, PipelineStatus] = {
    OpportunityDecision.OUTREACH: PipelineStatus.APPROVED_FOR_OUTREACH,
    OpportunityDecision.DEFER: PipelineStatus.DEFERRED,
    OpportunityDecision.DEEPER_RESEARCH: PipelineStatus.RESEARCH_PENDING,
    OpportunityDecision.NOT_RELEVANT: PipelineStatus.NOT_RELEVANT,
    OpportunityDecision.WATCHLIST: PipelineStatus.WATCHLIST,
}


def allowed_next_statuses(current: PipelineStatus) -> frozenset[PipelineStatus]:
    return ALLOWED_TRANSITIONS.get(current, frozenset())


def transition_is_allowed(
    current: PipelineStatus,
    target: PipelineStatus,
    *,
    via_owner_decision: bool = False,
) -> bool:
    if target == current:
        return True
    if target not in allowed_next_statuses(current):
        return False
    if current == PipelineStatus.DECISION_PENDING and target in DECISION_PIPELINE_STATUS.values():
        return via_owner_decision
    return True


def draft_generation_allowed(status: PipelineStatus, decision: OpportunityDecision) -> bool:
    return (
        status
        in {
            PipelineStatus.APPROVED_FOR_OUTREACH,
            PipelineStatus.DRAFT_READY,
            PipelineStatus.REVIEW,
        }
        and decision == OpportunityDecision.OUTREACH
    )
