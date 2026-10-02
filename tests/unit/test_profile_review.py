from uuid import uuid4

import pytest

from app.modules.profile_review.models import CandidateProfileSection
from app.modules.profile_review.schemas import ProfileSectionType, ReviewDecision
from app.modules.profile_review.service import (
    PERMISSION_DEFAULTS,
    prepare_import_data,
    review_section,
)


class RecordingSession:
    def __init__(self) -> None:
        self.records: list[object] = []

    def add(self, record: object) -> None:
        self.records.append(record)


def test_profile_defines_exactly_twenty_three_independent_sections() -> None:
    assert len(ProfileSectionType) == 23
    assert len({item.value for item in ProfileSectionType}) == 23


def test_import_forces_verification_and_downstream_permissions_off() -> None:
    proposed, messages = prepare_import_data(
        "fact",
        {
            "fact_type": "achievement",
            "text": "Synthetic proposed achievement",
            "verified": True,
            "use_for_ai_analysis": True,
            "use_in_scoring": True,
            "use_in_draft": True,
            "send_externally": True,
            "publish_publicly": True,
        },
    )
    assert proposed["verified"] is False
    assert proposed["store_private"] is True
    for key in PERMISSION_DEFAULTS:
        if key != "store_private":
            assert proposed[key] is False
    assert any("permission ignored" in item for item in messages)


@pytest.mark.asyncio
async def test_section_verification_requires_prior_user_approval() -> None:
    section = CandidateProfileSection(
        id=uuid4(),
        profile_id=uuid4(),
        section_type="technical_skills",
        status="review_required",
        version=1,
        content_draft="Synthetic technical skills draft",
    )
    session = RecordingSession()
    with pytest.raises(ValueError, match="prior user approval"):
        await review_section(
            session,  # type: ignore[arg-type]
            section,
            decision=ReviewDecision.VERIFY,
            actor="owner",
            comment=None,
            content_hash=None,
            request_id="synthetic",
        )
    await review_section(
        session,  # type: ignore[arg-type]
        section,
        decision=ReviewDecision.APPROVE,
        actor="owner",
        comment="Explicit approval",
        content_hash=None,
        request_id="synthetic",
    )
    assert section.status == "user_approved"
    await review_section(
        session,  # type: ignore[arg-type]
        section,
        decision=ReviewDecision.VERIFY,
        actor="owner",
        comment="Explicit verification",
        content_hash=None,
        request_id="synthetic",
    )
    assert section.status == "verified"
