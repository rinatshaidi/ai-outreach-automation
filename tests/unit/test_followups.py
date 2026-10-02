"""Deterministic Stage 8 scheduling and proposal rules."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.crm.models import Campaign
from app.modules.delivery.models import OutboundMessage
from app.modules.followups.schemas import ManualReplyCreate
from app.modules.followups.service import (
    add_business_days,
    followup_policy,
    proposal_for,
)


def test_five_business_days_skip_weekends_in_user_timezone() -> None:
    sent_on_friday = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)

    due = add_business_days(sent_on_friday, 5, "Europe/Moscow")

    assert due == datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


def test_due_calculation_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        add_business_days(datetime(2026, 8, 1), 5, "Europe/Moscow")
    with pytest.raises(ValueError, match="Unknown user timezone"):
        add_business_days(datetime.now(UTC), 1, "Invalid/Timezone")


def test_campaign_policy_defaults_to_one_followup_after_seven_days() -> None:
    campaign = Campaign(name="Synthetic", goal="Synthetic", followup_policy={})

    assert followup_policy(campaign) == (True, 7, 1)

    campaign.followup_policy = {"interval_business_days": "invalid", "max_followups": None}
    assert followup_policy(campaign) == (True, 7, 1)


def test_proposal_is_shorter_and_contains_no_new_candidate_facts() -> None:
    message = OutboundMessage(
        id=uuid4(),
        company_id=uuid4(),
        contact_id=uuid4(),
        campaign_id=uuid4(),
        draft_id=uuid4(),
        approval_id=uuid4(),
        delivery_mode="real",
        recipient_hash="synthetic-hash",
        recipient_masked="de***@***.com",
        subject="A measurable workflow pilot",
        body="A verified and evidence-based initial message. " * 20,
        delivery_status="sent",
        provider="synthetic",
        idempotency_key="synthetic-followup-unit-key",
    )

    subject, body, report, digest = proposal_for(message)

    assert subject == "Re: A measurable workflow pilot"
    assert len(body) < len(message.body)
    assert report["passed"] is True
    assert report["new_candidate_facts"] == []
    assert report["automatic_send_allowed"] is False
    assert len(digest) == 64


def test_manual_reply_timestamp_requires_timezone() -> None:
    with pytest.raises(ValueError, match="must include a timezone"):
        ManualReplyCreate(
            company_id=uuid4(),
            contact_id=uuid4(),
            outcome="replied",
            summary="Synthetic reply",
            occurred_at=datetime(2026, 8, 1, 12, 0),
        )
