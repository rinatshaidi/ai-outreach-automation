"""Deterministic extraction, validation and ranking tests for Contact Discovery v1."""

import ipaddress
from uuid import uuid4

import httpx
import pytest

from app.modules.crm.contact_discovery import (
    ChannelCandidate,
    _is_relevant_official_path,
    _official_candidates,
    _role_score,
    _search_candidate,
    _validate_channel,
)
from app.modules.crm.models import Company, CompanySource, Contact
from app.modules.research.fetcher import SafeFetcher
from app.modules.search_tasks.executor import SearchResult


async def public_resolver(_: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    return [ipaddress.ip_address("93.184.216.34")]


def company() -> Company:
    return Company(
        id=uuid4(),
        name="ExampleCo",
        normalized_domain="example.com",
        is_synthetic=True,
    )


def test_official_page_extracts_multiple_public_channels() -> None:
    record = company()
    source = CompanySource(
        id=uuid4(),
        company_id=record.id,
        url="https://example.com/contact",
        source_type="official_public_web",
    )
    html = b"""
    <a href="mailto:partnerships@example.com">Partnerships</a>
    <a href="https://www.linkedin.com/company/exampleco">LinkedIn</a>
    <a href="https://wa.me/15551234567">WhatsApp</a>
    <a href="/careers">Careers</a>
    """

    candidates = _official_candidates(record, source, html, "text/html")
    channels = {
        channel.channel_type
        for candidate in candidates
        for channel in candidate.channels
    }

    assert channels >= {"email", "linkedin", "whatsapp", "official_form"}
    forms = {
        channel.value
        for candidate in candidates
        for channel in candidate.channels
        if channel.channel_type == "official_form"
    }
    assert forms == {"https://example.com/careers"}


def test_public_search_accepts_relevant_official_contact_page() -> None:
    candidate = _search_candidate(
        company(),
        SearchResult(
            title="ExampleCo - Contact sales",
            url="https://example.com/business/contact-sales",
        ),
    )

    assert candidate is not None
    assert candidate.channels[0].channel_type == "official_form"
    assert candidate.channels[0].source_type == "public_search"


def test_public_search_does_not_accept_unrelated_domain_as_official() -> None:
    candidate = _search_candidate(
        company(),
        SearchResult(
            title="ExampleCo contact list",
            url="https://directory.invalid/exampleco-contact",
        ),
    )

    assert candidate is None


def test_blog_article_is_not_mislabelled_as_contact_form() -> None:
    assert not _is_relevant_official_path("https://example.com/blog/contacting-our-team")
    assert not _is_relevant_official_path("https://example.com/insights/article?contact=true")
    assert _is_relevant_official_path("https://example.com/contact-partnerships")


def test_role_ranking_is_opportunity_aware() -> None:
    expansion = {"business_expansion"}

    assert _role_score("Head of Expansion", expansion) > _role_score("Press Office", expansion)
    assert _role_score("Customer Support", expansion) < _role_score("Hiring Team", expansion)


@pytest.mark.asyncio
async def test_reachable_official_form_is_verified_with_company_identity() -> None:
    record = company()
    contact = Contact(
        id=uuid4(),
        company_id=record.id,
        name="ExampleCo Business Development / Partnerships",
        role="Business Development / Partnerships",
    )
    public_fetcher = SafeFetcher(
        resolver=public_resolver,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text="<title>ExampleCo</title><h1>Contact our partnerships team</h1>",
            )
        ),
        respect_robots=False,
        minimum_host_interval=0,
    )
    channel = ChannelCandidate(
        channel_type="official_form",
        value="https://example.com/contact-partnerships",
        url="https://example.com/contact-partnerships",
        source_url="https://example.com/contact-partnerships",
        source_type="official_site",
        confidence=0.8,
        source_text="ExampleCo contact partnerships",
    )

    validation = await _validate_channel(channel, contact, record, public_fetcher)

    assert validation["status"] == "VERIFIED"
    assert validation["http_status"] == 200
