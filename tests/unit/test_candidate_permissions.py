from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.candidate_profile.models import (
    CandidateContact,
    CandidateFact,
    CandidateProfile,
    CandidateRule,
)
from app.modules.candidate_profile.schemas import FactPackPurpose, PermissionFields
from app.modules.candidate_profile.service import build_fact_pack, validate_permissions


def test_permission_dependencies_fail_closed() -> None:
    with pytest.raises(ValidationError, match="store_private is required"):
        PermissionFields(use_for_ai_analysis=True)

    with pytest.raises(ValidationError, match="use_in_draft is required"):
        PermissionFields(store_private=True, send_externally=True)


def test_fact_pack_only_includes_verified_and_permitted_records() -> None:
    profile = CandidateProfile(id=uuid4(), version=3)
    allowed = CandidateFact(
        id=uuid4(),
        profile_id=profile.id,
        fact_type="skill",
        text="Synthetic Python skill",
        verified=True,
        store_private=True,
        use_for_ai_analysis=True,
    )
    unverified = CandidateFact(
        id=uuid4(),
        profile_id=profile.id,
        fact_type="achievement",
        text="Synthetic unverified claim",
        verified=False,
        store_private=True,
        use_for_ai_analysis=True,
    )
    forbidden = CandidateFact(
        id=uuid4(),
        profile_id=profile.id,
        fact_type="technology",
        text="Synthetic forbidden technology",
        verified=True,
        store_private=True,
        use_for_ai_analysis=False,
    )
    rule = CandidateRule(
        id=uuid4(),
        profile_id=profile.id,
        rule_type="wording",
        text="Never use Expert",
        severity="block",
        priority=10,
        active=True,
    )

    pack = build_fact_pack(
        profile,
        [allowed, unverified, forbidden],
        [],
        [rule],
        FactPackPurpose.AI_ANALYSIS,
    )

    assert [fact.id for fact in pack.facts] == [allowed.id]
    assert set(pack.excluded_fact_ids) == {unverified.id, forbidden.id}
    assert pack.rules[0].text == "Never use Expert"
    assert pack.profile_version == 3


def test_external_contact_requires_verification_permission_and_signature_opt_in() -> None:
    profile = CandidateProfile(id=uuid4(), version=1)
    contact = CandidateContact(
        id=uuid4(),
        profile_id=profile.id,
        contact_type="email",
        value="synthetic@example.test",
        verified=True,
        store_private=True,
        use_in_draft=True,
        send_externally=True,
        use_in_signature=False,
        allowed_in_signature=False,
    )

    blocked = build_fact_pack(profile, [], [contact], [], FactPackPurpose.EXTERNAL_SEND)
    assert blocked.contacts == []

    contact.use_in_signature = True
    allowed = build_fact_pack(profile, [], [contact], [], FactPackPurpose.EXTERNAL_SEND)
    assert allowed.contacts[0].value == "synthetic@example.test"


def test_complete_entity_permission_validation() -> None:
    fact = CandidateFact(
        profile_id=uuid4(),
        fact_type="skill",
        text="Synthetic skill",
        store_private=True,
        use_in_draft=False,
        send_externally=True,
    )

    with pytest.raises(ValidationError, match="use_in_draft is required"):
        validate_permissions(fact)
