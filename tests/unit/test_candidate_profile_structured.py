from datetime import date

import pytest
from pydantic import ValidationError

from app.modules.candidate_profile.schemas import (
    CandidateExperienceCreate,
    CandidateProfileUpsert,
    CandidateSkillCreate,
)


def test_experience_rejects_reversed_dates() -> None:
    with pytest.raises(ValidationError, match="ended_at cannot be before started_at"):
        CandidateExperienceCreate(
            position="Synthetic Operations Lead",
            started_at=date(2025, 2, 1),
            ended_at=date(2025, 1, 1),
            store_private=True,
        )


@pytest.mark.parametrize("level", ["proficient", "advanced"])
def test_high_skill_level_requires_evidence(level: str) -> None:
    with pytest.raises(ValidationError, match="require evidence"):
        CandidateSkillCreate(
            name="Synthetic negotiation skill",
            skill_group="business",
            actual_level=level,
            store_private=True,
        )


@pytest.mark.parametrize("skill_group", ["ai", "technology"])
def test_technical_skill_requires_explicit_limitations(skill_group: str) -> None:
    with pytest.raises(ValidationError, match="require explicit limitations"):
        CandidateSkillCreate(
            name="Synthetic technical skill",
            skill_group=skill_group,
            actual_level="practical",
            store_private=True,
        )


def test_remote_and_relocation_geographies_are_independent() -> None:
    profile = CandidateProfileUpsert(
        remote_work_countries=["Germany", "Netherlands"],
        relocation_countries=["Portugal"],
        business_trip_countries=["Poland"],
        workplace_formats=["remote", "relocation"],
    )

    assert profile.remote_work_countries == ["Germany", "Netherlands"]
    assert profile.relocation_countries == ["Portugal"]
    assert profile.business_trip_countries == ["Poland"]


def test_structured_record_permissions_fail_closed() -> None:
    with pytest.raises(ValidationError):
        CandidateExperienceCreate(
            position="Synthetic Project Lead",
            store_private=False,
            use_for_ai_analysis=True,
        )
