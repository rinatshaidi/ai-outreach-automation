"""Public contact URL validation tests."""

import ipaddress
from uuid import uuid4

import httpx
import pytest

from app.modules.crm.contact_presentation import present_contact
from app.modules.crm.contact_validation import classify_contact_for_outreach, validate_contact_path
from app.modules.crm.models import Company, Contact
from app.modules.crm.schemas import ContactValidationStatus
from app.modules.research.fetcher import SafeFetcher


async def public_resolver(_: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    return [ipaddress.ip_address("93.184.216.34")]


def records(url: str = "https://partners.airalo.com/contact-sales") -> tuple[Company, Contact]:
    company = Company(
        id=uuid4(),
        name="Airalo",
        normalized_domain="airalo.com",
        is_synthetic=True,
    )
    contact = Contact(
        id=uuid4(),
        company_id=company.id,
        name="Airalo Partners Sales Team",
        role="Official partnership contact",
        other_public_link=url,
        verification_status="verified_public",
        lawful_public_source_note="Official Airalo page",
    )
    return company, contact


def fetcher(handler: httpx.MockTransport) -> SafeFetcher:
    return SafeFetcher(
        resolver=public_resolver,
        transport=handler,
        respect_robots=False,
        minimum_host_interval=0,
    )


def test_support_mailbox_is_suppressed_with_schema_valid_priority() -> None:
    company, contact = records()
    contact.email = "help@example.com"

    classify_contact_for_outreach(contact)

    assert contact.do_not_contact is True
    assert contact.decision_priority == 2
    assert contact.decision_maker_role is None


def test_careers_mailbox_is_labeled_as_hr_and_explained_to_owner() -> None:
    company, contact = records()
    contact.email = "careers@example.com"

    classify_contact_for_outreach(contact, company.name)
    presentation = present_contact(contact, "ru")

    assert contact.decision_maker_role == "talent_acquisition"
    assert contact.decision_priority == 1
    assert presentation.role_label == "HR / рекрутинг"
    assert "вакансию" in presentation.guidance


def test_named_recruiter_keeps_their_public_name() -> None:
    company, contact = records()
    contact.name = "Alex Morgan"
    contact.role = "Recruiter"
    contact.linkedin = "https://www.linkedin.com/in/alex-morgan"

    classify_contact_for_outreach(contact, company.name)

    assert contact.name == "Alex Morgan"
    assert contact.decision_maker_role == "talent_acquisition"


def test_generic_public_channel_is_not_presented_as_a_named_person() -> None:
    company, contact = records()
    contact.email = "contact@example.com"
    contact.name = "Example Official Contact"
    contact.role = "Official company contact"

    classify_contact_for_outreach(contact, company.name)
    presentation = present_contact(contact, "ru")

    assert contact.decision_maker_role is None
    assert presentation.role_label == "Публичный контакт компании"
    assert "Персональный получатель не подтверждён" in presentation.guidance


def test_generic_sales_mailbox_is_not_promoted_to_a_business_leader() -> None:
    company, contact = records()
    contact.name = "Example Sales Team"
    contact.role = "Sales"
    contact.email = "sales@example.com"

    classify_contact_for_outreach(contact, company.name)

    assert contact.decision_maker_role is None
    assert contact.decision_priority == 2


def test_named_russian_founder_is_classified_without_renaming() -> None:
    company, contact = records()
    contact.name = "Анна Петрова"
    contact.role = "Основатель"
    contact.linkedin = "https://www.linkedin.com/in/anna-petrova"

    classify_contact_for_outreach(contact, company.name)
    presentation = present_contact(contact, "ru")

    assert contact.name == "Анна Петрова"
    assert contact.decision_maker_role == "founder"
    assert presentation.role_label == "Основатель / руководитель"


@pytest.mark.asyncio
async def test_existing_matching_official_page_is_verified() -> None:
    company, contact = records()
    validator = fetcher(
        httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text="<title>Airalo Partners</title><h1>Contact sales</h1>",
            )
        )
    )

    result = await validate_contact_path(contact, company, fetcher=validator)

    assert result.status == ContactValidationStatus.VERIFIED
    assert result.http_status == 200
    assert result.final_url == "https://partners.airalo.com/contact-sales"
    assert result.identity_match is True


@pytest.mark.asyncio
async def test_http_404_is_invalid() -> None:
    company, contact = records("https://www.airalo.com/about-us/missing-person")
    validator = fetcher(
        httpx.MockTransport(
            lambda _: httpx.Response(
                404,
                headers={"content-type": "text/html"},
                text="not found",
            )
        )
    )

    result = await validate_contact_path(contact, company, fetcher=validator)

    assert result.status == ContactValidationStatus.INVALID
    assert result.http_status == 404


@pytest.mark.asyncio
async def test_soft_404_is_invalid_even_with_http_200() -> None:
    company, contact = records()
    validator = fetcher(
        httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text="<title>Page not found</title><p>Something went wrong</p>",
            )
        )
    )

    result = await validate_contact_path(contact, company, fetcher=validator)

    assert result.status == ContactValidationStatus.INVALID
    assert result.http_status == 200
    assert result.error is not None and result.error.startswith("soft_404")


@pytest.mark.asyncio
async def test_existing_unrelated_page_is_only_partial() -> None:
    company, contact = records("https://unrelated.example/profile")
    validator = fetcher(
        httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text="<title>Unrelated profile</title>",
            )
        )
    )

    result = await validate_contact_path(contact, company, fetcher=validator)

    assert result.status == ContactValidationStatus.PARTIAL
    assert result.identity_match is False


@pytest.mark.asyncio
async def test_public_email_on_linked_careers_source_is_verified() -> None:
    company, contact = records()
    contact.other_public_link = None
    contact.email = "hiring@careers.example"
    validator = fetcher(
        httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text='<a href="mailto:hiring@careers.example">Careers</a>',
            )
        )
    )

    result = await validate_contact_path(
        contact,
        company,
        fetcher=validator,
        source_url="https://careers.example/jobs",
    )

    assert result.status == ContactValidationStatus.VERIFIED
    assert result.identity_match is True


@pytest.mark.asyncio
async def test_oversized_current_source_uses_exact_cached_email_provenance() -> None:
    company, contact = records()
    contact.other_public_link = None
    contact.email = "hiring@careers.example"
    validator = SafeFetcher(
        resolver=public_resolver,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "text/html", "content-length": "5000"},
                text="x" * 5000,
            )
        ),
        respect_robots=False,
        minimum_host_interval=0,
        max_bytes=100,
    )

    result = await validate_contact_path(
        contact,
        company,
        fetcher=validator,
        source_url="https://careers.example/jobs",
        source_text="Contact us at hiring@careers.example",
        source_http_status=200,
    )

    assert result.status == ContactValidationStatus.VERIFIED
    assert result.http_status == 200
    assert result.identity_match is True
