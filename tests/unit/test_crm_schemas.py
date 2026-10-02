"""Mini-CRM DTO validation tests."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.crm.schemas import CampaignCreate, CompanyCreate, ContactCreate


def test_company_domain_is_normalized() -> None:
    company = CompanyCreate(name="Synthetic Labs", normalized_domain="HTTPS://Example.TEST/jobs")

    assert company.normalized_domain == "example.test"


@pytest.mark.parametrize("domain", ["localhost", "bad domain.test", "https://"])
def test_company_rejects_invalid_domain(domain: str) -> None:
    with pytest.raises(ValidationError):
        CompanyCreate(name="Synthetic Labs", normalized_domain=domain)


def test_contact_requires_a_public_channel() -> None:
    with pytest.raises(ValidationError, match="public professional contact channel"):
        ContactCreate(company_id=uuid4(), name="Synthetic Person")


def test_verified_contact_requires_source_note_and_normalizes_email() -> None:
    with pytest.raises(ValidationError, match="lawful public source note"):
        ContactCreate(
            company_id=uuid4(),
            name="Synthetic Person",
            email="PERSON@EXAMPLE.TEST",
            verification_status="verified",
        )

    contact = ContactCreate(
        company_id=uuid4(),
        name="Synthetic Person",
        email="PERSON@EXAMPLE.TEST",
        verification_status="verified",
        lawful_public_source_note="Synthetic company team page",
    )
    assert contact.email == "person@example.test"


def test_campaign_daily_limit_is_bounded() -> None:
    with pytest.raises(ValidationError):
        CampaignCreate(name="Synthetic campaign", goal="Test outreach", daily_limit=501)
