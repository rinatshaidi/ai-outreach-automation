from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import SQLAlchemyError

from app.infrastructure.db.session import get_db_session
from app.main import app


class HealthySession:
    async def execute(self, _: object) -> None:
        return None


class UnavailableSession:
    async def execute(self, _: object) -> None:
        raise SQLAlchemyError("synthetic database failure")


async def override_session(session: Any) -> AsyncIterator[Any]:
    yield session


@pytest.mark.asyncio
async def test_liveness_and_product_entrypoint() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        live = await client.get("/api/v1/health/live")
        page = await client.get("/")

    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    assert page.status_code == 303
    assert page.headers["location"] == "/companies"
    assert page.headers["x-content-type-options"] == "nosniff"
    assert page.headers["x-request-id"]


@pytest.mark.asyncio
async def test_openapi_exposes_mini_crm_core() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/openapi.json")

    paths = response.json()["paths"]
    assert "/api/v1/companies" in paths
    assert {"get", "post"} <= set(paths["/api/v1/companies"])
    assert {"get", "post"} <= set(paths["/api/v1/search-tasks"])
    assert "/api/v1/search-tasks/{task_id}/start" in paths
    assert "/api/v1/search-tasks/{task_id}/cancel" in paths
    assert "/api/v1/search-tasks/{task_id}/results" in paths
    assert "/api/v1/contacts" in paths
    assert "/api/v1/jobs" in paths
    assert "/api/v1/campaigns" in paths
    assert "/api/v1/communications" in paths
    assert "/api/v1/dashboard" in paths
    assert "/api/v1/companies/{company_id}/sources" in paths
    assert "/api/v1/companies/{company_id}/signals" in paths
    assert "/api/v1/companies/{company_id}/opportunities" in paths
    assert "/api/v1/companies/{company_id}/assessments" in paths
    assert "/api/v1/companies/{company_id}/recommendations" in paths
    assert "/api/v1/companies/{company_id}/recommendations/{recommendation_id}/decision" in paths
    assert "/api/v1/companies/{company_id}/research" in paths
    assert "/api/v1/companies/{company_id}/research/runs" in paths
    assert "/api/v1/companies/{company_id}/research/facts" in paths
    assert "/api/v1/companies/{company_id}/research/hypotheses" in paths
    assert "/api/v1/companies/{company_id}/relevance/calculate" in paths
    assert "/api/v1/companies/{company_id}/relevance/thresholds" in paths
    assert "/api/v1/companies/{company_id}/relevance/overrides" in paths
    assert "/api/v1/companies/{company_id}/relevance/assessments/{assessment_id}/override" in paths
    assert "/api/v1/companies/{company_id}/generation/generate" in paths
    assert "/api/v1/companies/{company_id}/generation/runs" in paths
    assert "/api/v1/companies/{company_id}/generation/drafts" in paths
    assert "/api/v1/drafts" in paths
    assert "/api/v1/drafts/{draft_id}" in paths
    assert "/api/v1/drafts/{draft_id}/edit" in paths
    assert "/api/v1/drafts/{draft_id}/regenerate" in paths
    assert "/api/v1/drafts/{draft_id}/recipient" in paths
    assert "/api/v1/drafts/{draft_id}/approve" in paths
    assert "/api/v1/drafts/{draft_id}/defer" in paths
    assert "/api/v1/drafts/{draft_id}/reject" in paths
    assert "/api/v1/drafts/{draft_id}/do-not-contact" in paths
    assert "/api/v1/drafts/{draft_id}/send-test" in paths
    assert "/api/v1/drafts/{draft_id}/send" in paths
    assert "/api/v1/messages" in paths
    assert "/api/v1/followups" in paths
    assert "/api/v1/followups/refresh-due" in paths
    assert "/api/v1/followups/{followup_id}/approve" in paths
    assert "/api/v1/followups/{followup_id}/defer" in paths
    assert "/api/v1/followups/{followup_id}/reject" in paths
    assert "/api/v1/followups/{followup_id}/cancel" in paths
    assert "/api/v1/communications/replies" in paths
    assert "/api/v1/analytics" in paths
    assert "/api/v1/auth/session" in paths
    assert "/api/v1/candidate-profile/sections" in paths
    assert "/api/v1/candidate-profile/sections/{section_type}/review" in paths
    assert "/api/v1/candidate-profile/readiness" in paths
    assert "/api/v1/candidate-profile/records/{entity_type}/{entity_id}/verification" in paths
    assert "/api/v1/candidate-profile/records/verify-reviewed" in paths
    assert "/api/v1/candidate-profile/imports" in paths
    assert "/api/v1/candidate-profile/imports/{batch_id}/validate" in paths
    assert "/api/v1/candidate-profile/imports/{batch_id}/apply" in paths
    assert "/api/v1/pilot/readiness" in paths


@pytest.mark.asyncio
async def test_readiness_checks_database() -> None:
    async def healthy_override() -> AsyncIterator[HealthySession]:
        yield HealthySession()

    app.dependency_overrides[get_db_session] = healthy_override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


@pytest.mark.asyncio
async def test_readiness_fails_without_database_and_leaks_no_details() -> None:
    async def unavailable_override() -> AsyncIterator[UnavailableSession]:
        yield UnavailableSession()

    app.dependency_overrides[get_db_session] = unavailable_override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "database_unavailable"
    assert "synthetic database failure" not in response.text
