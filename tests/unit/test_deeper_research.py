"""Bounded deeper-research selection tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.modules.crm.models import Company, CompanySource
from app.modules.research.deeper import MAX_RESEARCH_SOURCES, select_research_urls


def test_deeper_research_uses_distinct_categories_and_hard_limit() -> None:
    company = Company(
        id=uuid4(),
        name="Calibration Company",
        normalized_domain="example.com",
        is_synthetic=True,
    )
    now = datetime.now(UTC)
    urls = [
        "https://example.com/about",
        "https://example.com/about/team",
        "https://careers.example.com/",
        "https://careers.example.com/vacancy",
        "https://example.com/news",
        "https://example.com/blog",
        "https://example.com/leadership",
    ]
    sources = [
        CompanySource(
            id=uuid4(),
            company_id=company.id,
            url=url,
            source_type="official_public_web",
            http_status=200,
            fetched_at=now - timedelta(minutes=index),
        )
        for index, url in enumerate(urls)
    ]

    selected = select_research_urls(company, sources)

    assert 2 <= len(selected) <= MAX_RESEARCH_SOURCES
    assert "https://example.com/about" in selected
    assert "https://careers.example.com/" in selected
    assert len(selected) == len(set(selected))
