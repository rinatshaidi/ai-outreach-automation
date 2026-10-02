from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.search_tasks.executor import (
    PublicSearchResolver,
    reload_company_after_rollback,
)


class _SessionAfterFailure:
    def __init__(self, expected_id: object, company: object) -> None:
        self.expected_id = expected_id
        self.company = company
        self.rolled_back = False

    async def rollback(self) -> None:
        self.rolled_back = True

    async def get(self, model: object, company_id: object) -> object | None:
        assert self.rolled_back
        assert company_id == self.expected_id
        return self.company


@pytest.mark.asyncio
async def test_reload_company_after_rollback_uses_cached_scalar_id() -> None:
    """A rollback recovery must never need an expired Company ORM attribute."""

    company_id = uuid4()
    expected_company = object()
    session = _SessionAfterFailure(company_id, expected_company)

    restored = await reload_company_after_rollback(session, company_id)  # type: ignore[arg-type]

    assert restored is expected_company


class _DiscoveryProvider:
    available = True

    def __init__(self) -> None:
        self.limit = 0

    async def discover(self, _: str, limit: int) -> list[dict[str, str]]:
        self.limit = limit
        return [
            {"name": "Example", "official_url": "https://example.org"},
        ]


@pytest.mark.asyncio
async def test_daily_resolution_requests_a_bounded_reserve_pool() -> None:
    provider = _DiscoveryProvider()
    task = SimpleNamespace(
        company_name_or_url=None,
        task_type="find_companies",
        original_query="Find suitable companies",
        result_limit=3,
        parsed_country=None,
        parsed_industry=None,
    )

    resolved = await PublicSearchResolver(discovery_provider=provider).resolve(task)  # type: ignore[arg-type]

    assert provider.limit == 15
    assert [item.normalized_domain for item in resolved] == ["example.org"]
