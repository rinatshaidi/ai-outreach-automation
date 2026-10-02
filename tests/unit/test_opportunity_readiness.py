"""Contact-path acceptance tests for opportunity readiness."""

from datetime import UTC, datetime
from uuid import uuid4

from app.modules.crm.models import Contact
from app.modules.opportunities.models import CompanyOpportunity
from app.modules.opportunities.readiness import (
    ContactStatus,
    _contact_status,
    _source_backed_scenarios,
    _valid_contact,
    is_source_backed_opportunity,
)


def contact(**overrides: object) -> Contact:
    values: dict[str, object] = {
        "id": uuid4(),
        "company_id": uuid4(),
        "name": "Public Partnerships Team",
        "other_public_link": "https://example.com/contact-sales",
        "verification_status": "verified_public",
        "validation_status": "VERIFIED_CONTACT",
        "validated_at": datetime.now(UTC),
        "confidence": 0.9,
        "lawful_public_source_note": "Official public Contact Sales page",
        "do_not_contact": False,
    }
    values.update(overrides)
    return Contact(**values)


def test_verified_public_contact_path_is_actionable() -> None:
    item = contact()

    status, usable = _contact_status([item])

    assert _valid_contact(item) is True
    assert status == ContactStatus.FOUND
    assert usable == [item]


def test_role_name_without_real_channel_is_not_a_contact() -> None:
    item = contact(other_public_link=None)

    status, usable = _contact_status([item])

    assert _valid_contact(item) is False
    assert status == ContactStatus.NO_VALID_CONTACT
    assert usable == []


def test_unverified_public_path_is_partial() -> None:
    item = contact(
        verification_status="unverified",
        validation_status="UNVERIFIED_CONTACT",
        validated_at=None,
    )

    status, usable = _contact_status([item])

    assert _valid_contact(item) is False
    assert status == ContactStatus.PARTIAL
    assert usable == [item]


def test_do_not_contact_path_is_never_usable() -> None:
    item = contact(do_not_contact=True)

    status, usable = _contact_status([item])

    assert _valid_contact(item) is False
    assert status == ContactStatus.NO_VALID_CONTACT
    assert usable == []


def test_source_backed_proposed_opportunity_is_a_valid_collaboration_scenario() -> None:
    opportunity = CompanyOpportunity(
        company_id=uuid4(),
        opportunity_type="general_competence_fit",
        rationale="Source-backed project scenario",
        confidence=0.65,
        source_ids=[str(uuid4())],
        signal_ids=[],
        status="proposed",
    )

    assert _source_backed_scenarios([opportunity]) == ["Source-backed project scenario"]
    assert is_source_backed_opportunity(opportunity) is True


def test_unsupported_or_rejected_opportunity_is_not_a_collaboration_scenario() -> None:
    unsupported = CompanyOpportunity(
        company_id=uuid4(),
        opportunity_type="general_competence_fit",
        rationale="Unsupported hypothesis",
        confidence=0.3,
        source_ids=[],
        signal_ids=[],
        status="proposed",
    )
    rejected = CompanyOpportunity(
        company_id=uuid4(),
        opportunity_type="process_automation",
        rationale="Rejected scenario",
        confidence=0.2,
        source_ids=[str(uuid4())],
        signal_ids=[],
        status="rejected",
    )

    assert _source_backed_scenarios([unsupported, rejected]) == []
    assert is_source_backed_opportunity(unsupported) is False
    assert is_source_backed_opportunity(rejected) is False
