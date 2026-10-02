"""Mini-CRM integration tests against the configured PostgreSQL schema."""

import ipaddress
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.crm import get_contact_validator
from app.api.delivery import get_email_adapter, get_test_email_adapter
from app.api.research import get_safe_fetcher
from app.config import Settings, get_settings
from app.infrastructure.db.session import engine, get_db_session
from app.main import app
from app.modules.audit.models import AuditEvent
from app.modules.crm.models import Company, Contact
from app.modules.delivery.models import OutboundMessage
from app.modules.generation.models import DraftApproval, MessageDraft
from app.modules.generation.rewrite import RewrittenMessage, get_ai_rewrite_provider
from app.modules.profile_review.models import PilotCalibrationNote
from app.modules.research.fetcher import FetchedDocument, SafeFetcher, SafeFetchError
from app.modules.research.models import CompanyFact, CompanyTaskHypothesis
from app.modules.safety.models import OwnerSafetyPolicy
from app.modules.search_tasks.executor import ResolvedCompany, execute_claimed_task
from app.modules.search_tasks.models import SearchTask, SearchTaskResult
from app.modules.search_tasks.worker import recover_interrupted_tasks_in_session

pytestmark = pytest.mark.integration

CRM_TABLES = {
    "campaigns",
    "communication_events",
    "companies",
    "contacts",
    "contact_channels",
    "job_openings",
}

CANDIDATE_OPPORTUNITY_TABLES = {
    "candidate_experiences",
    "candidate_skills",
    "candidate_strengths",
}

OPPORTUNITY_CRM_TABLES = {
    "company_sources",
    "opportunity_signals",
    "company_opportunities",
    "opportunity_assessments",
    "positioning_recommendations",
    "opportunity_decision_events",
}

RESEARCH_TABLES = {
    "company_facts",
    "company_task_hypotheses",
    "research_runs",
    "company_decision_syntheses",
}
RELEVANCE_TABLES = {"opportunity_assessment_overrides"}
GENERATION_TABLES = {
    "generation_runs",
    "message_drafts",
    "sender_voice_profiles",
    "approved_writing_examples",
}
REVIEW_TABLES = {"draft_approvals", "draft_review_events"}
DELIVERY_TABLES = {"outbound_messages", "delivery_attempts"}
FOLLOWUP_TABLES = {"followups"}
PERSONALIZATION_TABLES = {
    "users",
    "auth_sessions",
    "login_attempts",
    "candidate_profile_sections",
    "profile_review_events",
    "profile_import_batches",
    "profile_import_items",
    "pilot_calibration_notes",
}
SEARCH_TASK_TABLES = {"search_tasks", "search_task_results"}
MAILBOX_TABLES = {
    "mailbox_connections",
    "oauth_authorization_states",
    "inbound_messages",
}
SAFETY_TABLES = {"owner_safety_policies"}


class FakeAIRewriteProvider:
    provider_name = "synthetic-ai-provider"
    model_name = "synthetic-rewrite-model"

    async def rewrite(
        self,
        *,
        context: object,
        subject: str,
        body: str,
        instruction: str,
        message_format: str = "expanded",
        tone: str = "professional",
    ) -> RewrittenMessage:
        del context, message_format, tone
        return RewrittenMessage(
            subject=f"{subject} — revised",
            body=f"{body}\n\nOwner instruction applied: {instruction}",
        )


class FakeEmailAdapter:
    provider_name = "synthetic-smtp"

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def send(self, *, recipient: str, subject: str, body: str) -> str:
        self.calls.append({"recipient": recipient, "subject": subject, "body": body})
        return f"synthetic-message-{len(self.calls)}"


@pytest.fixture
async def crm_client() -> AsyncIterator[AsyncClient]:
    """Let API commits use savepoints and roll the entire test back afterward."""

    try:
        connection = await engine.connect()
    except (OSError, SQLAlchemyError) as exc:
        pytest.skip(f"Configured PostgreSQL is unavailable: {type(exc).__name__}")

    outer_transaction = await connection.begin()
    session = AsyncSession(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    previous_override = app.dependency_overrides.get(get_db_session)
    app.dependency_overrides[get_db_session] = override_session
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=True)
        async with AsyncClient(transport=transport, base_url="http://postgres-test") as client:
            client._test_session = session  # type: ignore[attr-defined]
            yield client
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_db_session, None)
        else:
            app.dependency_overrides[get_db_session] = previous_override
        await session.close()
        if outer_transaction.is_active:
            await outer_transaction.rollback()
        await connection.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_mini_crm_schema_is_applied() -> None:
    try:
        async with engine.connect() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            tables = set(
                (
                    await connection.execute(
                        text(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_schema = 'public'"
                        )
                    )
                ).scalars()
            )
            preserved_counts = {
                table: await connection.scalar(text(f"SELECT count(*) FROM {table}"))  # noqa: S608
                for table in (
                    "candidate_profiles",
                    "candidate_facts",
                    "candidate_contacts",
                    "candidate_rules",
                    "consent_events",
                )
            }
            new_counts = {
                table: await connection.scalar(text(f"SELECT count(*) FROM {table}"))  # noqa: S608
                for table in (
                    CANDIDATE_OPPORTUNITY_TABLES
                    | OPPORTUNITY_CRM_TABLES
                    | RESEARCH_TABLES
                    | RELEVANCE_TABLES
                    | GENERATION_TABLES
                    | REVIEW_TABLES
                    | DELIVERY_TABLES
                    | FOLLOWUP_TABLES
                    | PERSONALIZATION_TABLES
                    | SEARCH_TASK_TABLES
                    | MAILBOX_TABLES
                    | SAFETY_TABLES
                )
            }
    except (OSError, SQLAlchemyError) as exc:
        pytest.skip(f"Configured PostgreSQL is unavailable: {type(exc).__name__}")
    finally:
        await engine.dispose()

    assert revision == "20260818_0023"
    assert tables >= (
        CRM_TABLES
        | CANDIDATE_OPPORTUNITY_TABLES
        | OPPORTUNITY_CRM_TABLES
        | RESEARCH_TABLES
        | RELEVANCE_TABLES
        | GENERATION_TABLES
        | REVIEW_TABLES
        | DELIVERY_TABLES
        | FOLLOWUP_TABLES
        | PERSONALIZATION_TABLES
        | SEARCH_TASK_TABLES
        | MAILBOX_TABLES
        | SAFETY_TABLES
    )
    assert preserved_counts["candidate_profiles"] >= 1
    assert all(isinstance(count, int) and count >= 0 for count in preserved_counts.values())
    # Stage 9 can seed an idempotent synthetic portfolio in an already migrated
    # development database, so schema verification must not require these tables
    # to remain empty after the migration has been exercised.
    assert all(isinstance(count, int) and count >= 0 for count in new_counts.values())


@pytest.mark.asyncio
async def test_candidate_opportunity_profile_crud_and_locking(crm_client: AsyncClient) -> None:
    profile_response = await crm_client.get("/api/v1/candidate-profile")
    assert profile_response.status_code == 200, profile_response.text
    profile = profile_response.json()

    update_response = await crm_client.put(
        "/api/v1/candidate-profile",
        json={
            "version": profile["version"],
            "display_name": profile["display_name"],
            "professional_title": "Synthetic Opportunity Operator",
            "total_years_experience": 8.5,
            "management_years_experience": 3,
            "desired_roles": ["Operations Lead"],
            "adjacent_roles": ["Project Lead"],
            "excluded_roles": ["Commission-only sales"],
            "preferred_industries": ["Synthetic Technology"],
            "remote_work_countries": ["Germany", "Netherlands"],
            "relocation_countries": ["Portugal"],
            "business_trip_countries": ["Poland"],
            "collaboration_formats": ["full_time", "project_based"],
            "workplace_formats": ["remote", "relocation"],
            "temporary_relocation_allowed": True,
            "on_the_ground_launch_allowed": False,
            "profile_status": "review_required",
        },
    )
    assert update_response.status_code == 200, update_response.text
    updated_profile = update_response.json()
    assert updated_profile["profile_status"] == "review_required"
    blocked_global_verification = await crm_client.put(
        "/api/v1/candidate-profile",
        json={
            "version": updated_profile["version"],
            "profile_status": "verified",
        },
    )
    assert blocked_global_verification.status_code == 422
    assert blocked_global_verification.json()["detail"]["code"] == "profile_review_required"
    assert updated_profile["remote_work_countries"] == ["Germany", "Netherlands"]
    assert updated_profile["relocation_countries"] == ["Portugal"]

    experience_response = await crm_client.post(
        "/api/v1/candidate-experiences",
        json={
            "position": "Synthetic Operations Lead",
            "organization_label": "Synthetic Company",
            "project_types": ["market launch"],
            "negotiations": True,
            "launches": True,
            "store_private": True,
            "use_for_ai_analysis": True,
        },
    )
    assert experience_response.status_code == 201, experience_response.text
    experience = experience_response.json()

    skill_response = await crm_client.post(
        "/api/v1/candidate-skills",
        json={
            "name": "Synthetic AI workflow design",
            "skill_group": "ai",
            "actual_level": "practical",
            "limitations": "No claim of model training expertise",
            "store_private": True,
        },
    )
    assert skill_response.status_code == 201, skill_response.text
    skill = skill_response.json()

    strength_response = await crm_client.post(
        "/api/v1/candidate-strengths",
        json={
            "strength_type": "project_launch",
            "text": "Structures a synthetic launch into accountable workstreams",
            "evidence": "Synthetic integration fixture",
            "store_private": True,
        },
    )
    assert strength_response.status_code == 201, strength_response.text
    strength = strength_response.json()

    stale = await crm_client.patch(
        f"/api/v1/candidate-experiences/{experience['id']}",
        json={"version": 99, "responsibility_level": "lead"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "version_conflict"

    listed = await crm_client.get("/api/v1/candidate-skills")
    assert listed.status_code == 200
    assert any(item["id"] == skill["id"] for item in listed.json())

    for collection, record in (
        ("candidate-experiences", experience),
        ("candidate-skills", skill),
        ("candidate-strengths", strength),
    ):
        response = await crm_client.delete(
            f"/api/v1/{collection}/{record['id']}", params={"version": record["version"]}
        )
        assert response.status_code == 204, response.text


@pytest.mark.asyncio
async def test_profile_sections_and_preview_first_import(crm_client: AsyncClient) -> None:
    sections_response = await crm_client.get("/api/v1/candidate-profile/sections")
    assert sections_response.status_code == 200, sections_response.text
    sections = sections_response.json()
    assert len(sections) == 23
    technical = next(item for item in sections if item["section_type"] == "technical_skills")
    if technical["status"] == "verified":
        corrected = await crm_client.post(
            "/api/v1/candidate-profile/sections/technical_skills/review",
            json={
                "version": technical["version"],
                "decision": "correct",
                "comment": "Synthetic test-only reset inside rolled-back transaction",
            },
        )
        assert corrected.status_code == 200, corrected.text
        technical = corrected.json()

    positioning = next(item for item in sections if item["section_type"] == "positioning")
    if positioning["status"] not in {"draft", "review_required"}:
        reset_positioning = await crm_client.post(
            "/api/v1/candidate-profile/sections/positioning/review",
            json={
                "version": positioning["version"],
                "decision": "correct",
                "comment": "Synthetic test-only reset inside rolled-back transaction",
            },
        )
        assert reset_positioning.status_code == 200, reset_positioning.text
        positioning = reset_positioning.json()
    section_content = "Readable synthetic positioning draft for explicit owner review."
    web_review = await crm_client.post(
        "/candidate-profile/sections/positioning/review",
        data={
            "version": positioning["version"],
            "decision": "approve",
            "content": section_content,
            "comment": "Synthetic owner-approved text",
        },
        follow_redirects=False,
    )
    assert web_review.status_code == 303, web_review.text
    positioning_after = (
        await crm_client.get("/api/v1/candidate-profile/sections/positioning")
    ).json()
    assert positioning_after["status"] == "user_approved"
    assert positioning_after["content_draft"] == section_content
    assert len(positioning_after["content_hash"]) == 64
    profile_page = await crm_client.get("/candidate-profile")
    assert profile_page.status_code == 200, profile_page.text
    assert "Проверка и согласование профиля" in profile_page.text
    assert "Сохранить и подтвердить" in profile_page.text
    assert section_content in profile_page.text
    assert "Позиционирование" in profile_page.text

    if technical["status"] == "user_approved":
        approved_data = technical
    else:
        approved = await crm_client.post(
            "/api/v1/candidate-profile/sections/technical_skills/review",
            json={
                "version": technical["version"],
                "decision": "approve",
                "comment": "Explicit synthetic owner approval",
            },
        )
        assert approved.status_code == 200, approved.text
        approved_data = approved.json()
        assert approved_data["status"] == "user_approved"
    verified = await crm_client.post(
        "/api/v1/candidate-profile/sections/technical_skills/review",
        json={
            "version": approved_data["version"],
            "decision": "verify",
            "comment": "Explicit second-step verification",
        },
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "verified"

    suffix = uuid4().hex[:10]
    before_skills = (await crm_client.get("/api/v1/candidate-skills")).json()
    preview = await crm_client.post(
        "/api/v1/candidate-profile/imports",
        json={
            "source_filename": f"synthetic-{suffix}.json",
            "items": [
                {
                    "section_type": "technical_skills",
                    "entity_type": "skill",
                    "data": {
                        "name": f"Synthetic Skill {suffix}",
                        "skill_group": "technology",
                        "actual_level": "practical",
                        "limitations": "Synthetic preview-only limitation",
                        "use_in_scoring": True,
                    },
                }
            ],
        },
    )
    assert preview.status_code == 201, preview.text
    batch = preview.json()
    assert batch["status"] == "preview_ready"
    assert batch["validation_report"]["automatic_apply"] is False
    item = batch["items"][0]
    assert item["operation"] == "proposed_create"
    assert item["default_permissions"]["use_in_scoring"] is False
    assert item["proposed_data"]["verified"] is False
    assert item["proposed_data"]["use_in_scoring"] is False
    assert len((await crm_client.get("/api/v1/candidate-skills")).json()) == len(before_skills)

    validated = await crm_client.post(f"/api/v1/candidate-profile/imports/{batch['id']}/validate")
    assert validated.status_code == 200, validated.text
    assert validated.json()["status"] == "review_required"

    decision = await crm_client.post(
        f"/api/v1/candidate-profile/imports/{batch['id']}/items/{item['id']}/decision",
        json={"version": item["version"], "decision": "approved"},
    )
    assert decision.status_code == 200, decision.text
    applied = await crm_client.post(f"/api/v1/candidate-profile/imports/{batch['id']}/apply")
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "applied"
    skills = (await crm_client.get("/api/v1/candidate-skills")).json()
    imported = next(item for item in skills if item["name"] == f"Synthetic Skill {suffix}")
    assert imported["verified"] is False
    assert imported["store_private"] is True
    assert imported["use_in_scoring"] is False
    assert imported["use_in_draft"] is False

    readiness = await crm_client.get("/api/v1/pilot/readiness")
    assert readiness.status_code == 200, readiness.text
    assert readiness.json()["safe_local_flags"] is True
    assert readiness.json()["owner_acceptance_required"] is True


@pytest.mark.asyncio
async def test_candidate_profile_form_reports_invalid_enum_without_losing_values(
    crm_client: AsyncClient,
) -> None:
    before_response = await crm_client.get("/api/v1/candidate-profile")
    assert before_response.status_code == 200, before_response.text
    before = before_response.json()
    common_form = {
        "version": str(before["version"]),
        "display_name": "Regression Candidate",
        "professional_title": "AI Automation with Business Background",
        "location": "Krasnodar, Russia",
        "summary": "Regression profile form preserving submitted values.",
        "total_years_experience": "10+",
        "management_years_experience": "10+",
        "desired_roles": "AI Automation, Project Management",
        "preferred_countries": "Любая страна",
        "collaboration_formats": (
            "full_time, part_time, project_based, contract, consulting, advisory"
        ),
        "target_income": "2000 USD full-time; project work by agreement",
        "temporary_relocation_allowed": "true",
        "on_the_ground_launch_allowed": "true",
        "profile_status": "review_required",
    }
    invalid_response = await crm_client.post(
        "/candidate-profile/profile",
        data={
            **common_form,
            "workplace_formats": "remote, temporary_relocation, business_trips",
        },
    )
    assert invalid_response.status_code == 422, invalid_response.text
    assert "temporary_relocation" in invalid_response.text
    assert "business_trips" in invalid_response.text
    assert "Допустимо только" in invalid_response.text
    assert "Regression Candidate" in invalid_response.text
    unchanged = (await crm_client.get("/api/v1/candidate-profile")).json()
    assert unchanged["version"] == before["version"]
    assert unchanged["display_name"] == before["display_name"]

    valid_response = await crm_client.post(
        "/candidate-profile/profile",
        data={**common_form, "workplace_formats": "remote, hybrid, on_site, relocation"},
        follow_redirects=False,
    )
    assert valid_response.status_code == 303, valid_response.text
    saved = (await crm_client.get("/api/v1/candidate-profile")).json()
    assert saved["display_name"] == "Regression Candidate"
    assert saved["total_years_experience"] == 10.0
    assert saved["management_years_experience"] == 10.0
    assert saved["preferred_countries"] == ["Любая страна"]
    assert saved["collaboration_formats"] == [
        "full_time",
        "part_time",
        "project_based",
        "contract",
        "consulting",
        "advisory",
    ]
    assert saved["workplace_formats"] == ["remote", "hybrid", "on_site", "relocation"]
    assert saved["temporary_relocation_allowed"] is True
    assert saved["on_the_ground_launch_allowed"] is True
    assert saved["target_income"] == common_form["target_income"]
    assert saved["profile_status"] == "review_required"
    page = await crm_client.get("/candidate-profile")
    assert page.status_code == 200, page.text
    assert "Regression Candidate" in page.text


@pytest.mark.asyncio
async def test_candidate_experience_web_validation_duplicate_edit_and_delete(
    crm_client: AsyncClient,
) -> None:
    suffix = uuid4().hex[:12]
    position = f"Synthetic Director {suffix}"
    organization = f"Synthetic Organization {suffix}"
    base_form = {
        "position": f"Должность: {position}",
        "organization_label": f"Организация: {organization}",
        "industry": "Отрасль: Synthetic Infrastructure",
        "started_at": "2016-04-11",
        "ended_at": "",
        "project_types": "Типы проектов: launch, reconstruction",
        "responsibility_level": "Project and operational leadership",
        "team_size_max": "Макс. команда: 300",
        "project_geographies": "География проектов: Synthetic Region",
        "contractor_management": "true",
        "negotiations": "true",
        "store_private": "true",
    }
    before = (await crm_client.get("/api/v1/candidate-experiences")).json()

    too_long = await crm_client.post(
        "/candidate-profile/experiences",
        data={**base_form, "responsibility_level": "R" * 161},
    )
    assert too_long.status_code == 422, too_long.text
    assert "максимум 160 символов" in too_long.text
    assert position in too_long.text
    after_invalid = (await crm_client.get("/api/v1/candidate-experiences")).json()
    assert len(after_invalid) == len(before)

    created_response = await crm_client.post(
        "/candidate-profile/experiences", data=base_form, follow_redirects=False
    )
    assert created_response.status_code == 303, created_response.text
    created = next(
        item
        for item in (await crm_client.get("/api/v1/candidate-experiences")).json()
        if item["position"] == position
    )
    assert created["organization_label"] == organization
    assert created["industry"] == "Synthetic Infrastructure"
    assert created["project_types"] == ["launch", "reconstruction"]
    assert created["team_size_max"] == 300
    assert created["project_geographies"] == ["Synthetic Region"]

    duplicate = await crm_client.post("/candidate-profile/experiences", data=base_form)
    assert duplicate.status_code == 422, duplicate.text
    assert "Похожая запись уже существует" in duplicate.text
    assert str(created["id"]) in duplicate.text
    after_warning = (await crm_client.get("/api/v1/candidate-experiences")).json()
    assert sum(item["position"] == position for item in after_warning) == 1

    confirmed_duplicate = await crm_client.post(
        "/candidate-profile/experiences",
        data={**base_form, "confirm_duplicate": "true"},
        follow_redirects=False,
    )
    assert confirmed_duplicate.status_code == 303, confirmed_duplicate.text
    duplicates = [
        item
        for item in (await crm_client.get("/api/v1/candidate-experiences")).json()
        if item["position"] == position
    ]
    assert len(duplicates) == 2
    edited_record = max(duplicates, key=lambda item: item["created_at"])
    edited_position = f"Synthetic Operations Director {suffix}"
    edit_response = await crm_client.post(
        f"/candidate-profile/experiences/{edited_record['id']}/edit",
        data={
            **base_form,
            "version": str(edited_record["version"]),
            "position": edited_position,
        },
        follow_redirects=False,
    )
    assert edit_response.status_code == 303, edit_response.text
    edited = next(
        item
        for item in (await crm_client.get("/api/v1/candidate-experiences")).json()
        if item["id"] == edited_record["id"]
    )
    assert edited["position"] == edited_position
    assert edited["team_size_max"] == 300

    not_confirmed = await crm_client.post(
        f"/candidate-profile/experiences/{edited['id']}/delete",
        data={"version": str(edited["version"])},
    )
    assert not_confirmed.status_code == 422, not_confirmed.text
    assert "Удаление отменено" in not_confirmed.text
    assert any(
        item["id"] == edited["id"]
        for item in (await crm_client.get("/api/v1/candidate-experiences")).json()
    )

    deleted = await crm_client.post(
        f"/candidate-profile/experiences/{edited['id']}/delete",
        data={"version": str(edited["version"]), "confirm_delete": "yes"},
        follow_redirects=False,
    )
    assert deleted.status_code == 303, deleted.text
    remaining = (await crm_client.get("/api/v1/candidate-experiences")).json()
    assert not any(item["id"] == edited["id"] for item in remaining)
    assert any(item["id"] == created["id"] for item in remaining)

    session: AsyncSession = crm_client._test_session  # type: ignore[attr-defined]
    audit = await session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "candidate_experience_deleted",
            AuditEvent.entity_id == str(edited["id"]),
        )
    )
    assert audit is not None
    assert audit.result == "success"
    page = await crm_client.get("/candidate-profile")
    assert page.status_code == 200, page.text
    assert position in page.text


@pytest.mark.asyncio
async def test_candidate_skill_card_can_be_opened_and_edited(
    crm_client: AsyncClient,
) -> None:
    suffix = uuid4().hex[:12]
    created_response = await crm_client.post(
        "/api/v1/candidate-skills",
        json={
            "name": f"Synthetic Skill {suffix}",
            "skill_group": "business",
            "actual_level": "practical",
            "duration_months": 12,
            "store_private": True,
        },
    )
    assert created_response.status_code == 201, created_response.text
    created = created_response.json()

    page = await crm_client.get("/candidate-profile")
    assert page.status_code == 200, page.text
    assert f"/candidate-profile/skills/{created['id']}/edit" in page.text
    assert "нажмите для просмотра и исправления" in page.text

    invalid = await crm_client.post(
        f"/candidate-profile/skills/{created['id']}/edit",
        data={
            "version": str(created["version"]),
            "name": created["name"],
            "skill_group": "business",
            "actual_level": "proficient",
            "duration_months": "12",
            "evidence": "",
            "store_private": "true",
        },
    )
    assert invalid.status_code == 422, invalid.text
    assert "proficient and advanced skills require evidence" in invalid.text

    edited_name = f"Edited Synthetic Skill {suffix}"
    edited_response = await crm_client.post(
        f"/candidate-profile/skills/{created['id']}/edit",
        data={
            "version": str(created["version"]),
            "name": edited_name,
            "skill_group": "business",
            "actual_level": "proficient",
            "duration_months": "18",
            "evidence": "Synthetic regression evidence",
            "verified_results": "Synthetic local result",
            "store_private": "true",
        },
        follow_redirects=False,
    )
    assert edited_response.status_code == 303, edited_response.text
    edited = next(
        item
        for item in (await crm_client.get("/api/v1/candidate-skills")).json()
        if item["id"] == created["id"]
    )
    assert edited["name"] == edited_name
    assert edited["actual_level"] == "proficient"
    assert edited["duration_months"] == 18
    assert edited["evidence"] == "Synthetic regression evidence"


@pytest.mark.asyncio
async def test_candidate_fact_and_contact_can_be_deleted_with_confirmation(
    crm_client: AsyncClient,
) -> None:
    suffix = uuid4().hex[:12]
    fact_response = await crm_client.post(
        "/api/v1/candidate-facts",
        json={
            "fact_type": "technology",
            "text": f"Synthetic removable fact {suffix}",
            "store_private": True,
        },
    )
    assert fact_response.status_code == 201, fact_response.text
    fact = fact_response.json()
    contact_response = await crm_client.post(
        "/api/v1/candidate-contacts",
        json={
            "contact_type": "email",
            "value": f"removable-{suffix}@example.test",
            "store_private": True,
        },
    )
    assert contact_response.status_code == 201, contact_response.text
    contact = contact_response.json()

    page = await crm_client.get("/candidate-profile")
    assert f"/candidate-profile/facts/{fact['id']}/delete" in page.text
    assert f"/candidate-profile/contacts/{contact['id']}/delete" in page.text

    refused = await crm_client.post(
        f"/candidate-profile/facts/{fact['id']}/delete",
        data={"version": str(fact["version"])},
    )
    assert refused.status_code == 422, refused.text
    assert "Удаление отменено" in refused.text

    fact_deleted = await crm_client.post(
        f"/candidate-profile/facts/{fact['id']}/delete",
        data={"version": str(fact["version"]), "confirm_delete": "yes"},
        follow_redirects=False,
    )
    assert fact_deleted.status_code == 303, fact_deleted.text
    contact_deleted = await crm_client.post(
        f"/candidate-profile/contacts/{contact['id']}/delete",
        data={"version": str(contact["version"]), "confirm_delete": "yes"},
        follow_redirects=False,
    )
    assert contact_deleted.status_code == 303, contact_deleted.text
    assert not any(
        item["id"] == fact["id"]
        for item in (await crm_client.get("/api/v1/candidate-facts")).json()
    )
    assert not any(
        item["id"] == contact["id"]
        for item in (await crm_client.get("/api/v1/candidate-contacts")).json()
    )

    session: AsyncSession = crm_client._test_session  # type: ignore[attr-defined]
    fact_audit = await session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "candidate_fact_deleted",
            AuditEvent.entity_id == str(fact["id"]),
        )
    )
    contact_audit = await session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "candidate_contact_deleted",
            AuditEvent.entity_id == str(contact["id"]),
        )
    )
    assert fact_audit is not None
    assert contact_audit is not None


@pytest.mark.asyncio
async def test_opportunity_foundation_pipeline_and_owner_decision(crm_client: AsyncClient) -> None:
    suffix = uuid4().hex[:12]
    company_response = await crm_client.post(
        "/api/v1/companies",
        json={
            "name": f"Opportunity Company {suffix}",
            "normalized_domain": f"opportunity-{suffix}.example",
            "is_synthetic": True,
            "country": "Synthetic Region",
            "description": "Synthetic expansion company used only by the integration test.",
            "language_signals": ["en"],
        },
    )
    assert company_response.status_code == 201, company_response.text
    company = company_response.json()
    company_id = company["id"]

    for expected_version, target in (
        (1, "research_pending"),
        (2, "researched"),
    ):
        response = await crm_client.patch(
            f"/api/v1/companies/{company_id}",
            json={"version": expected_version, "pipeline_status": target},
        )
        assert response.status_code == 200, response.text

    source_response = await crm_client.post(
        f"/api/v1/companies/{company_id}/sources",
        json={
            "url": f"https://public-{suffix}.example/company-news",
            "source_type": "company_news",
            "trust_level": "official_public",
            "freshness_status": "current",
        },
    )
    assert source_response.status_code == 201, source_response.text
    source = source_response.json()

    session: AsyncSession = crm_client._test_session  # type: ignore[attr-defined]
    session.add_all(
        [
            CompanyFact(
                company_id=UUID(company_id),
                source_id=UUID(source["id"]),
                fact_type="company_description",
                value="The company is preparing a synthetic market entry.",
                confidence=0.95,
                exact_fragment="Synthetic market entry announcement",
                status="verified",
            ),
            CompanyTaskHypothesis(
                company_id=UUID(company_id),
                source_ids=[source["id"]],
                title="Synthetic launch coordination",
                description="Coordinate the documented synthetic market launch.",
                rationale="The official source records a market-entry program.",
                confidence=0.8,
                status="hypothesis",
                risks=["Public information may be incomplete"],
            ),
        ]
    )
    await session.flush()

    signal_response = await crm_client.post(
        f"/api/v1/companies/{company_id}/signals",
        json={
            "signal_type": "market_entry",
            "title": "Synthetic market entry",
            "description": "The fixture company announced a synthetic market entry.",
            "source_id": source["id"],
            "detected_at": "2026-08-01T10:00:00Z",
            "confidence": 0.9,
            "exact_fragment": "Synthetic market entry announcement",
            "status": "verified",
        },
    )
    assert signal_response.status_code == 201, signal_response.text
    signal = signal_response.json()

    opportunity_response = await crm_client.post(
        f"/api/v1/companies/{company_id}/opportunities",
        json={
            "opportunity_type": "market_entry",
            "rationale": "Candidate launch experience matches the synthetic expansion task.",
            "confidence": 0.85,
            "source_ids": [source["id"]],
            "signal_ids": [signal["id"]],
            "status": "verified",
        },
    )
    assert opportunity_response.status_code == 201, opportunity_response.text
    opportunity = opportunity_response.json()

    profile = (await crm_client.get("/api/v1/candidate-profile")).json()
    scores = {
        "business_fit_score": 82,
        "ai_automation_fit_score": 55,
        "hybrid_fit_score": 76,
        "format_fit_score": 80,
        "geography_fit_score": 75,
        "timing_signal_score": 90,
        "contactability_score": 60,
        "overall_opportunity_score": 79,
    }
    assessment_response = await crm_client.post(
        f"/api/v1/companies/{company_id}/assessments",
        json={
            "candidate_profile_version": profile["version"],
            **scores,
            "score_breakdown": {
                "formula_version": "integration-v1",
                "weights": {"business": 0.4, "timing": 0.2},
                "contributions": {},
                "warnings": [],
            },
            "opportunity_ids": [opportunity["id"]],
            "opportunity_signal_ids": [signal["id"]],
            "source_ids": [source["id"]],
            "possible_business_tasks": ["Synthetic market launch"],
            "candidate_value_hypotheses": ["Coordinate launch workstreams"],
            "recommended_collaboration_formats": ["project_based"],
            "recommended_workplace_formats": ["relocation"],
            "possible_roles": ["Launch Lead"],
            "reasons_to_contact": ["Verified market entry"],
            "reasons_not_to_contact": [],
            "risks": ["Public information may be incomplete"],
            "next_action": "Select positioning",
            "model_or_rule_version": "integration-v1",
        },
    )
    assert assessment_response.status_code == 201, assessment_response.text
    assessment = assessment_response.json()
    assert assessment["overall_opportunity_score"] == 79

    company = (await crm_client.get(f"/api/v1/companies/{company_id}")).json()
    transition = await crm_client.patch(
        f"/api/v1/companies/{company_id}",
        json={"version": company["version"], "pipeline_status": "opportunity_identified"},
    )
    assert transition.status_code == 200, transition.text

    recommendation_response = await crm_client.post(
        f"/api/v1/companies/{company_id}/recommendations",
        json={
            "assessment_id": assessment["id"],
            "primary_strategy": "business_first",
            "primary_message_line": "Lead with verified launch and operations experience.",
            "secondary_advantage": "Use AI automation as an efficiency amplifier.",
            "rationale": "The verified signal is primarily operational.",
            "value_proposition": "Coordinate a controlled synthetic market launch.",
            "concrete_first_message_offer": "Discuss a 30-day launch diagnostic.",
            "primary_decision_maker_role": "country_manager",
            "secondary_decision_maker_role": "head_of_operations",
            "collaboration_format": "project_based",
            "workplace_formats": ["relocation"],
            "possible_role": "Market Launch Lead",
        },
    )
    assert recommendation_response.status_code == 201, recommendation_response.text
    recommendation = recommendation_response.json()

    for target in ("strategy_selected", "contact_missing", "decision_pending"):
        company = (await crm_client.get(f"/api/v1/companies/{company_id}")).json()
        transition = await crm_client.patch(
            f"/api/v1/companies/{company_id}",
            json={"version": company["version"], "pipeline_status": target},
        )
        assert transition.status_code == 200, transition.text

    company = (await crm_client.get(f"/api/v1/companies/{company_id}")).json()
    bypass = await crm_client.patch(
        f"/api/v1/companies/{company_id}",
        json={"version": company["version"], "pipeline_status": "approved_for_outreach"},
    )
    assert bypass.status_code == 409
    assert bypass.json()["detail"]["code"] == "invalid_pipeline_transition"

    unconfirmed = await crm_client.post(
        f"/api/v1/companies/{company_id}/recommendations/{recommendation['id']}/decision",
        json={"version": recommendation["version"], "decision": "outreach"},
    )
    assert unconfirmed.status_code == 422

    blocked_without_contact = await crm_client.post(
        f"/api/v1/companies/{company_id}/recommendations/{recommendation['id']}/decision",
        json={
            "version": recommendation["version"],
            "decision": "outreach",
            "confirmed": True,
            "comment": "Must be blocked until a public contact path exists",
        },
    )
    assert blocked_without_contact.status_code == 409
    assert blocked_without_contact.json()["detail"]["code"] == "opportunity_not_actionable"

    readiness = await crm_client.get(f"/api/v1/companies/{company_id}/readiness")
    assert readiness.status_code == 200, readiness.text
    assert readiness.json()["contact_status"] == "CONTACT_RESEARCH_REQUIRED"
    assert readiness.json()["recommended_action"] == "CONTACT_RESEARCH_REQUIRED"
    blocked_card = await crm_client.get(f"/companies/{company_id}")
    assert blocked_card.status_code == 200, blocked_card.text
    assert "Сообщение пока недоступно" in blocked_card.text
    assert "нет проверенного публичного контакта" in blocked_card.text
    assert "Искать контакты глубже" in blocked_card.text

    contact = await crm_client.post(
        "/api/v1/contacts",
        json={
            "company_id": company_id,
            "name": "Synthetic Partnerships Team",
            "role": "Official partnership contact",
            "other_public_link": f"https://opportunity-{suffix}.example/contact-sales",
            "verification_status": "verified_public",
            "confidence": 0.95,
            "lawful_public_source_note": "Official public Contact Sales page",
            "decision_maker_role": "head_of_business_development",
            "decision_priority": 1,
            "source_id": source["id"],
        },
    )
    assert contact.status_code == 201, contact.text

    async def contact_resolver(
        _: str,
    ) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        return [ipaddress.ip_address("93.184.216.34")]

    contact_fetcher = SafeFetcher(
        resolver=contact_resolver,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text="<title>Opportunity Company</title><h1>Synthetic Partnerships Team</h1>",
            )
        ),
        respect_robots=False,
        minimum_host_interval=0,
    )
    app.dependency_overrides[get_contact_validator] = lambda: contact_fetcher
    validated_contact = await crm_client.post(f"/api/v1/contacts/{contact.json()['id']}/validate")
    app.dependency_overrides.pop(get_contact_validator, None)
    assert validated_contact.status_code == 200, validated_contact.text
    assert validated_contact.json()["validation_status"] == "VERIFIED_CONTACT"

    actionable = await crm_client.get(f"/api/v1/companies/{company_id}/readiness")
    assert actionable.status_code == 200, actionable.text
    assert actionable.json()["actionable"] is True
    assert actionable.json()["contact_status"] == "CONTACT_FOUND"

    localized_card = await crm_client.get(f"/companies/{company_id}")
    assert localized_card.status_code == 200, localized_card.text
    assert "Подготовка и решение" in localized_card.text
    assert "Контакты" in localized_card.text
    assert "Актуальные сигналы" in localized_card.text
    assert "Что происходит сейчас" not in localized_card.text
    assert "Подготовить все варианты" in localized_card.text
    assert "VERIFIED_CONTACT" not in localized_card.text

    prepare_letter = await crm_client.post(
        f"/companies/{company_id}/prepare-letter",
        data={
            "recommendation_id": recommendation["id"],
            "contact_id": contact.json()["id"],
            "version": recommendation["version"],
        },
        follow_redirects=False,
    )
    assert prepare_letter.status_code == 303, prepare_letter.text
    assert prepare_letter.headers["location"].startswith(f"/companies/{company_id}")
    assert "#letter" in prepare_letter.headers["location"]
    generated_drafts = await crm_client.get(f"/api/v1/companies/{company_id}/generation/drafts")
    assert generated_drafts.status_code == 200, generated_drafts.text
    assert {(item["message_format"], item["tone"]) for item in generated_drafts.json()} == {
        ("expanded", "professional"),
        ("expanded", "friendly"),
        ("short", "professional"),
        ("short", "friendly"),
    }
    workspace_page = await crm_client.get(f"/companies/{company_id}")
    assert workspace_page.status_code == 200
    assert "Развёрнутое письмо" in workspace_page.text
    assert "Короткое сообщение" in workspace_page.text
    assert "Профессиональный" in workspace_page.text
    assert "Дружелюбный" in workspace_page.text
    assert "Скопировать сообщение" in workspace_page.text
    assert "Изменить с помощью ИИ" in workspace_page.text
    assert "История версий" in workspace_page.text
    assert "/review/" in workspace_page.text
    assert 'name="workspace" value="true"' in workspace_page.text

    professional = next(
        item
        for item in generated_drafts.json()
        if item["message_format"] == "expanded" and item["tone"] == "professional"
    )
    workspace_edit = await crm_client.post(
        f"/review/{professional['id']}/edit",
        data={
            "workspace": "true",
            "revision": professional["revision"],
            "subject": professional["subject"],
            "body": f"{professional['body']}\n\nWorkspace clarification.",
            "comment": "Company workspace edit",
        },
        follow_redirects=False,
    )
    assert workspace_edit.status_code == 303
    assert workspace_edit.headers["location"].startswith(f"/companies/{company_id}")
    latest_professional = await session.scalar(
        select(MessageDraft)
        .where(
            MessageDraft.company_id == UUID(company_id),
            MessageDraft.variant == professional["variant"],
        )
        .order_by(MessageDraft.revision.desc())
    )
    assert latest_professional is not None
    app.dependency_overrides[get_ai_rewrite_provider] = lambda: FakeAIRewriteProvider()
    try:
        workspace_rewrite = await crm_client.post(
            f"/review/{latest_professional.id}/regenerate",
            data={
                "workspace": "true",
                "revision": latest_professional.revision,
                "campaign_goal": "Make it shorter",
                "language": "same",
            },
            follow_redirects=False,
        )
    finally:
        app.dependency_overrides.pop(get_ai_rewrite_provider, None)
    assert workspace_rewrite.status_code == 303
    assert workspace_rewrite.headers["location"].startswith(f"/companies/{company_id}")
    rewritten_professional = await session.scalar(
        select(MessageDraft)
        .where(
            MessageDraft.company_id == UUID(company_id),
            MessageDraft.variant == professional["variant"],
        )
        .order_by(MessageDraft.revision.desc())
    )
    assert rewritten_professional is not None
    workspace_approve = await crm_client.post(
        f"/review/{rewritten_professional.id}/approve",
        data={"workspace": "true", "revision": rewritten_professional.revision},
        follow_redirects=False,
    )
    assert workspace_approve.status_code == 303
    assert workspace_approve.headers["location"].startswith(f"/companies/{company_id}")
    assert not list(
        await session.scalars(
            select(OutboundMessage).where(OutboundMessage.company_id == UUID(company_id))
        )
    )

    company = (await crm_client.get(f"/api/v1/companies/{company_id}")).json()
    assert company["pipeline_status"] == "approved"
    assert company["recommended_positioning"] == "business_first"
    assert company["overall_opportunity_score"] == 79

    timeline = (
        await crm_client.get("/api/v1/communications", params={"company_id": company_id})
    ).json()
    assert {item["event_type"] for item in timeline} >= {
        "opportunity_signal_added",
        "opportunity_added",
        "opportunity_assessed",
        "positioning_recommended",
        "opportunity_decision",
    }

    final_company = (await crm_client.get(f"/api/v1/companies/{company_id}")).json()
    deleted = await crm_client.delete(
        f"/api/v1/companies/{company_id}", params={"version": final_company["version"]}
    )
    assert deleted.status_code == 204, deleted.text


@pytest.mark.asyncio
async def test_safe_research_persists_provenance_and_deduplicates(crm_client: AsyncClient) -> None:
    suffix = uuid4().hex[:12]
    company_response = await crm_client.post(
        "/api/v1/companies",
        json={
            "name": f"Research Company {suffix}",
            "normalized_domain": f"research-{suffix}.example",
            "is_synthetic": True,
            "country": "Synthetic Region",
        },
    )
    assert company_response.status_code == 201, company_response.text
    company = company_response.json()
    company_id = company["id"]

    async def public_resolver(_: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        return [ipaddress.ip_address("93.184.216.34")]

    html = """
    <html><body><h1>Synthetic Global Company</h1>
    <p>We announce a new market entry and a process automation program.</p>
    <a href="mailto:careers@synthetic.example">Careers</a></body></html>
    """
    fetcher = SafeFetcher(
        resolver=public_resolver,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, headers={"content-type": "text/html"}, text=html)
        ),
        respect_robots=False,
        minimum_host_interval=0,
    )
    app.dependency_overrides[get_safe_fetcher] = lambda: fetcher
    try:
        for _ in range(2):
            response = await crm_client.post(
                f"/api/v1/companies/{company_id}/research",
                json={"url": f"https://research-{suffix}.example/about"},
            )
            assert response.status_code == 201, response.text
            result = response.json()
            assert result["run"]["status"] == "completed"
            assert result["facts"]
            assert result["hypotheses"]
            assert result["signal_ids"]

        sources = await crm_client.get(f"/api/v1/companies/{company_id}/sources")
        facts = await crm_client.get(f"/api/v1/companies/{company_id}/research/facts")
        hypotheses = await crm_client.get(f"/api/v1/companies/{company_id}/research/hypotheses")
        runs = await crm_client.get(f"/api/v1/companies/{company_id}/research/runs")
        contacts = await crm_client.get("/api/v1/contacts", params={"company_id": company_id})
        assert len(sources.json()) == 1
        assert len(facts.json()) == 1
        assert len(hypotheses.json()) >= 1
        assert len(runs.json()) == 2
        assert len(contacts.json()) == 1
        assert contacts.json()[0]["verification_status"] == "unverified"
        assert contacts.json()[0]["decision_maker_role"] == "talent_acquisition"

        fact = facts.json()[0]
        verified = await crm_client.patch(
            f"/api/v1/companies/{company_id}/research/facts/{fact['id']}",
            json={"version": fact["version"], "status": "verified"},
        )
        assert verified.status_code == 200, verified.text
        assert verified.json()["status"] == "verified"

        custom_weights = {
            "core_fit": 0.35,
            "format_fit_score": 0.20,
            "geography_fit_score": 0.10,
            "timing_signal_score": 0.10,
            "contactability_score": 0.10,
            "value_proposition_realism": 0.15,
        }
        scoring = await crm_client.post(
            f"/api/v1/companies/{company_id}/relevance/calculate",
            json={"weights": custom_weights},
        )
        assert scoring.status_code == 201, scoring.text
        assessment = scoring.json()
        assert assessment["model_or_rule_version"] == "opportunity-relevance-v1"
        assert assessment["score_breakdown"]["formula_version"] == "opportunity-relevance-v1"
        assert assessment["score_breakdown"]["weights"] == custom_weights
        assert "overall_opportunity_score" in assessment["score_breakdown"]["contributions"]

        override = await crm_client.post(
            f"/api/v1/companies/{company_id}/relevance/assessments/{assessment['id']}/override",
            json={
                "overridden_score": 80,
                "reason": "Synthetic owner evidence requires a documented manual review override",
            },
        )
        assert override.status_code == 201, override.text
        assert override.json()["original_score"] == assessment["overall_opportunity_score"]
        assert override.json()["overridden_score"] == 80
        overrides = await crm_client.get(f"/api/v1/companies/{company_id}/relevance/overrides")
        assert len(overrides.json()) == 1

        company = (await crm_client.get(f"/api/v1/companies/{company_id}")).json()
        assert company["pipeline_status"] == "opportunity_identified"
        assert company["overall_opportunity_score"] == 80
        assert "en" in company["language_signals"]
        assert "market_entry" in company["opportunity_types"]
        page = await crm_client.get(f"/companies/{company_id}")
        assert page.status_code == 200
        assert "О компании" in page.text
        assert "Подтверждённые факты" in page.text
        assert "Техническая оценка — вторично" not in page.text

        opportunity_items = (
            await crm_client.get(f"/api/v1/companies/{company_id}/opportunities")
        ).json()
        opportunity = opportunity_items[0]
        opportunity_verified = await crm_client.patch(
            f"/api/v1/companies/{company_id}/opportunities/{opportunity['id']}",
            json={
                "version": opportunity["version"],
                "status": "verified",
                "source_ids": [sources.json()[0]["id"]],
            },
        )
        assert opportunity_verified.status_code == 200, opportunity_verified.text
        contact = contacts.json()[0]
        contact_verified = await crm_client.patch(
            f"/api/v1/contacts/{contact['id']}",
            json={
                "version": contact["version"],
                "email": "delivery@synthetic-company.com",
                "verification_status": "verified",
                "lawful_public_source_note": "Synthetic public mailto in integration fixture",
            },
        )
        assert contact_verified.status_code == 200, contact_verified.text
        app.dependency_overrides[get_contact_validator] = lambda: fetcher
        contact_validation = await crm_client.post(f"/api/v1/contacts/{contact['id']}/validate")
        app.dependency_overrides.pop(get_contact_validator, None)
        assert contact_validation.status_code == 200, contact_validation.text
        assert contact_validation.json()["validation_status"] == "VERIFIED_CONTACT"
        candidate_fact = await crm_client.post(
            "/api/v1/candidate-facts",
            json={
                "fact_type": "experience",
                "text": "Verified operational delivery and practical workflow automation",
                "evidence": "Synthetic integration evidence",
                "verified": True,
                "store_private": True,
                "use_for_ai_analysis": True,
                "use_in_draft": True,
            },
        )
        assert candidate_fact.status_code == 201, candidate_fact.text
        campaign_response = await crm_client.post(
            "/api/v1/campaigns",
            json={
                "name": "Synthetic Stage 7 Delivery",
                "goal": "Verify guarded delivery without external network access",
                "daily_limit": 2,
                "followup_policy": {
                    "enabled": True,
                    "interval_business_days": 0,
                    "max_followups": 1,
                },
                "status": "active",
            },
        )
        assert campaign_response.status_code == 201, campaign_response.text
        delivery_campaign = campaign_response.json()
        recommendation_response = await crm_client.post(
            f"/api/v1/companies/{company_id}/recommendations",
            json={
                "assessment_id": assessment["id"],
                "primary_strategy": "business_first",
                "primary_message_line": "Operational delivery first",
                "secondary_advantage": "Practical workflow automation",
                "rationale": "The verified profile and company fact support a cautious approach",
                "value_proposition": "Explore one measurable workflow improvement",
                "concrete_first_message_offer": "map one workflow and define a small pilot",
                "primary_decision_maker_role": "coo",
                "secondary_decision_maker_role": "head_of_operations",
                "collaboration_format": "project_based",
                "workplace_formats": ["remote"],
                "possible_role": "Operations improvement partner",
            },
        )
        assert recommendation_response.status_code == 201, recommendation_response.text
        recommendation = recommendation_response.json()
        generation_payload = {
            "contact_id": contact["id"],
            "recommendation_id": recommendation["id"],
            "campaign_goal": "Explore a measurable operational improvement pilot",
            "language": "en",
        }
        closed_gate = await crm_client.post(
            f"/api/v1/companies/{company_id}/generation/generate",
            json=generation_payload,
        )
        assert closed_gate.status_code == 409, closed_gate.text
        assert closed_gate.json()["detail"]["code"] == "outreach_decision_required"

        for target in ("strategy_selected", "contact_found", "decision_pending"):
            current_company = (await crm_client.get(f"/api/v1/companies/{company_id}")).json()
            transition = await crm_client.patch(
                f"/api/v1/companies/{company_id}",
                json={"version": current_company["version"], "pipeline_status": target},
            )
            assert transition.status_code == 200, transition.text
        decision = await crm_client.post(
            f"/api/v1/companies/{company_id}/recommendations/{recommendation['id']}/decision",
            json={
                "version": recommendation["version"],
                "decision": "outreach",
                "confirmed": True,
                "comment": "Synthetic explicit owner decision for draft generation",
            },
        )
        assert decision.status_code == 201, decision.text
        generation = await crm_client.post(
            f"/api/v1/companies/{company_id}/generation/generate",
            json=generation_payload,
        )
        assert generation.status_code == 201, generation.text
        generation_run = generation.json()
        assert generation_run["status"] == "ready"
        assert generation_run["provider"] == "deterministic-local"
        assert generation_run["estimated_cost_usd"] == 0
        assert [item["variant"] for item in generation_run["drafts"]] == ["A", "B", "C", "D"]
        assert all(item["status"] == "ready" for item in generation_run["drafts"])
        assert all(item["validation_report"]["passed"] for item in generation_run["drafts"])
        assert all(item["candidate_fact_ids"] for item in generation_run["drafts"])
        assert all(item["company_fact_ids"] for item in generation_run["drafts"])
        stored_runs = await crm_client.get(f"/api/v1/companies/{company_id}/generation/runs")
        stored_drafts = await crm_client.get(f"/api/v1/companies/{company_id}/generation/drafts")
        assert len(stored_runs.json()) == 1
        assert len(stored_drafts.json()) == 4
        generated_company = (await crm_client.get(f"/api/v1/companies/{company_id}")).json()
        assert generated_company["pipeline_status"] == "draft_ready"
        generated_page = await crm_client.get("/letters?tab=drafts")
        assert generated_page.status_code == 200
        assert "Компания / получатель" in generated_page.text
        assert "Тема" in generated_page.text
        assert "Открыть компанию" in generated_page.text
        assert generated_company["name"] in generated_page.text
        assert "Готово к проверке" in generated_page.text

        draft_a = generation_run["drafts"][0]
        alternate_contact_response = await crm_client.post(
            "/api/v1/contacts",
            json={
                "company_id": company_id,
                "name": "Morgan Synthetic",
                "role": "Head of Operations",
                "email": "morgan@synthetic-company.com",
                "verification_status": "verified",
                "lawful_public_source_note": "Synthetic public fixture",
            },
        )
        assert alternate_contact_response.status_code == 201, alternate_contact_response.text
        alternate_contact = alternate_contact_response.json()
        recipient_change = await crm_client.post(
            f"/api/v1/drafts/{generation_run['drafts'][1]['id']}/recipient",
            json={
                "revision": generation_run["drafts"][1]["revision"],
                "contact_id": alternate_contact["id"],
                "confirmed": True,
                "comment": "Explicit synthetic recipient change",
            },
        )
        assert recipient_change.status_code == 201, recipient_change.text
        assert recipient_change.json()["contact_id"] == alternate_contact["id"]
        assert recipient_change.json()["revision"] == 2
        approval_one = await crm_client.post(
            f"/api/v1/drafts/{draft_a['id']}/approve",
            json={
                "revision": draft_a["revision"],
                "confirmed": True,
                "comment": "Explicit synthetic approval of the exact first revision",
            },
        )
        assert approval_one.status_code == 201, approval_one.text
        assert approval_one.json()["valid"] is True
        assert approval_one.json()["approval_token"]
        duplicate_approval = await crm_client.post(
            f"/api/v1/drafts/{draft_a['id']}/approve",
            json={"revision": 1, "confirmed": True},
        )
        assert duplicate_approval.status_code == 409
        edited_body = (
            draft_a["body"]
            + " This owner edit clarifies that the proposed conversation is exploratory."
        )
        edit = await crm_client.post(
            f"/api/v1/drafts/{draft_a['id']}/edit",
            json={
                "revision": 1,
                "subject": draft_a["subject"],
                "body": edited_body,
                "comment": "Synthetic owner clarification",
            },
        )
        assert edit.status_code == 201, edit.text
        draft_a_revision_two = edit.json()
        assert draft_a_revision_two["revision"] == 2
        assert draft_a_revision_two["content_hash"] != draft_a["content_hash"]
        stale_edit = await crm_client.post(
            f"/api/v1/drafts/{draft_a['id']}/edit",
            json={
                "revision": 1,
                "subject": draft_a["subject"],
                "body": edited_body,
            },
        )
        assert stale_edit.status_code == 409
        review_detail = await crm_client.get(f"/api/v1/drafts/{draft_a_revision_two['id']}")
        assert review_detail.status_code == 200, review_detail.text
        detail_payload = review_detail.json()
        assert [item["revision"] for item in detail_payload["revisions"]] == [2, 1]
        assert detail_payload["approvals"][0]["valid"] is False
        assert detail_payload["approvals"][0]["validity_reason"] == "draft_revision_changed"
        approval_two = await crm_client.post(
            f"/api/v1/drafts/{draft_a_revision_two['id']}/approve",
            json={
                "revision": 2,
                "confirmed": True,
                "comment": "Explicit synthetic approval of revision two",
            },
        )
        assert approval_two.status_code == 201, approval_two.text
        approval_two_payload = approval_two.json()
        fake_email_adapter = FakeEmailAdapter()
        app.dependency_overrides[get_email_adapter] = lambda: fake_email_adapter
        app.dependency_overrides[get_test_email_adapter] = lambda: fake_email_adapter
        test_send_payload = {
            "approval_id": approval_two_payload["id"],
            "approval_token": approval_two_payload["approval_token"],
            "campaign_id": delivery_campaign["id"],
        }
        test_send = await crm_client.post(
            f"/api/v1/drafts/{draft_a_revision_two['id']}/send-test",
            json=test_send_payload,
            headers={"Idempotency-Key": "stage7-test-send-key-0001"},
        )
        assert test_send.status_code == 201, test_send.text
        assert test_send.json()["delivery_mode"] == "test"
        assert test_send.json()["delivery_status"] == "sent"
        assert fake_email_adapter.calls[0]["recipient"] == "mailpit@example.test"
        assert "recipient_hash" not in test_send.json()
        after_mailpit_test = (await crm_client.get(f"/api/v1/companies/{company_id}")).json()
        assert after_mailpit_test["next_action"] == "Mailpit test sent; real email not sent"
        assert after_mailpit_test["pipeline_status"] == "approved"
        assert (await crm_client.get("/api/v1/followups")).json() == []
        idempotent_test_send = await crm_client.post(
            f"/api/v1/drafts/{draft_a_revision_two['id']}/send-test",
            json=test_send_payload,
            headers={"Idempotency-Key": "stage7-test-send-key-0001"},
        )
        assert idempotent_test_send.status_code == 201, idempotent_test_send.text
        assert idempotent_test_send.json()["id"] == test_send.json()["id"]
        assert len(fake_email_adapter.calls) == 1
        blocked_real_send = await crm_client.post(
            f"/api/v1/drafts/{draft_a_revision_two['id']}/send",
            json=test_send_payload,
            headers={"Idempotency-Key": "stage7-real-blocked-key-0001"},
        )
        assert blocked_real_send.status_code == 403
        assert blocked_real_send.json()["detail"]["code"] == "real_email_disabled"
        assert len(fake_email_adapter.calls) == 1

        external_fact = await crm_client.patch(
            f"/api/v1/candidate-facts/{candidate_fact.json()['id']}",
            json={
                "version": candidate_fact.json()["version"],
                "send_externally": True,
            },
        )
        assert external_fact.status_code == 200, external_fact.text
        used_fact_ids = set(generation_run["drafts"][1]["candidate_fact_ids"])
        candidate_facts = (await crm_client.get("/api/v1/candidate-facts")).json()
        for used_fact in candidate_facts:
            if used_fact["id"] in used_fact_ids and used_fact["id"] != external_fact.json()["id"]:
                fact_permission_update = await crm_client.patch(
                    f"/api/v1/candidate-facts/{used_fact['id']}",
                    json={
                        "version": used_fact["version"],
                        "send_externally": True,
                    },
                )
                assert fact_permission_update.status_code == 200, fact_permission_update.text
        candidate_contacts = (await crm_client.get("/api/v1/candidate-contacts")).json()
        for candidate_contact in candidate_contacts:
            if (
                candidate_contact["allowed_in_signature"]
                and candidate_contact["value"] in generation_run["drafts"][1]["body"]
            ):
                permission_update = await crm_client.patch(
                    f"/api/v1/candidate-contacts/{candidate_contact['id']}",
                    json={
                        "version": candidate_contact["version"],
                        "use_in_draft": True,
                        "send_externally": True,
                    },
                )
                assert permission_update.status_code == 200, permission_update.text

        draft_b = recipient_change.json()
        approval_b = await crm_client.post(
            f"/api/v1/drafts/{draft_b['id']}/approve",
            json={
                "revision": draft_b["revision"],
                "confirmed": True,
                "comment": "Explicit approval for guarded synthetic real delivery",
            },
        )
        assert approval_b.status_code == 201, approval_b.text
        approval_b_payload = approval_b.json()
        real_settings = Settings(
            _env_file=None,
            demo_mode=False,
            allow_real_email=True,
            delivery_owner_token=SecretStr("synthetic-owner-token"),
        )
        app.dependency_overrides[get_settings] = lambda: real_settings
        owner_blocked_send = await crm_client.post(
            f"/api/v1/drafts/{draft_b['id']}/send",
            json={
                "approval_id": approval_b_payload["id"],
                "approval_token": approval_b_payload["approval_token"],
                "campaign_id": delivery_campaign["id"],
            },
            headers={
                "Idempotency-Key": "stage7-owner-gate-blocked-0001",
                "Authorization": "Bearer synthetic-owner-token",
            },
        )
        assert owner_blocked_send.status_code == 403
        assert owner_blocked_send.json()["detail"]["code"] == "owner_real_send_disabled"
        crm_client._test_session.add(  # type: ignore[attr-defined]
            OwnerSafetyPolicy(owner_key="primary", real_send_enabled=True)
        )
        await crm_client._test_session.flush()  # type: ignore[attr-defined]
        real_send = await crm_client.post(
            f"/api/v1/drafts/{draft_b['id']}/send",
            json={
                "approval_id": approval_b_payload["id"],
                "approval_token": approval_b_payload["approval_token"],
                "campaign_id": delivery_campaign["id"],
            },
            headers={
                "Idempotency-Key": "stage7-real-send-key-0001",
                "Authorization": "Bearer synthetic-owner-token",
            },
        )
        assert real_send.status_code == 201, real_send.text
        assert real_send.json()["delivery_mode"] == "real"
        assert real_send.json()["delivery_status"] == "sent"
        assert fake_email_adapter.calls[-1]["recipient"] == "morgan@synthetic-company.com"
        consumed_detail = await crm_client.get(f"/api/v1/drafts/{draft_b['id']}")
        assert consumed_detail.json()["approvals"][0]["validity_reason"] == "already_consumed"
        listed_messages = await crm_client.get("/api/v1/messages")
        assert listed_messages.status_code == 200
        company_messages = [
            item for item in listed_messages.json() if item["company_id"] == company_id
        ]
        assert len(company_messages) == 2

        planned_followups = await crm_client.get("/api/v1/followups")
        assert planned_followups.status_code == 200
        assert len(planned_followups.json()) == 1
        planned_followup = planned_followups.json()[0]
        assert planned_followup["status"] == "planned"
        assert planned_followup["timezone"] == "Europe/Moscow"
        assert planned_followup["subject"] is None
        refresh_followups = await crm_client.post(
            "/api/v1/followups/refresh-due", json={"limit": 10}
        )
        assert refresh_followups.status_code == 200, refresh_followups.text
        proposal = refresh_followups.json()[0]
        assert proposal["status"] == "draft_ready"
        assert proposal["validation_report"]["passed"] is True
        assert proposal["validation_report"]["automatic_send_allowed"] is False
        assert len(proposal["body"]) < len(draft_b["body"])
        approve_followup_response = await crm_client.post(
            f"/api/v1/followups/{proposal['id']}/approve",
            json={
                "version": proposal["version"],
                "confirmed": True,
                "comment": "Explicit synthetic follow-up approval",
            },
        )
        assert approve_followup_response.status_code == 200, approve_followup_response.text
        approved_followup = approve_followup_response.json()
        assert approved_followup["status"] == "approved"
        manual_reply = await crm_client.post(
            "/api/v1/communications/replies",
            json={
                "company_id": company_id,
                "contact_id": contact["id"],
                "outcome": "project_discussion",
                "summary": "Synthetic reply opened a project discussion",
            },
        )
        assert manual_reply.status_code == 201, manual_reply.text
        assert manual_reply.json()["outcome"] == "project_discussion"
        assert manual_reply.json()["cancelled_followups"] == 1
        cancelled_followup = (
            await crm_client.get("/api/v1/followups", params={"company_id": company_id})
        ).json()[0]
        assert cancelled_followup["status"] == "cancelled"
        assert cancelled_followup["cancellation_reason"] == ("manual_reply_project_discussion")
        outcome_company = (await crm_client.get(f"/api/v1/companies/{company_id}")).json()
        assert outcome_company["pipeline_status"] == "project_discussion"
        mature_hybrid = await crm_client.post(
            "/api/v1/companies",
            json={
                "name": "Synthetic Mature Hybrid Portfolio Company",
                "normalized_domain": f"mature-hybrid-{suffix}.example",
                "is_synthetic": True,
                "country": "Germany",
                "company_size": "1000+",
                "maturity_stage": "mature",
                "opportunity_types": ["general_competence_fit", "process_automation"],
                "recommended_positioning": "hybrid",
                "recommended_collaboration_formats": ["project_based", "consulting"],
                "recommended_workplace_formats": ["remote"],
                "business_fit_score": 91,
                "ai_automation_fit_score": 86,
                "hybrid_fit_score": 94,
                "overall_opportunity_score": 92,
                "relevance_score": 92,
                "relevance_status": "opportunity_identified",
                "next_action": "Synthetic portfolio review",
            },
        )
        assert mature_hybrid.status_code == 201, mature_hybrid.text
        analytics = await crm_client.get("/api/v1/analytics")
        assert analytics.status_code == 200, analytics.text
        analytics_payload = analytics.json()
        assert all(
            item["name"] != "Synthetic Mature Hybrid Portfolio Company"
            for item in analytics_payload["portfolio"]
        )
        filtered_analytics = await crm_client.get(
            "/api/v1/analytics",
            params={
                "q": f"mature-hybrid-{suffix}.example",
                "vacancy": "without",
                "positioning_strategy": "hybrid",
            },
        )
        assert filtered_analytics.status_code == 200, filtered_analytics.text
        filtered_payload = filtered_analytics.json()
        assert filtered_payload["portfolio"] == []
        assert filtered_payload["applied_filters"] == {
            "q": f"mature-hybrid-{suffix}.example",
            "positioning_strategy": "hybrid",
            "vacancy": "without",
        }
        analytics_page = await crm_client.get("/analytics", params={"vacancy": "without"})
        assert analytics_page.status_code == 200
        assert "Analytics & Portfolio" in analytics_page.text
        assert "Synthetic Mature Hybrid Portfolio Company" not in analytics_page.text
        assert "Opportunity funnel" in analytics_page.text
        followup_page = await crm_client.get("/followups")
        assert followup_page.status_code == 200
        assert "never" not in followup_page.text.casefold()
        assert "никогда не отправляются автоматически" in followup_page.text

        refreshed_contact = (await crm_client.get(f"/api/v1/contacts/{contact['id']}")).json()
        contact_change = await crm_client.patch(
            f"/api/v1/contacts/{contact['id']}",
            json={
                "version": refreshed_contact["version"],
                "role": "Updated synthetic role",
            },
        )
        assert contact_change.status_code == 200, contact_change.text
        changed_contact_detail = await crm_client.get(
            f"/api/v1/drafts/{draft_a_revision_two['id']}"
        )
        current_approval = changed_contact_detail.json()["approvals"][0]
        assert current_approval["valid"] is False
        assert current_approval["validity_reason"] == "alternative_variant_selected"
        revoke_fact = await crm_client.patch(
            f"/api/v1/candidate-facts/{candidate_fact.json()['id']}",
            json={
                "version": external_fact.json()["version"],
                "use_in_draft": False,
                "send_externally": False,
            },
        )
        assert revoke_fact.status_code == 200, revoke_fact.text
        revoked_detail = await crm_client.get(f"/api/v1/drafts/{draft_a_revision_two['id']}")
        revoked_approval = revoked_detail.json()["approvals"][0]
        assert revoked_approval["valid"] is False
        assert revoked_approval["validity_reason"] == "alternative_variant_selected"
        review_page = await crm_client.get(f"/review/{draft_a_revision_two['id']}")
        assert review_page.status_code == 200
        assert "История версий" in review_page.text
        assert "Технические детали" not in review_page.text
        assert "Проверить тестовую доставку" in review_page.text
        assert "Сравнить варианты" in review_page.text

        async def private_resolver(
            _: str,
        ) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
            return [ipaddress.ip_address("127.0.0.1")]

        app.dependency_overrides[get_safe_fetcher] = lambda: SafeFetcher(
            resolver=private_resolver,
            respect_robots=False,
        )
        blocked = await crm_client.post(
            f"/api/v1/companies/{company_id}/research",
            json={"url": "https://blocked.example/private"},
        )
        assert blocked.status_code == 422
        assert blocked.json()["detail"]["code"] == "private_address"
        recorded_runs = (
            await crm_client.get(f"/api/v1/companies/{company_id}/research/runs")
        ).json()
        assert any(item["status"] == "blocked" for item in recorded_runs)
    finally:
        app.dependency_overrides.pop(get_safe_fetcher, None)
        app.dependency_overrides.pop(get_email_adapter, None)
        app.dependency_overrides.pop(get_test_email_adapter, None)
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_crm_crud_timeline_and_optimistic_locking(crm_client: AsyncClient) -> None:
    suffix = uuid4().hex[:12]
    company_response = await crm_client.post(
        "/api/v1/companies",
        json={
            "name": f"Integration Company {suffix}",
            "normalized_domain": f"integration-{suffix}.example",
            "country": "Synthetic Country",
            "industry": "Synthetic Industry",
        },
    )
    assert company_response.status_code == 201, company_response.text
    company = company_response.json()
    company_id = company["id"]
    assert company["version"] == 1

    stale = await crm_client.patch(
        f"/api/v1/companies/{company_id}",
        json={"version": 99, "pipeline_status": "researched"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "version_conflict"

    research_pending_response = await crm_client.patch(
        f"/api/v1/companies/{company_id}",
        json={
            "version": 1,
            "pipeline_status": "research_pending",
        },
    )
    assert research_pending_response.status_code == 200, research_pending_response.text

    updated_response = await crm_client.patch(
        f"/api/v1/companies/{company_id}",
        json={
            "version": 2,
            "pipeline_status": "researched",
            "next_action": "Synthetic integration review",
        },
    )
    assert updated_response.status_code == 200, updated_response.text
    updated = updated_response.json()
    assert updated["version"] == 3
    assert updated["pipeline_status"] == "researched"

    contact_response = await crm_client.post(
        "/api/v1/contacts",
        json={
            "company_id": company_id,
            "name": "Synthetic Decision Maker",
            "email": f"PERSON@integration-{suffix}.example",
            "verification_status": "verified",
            "lawful_public_source_note": "Synthetic integration fixture",
        },
    )
    assert contact_response.status_code == 201, contact_response.text
    contact = contact_response.json()
    assert contact["email"] == f"person@integration-{suffix}.example"

    job_response = await crm_client.post(
        "/api/v1/jobs",
        json={
            "company_id": company_id,
            "title": "Synthetic Integration Role",
            "url": f"https://integration-{suffix}.example/jobs/role",
            "required_skills": ["Python", "FastAPI"],
        },
    )
    assert job_response.status_code == 201, job_response.text
    job = job_response.json()

    campaign_response = await crm_client.post(
        "/api/v1/campaigns",
        json={
            "name": f"Integration Campaign {suffix}",
            "goal": "Exercise the synthetic CRM integration path",
        },
    )
    assert campaign_response.status_code == 201, campaign_response.text
    campaign = campaign_response.json()

    companies = await crm_client.get(
        "/api/v1/companies",
        params={"q": suffix, "pipeline_status": "researched", "sort": "name"},
    )
    assert companies.status_code == 200
    assert companies.json()["meta"]["total"] == 1

    timeline = await crm_client.get("/api/v1/communications", params={"company_id": company_id})
    assert timeline.status_code == 200
    assert {event["event_type"] for event in timeline.json()} >= {
        "company_created",
        "pipeline_changed",
        "contact_added",
        "job_added",
    }

    dashboard = await crm_client.get("/api/v1/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["companies"] >= 1
    assert dashboard.json()["verified_contacts"] >= 1
    assert dashboard.json()["active_jobs"] >= 1
    assert "opportunities_identified" in dashboard.json()
    assert "decision_pending" in dashboard.json()
    assert "opportunities_without_vacancy" in dashboard.json()

    assert (
        await crm_client.delete(
            f"/api/v1/contacts/{contact['id']}", params={"version": contact["version"]}
        )
    ).status_code == 204
    assert (
        await crm_client.delete(f"/api/v1/jobs/{job['id']}", params={"version": job["version"]})
    ).status_code == 204
    assert (
        await crm_client.delete(
            f"/api/v1/campaigns/{campaign['id']}", params={"version": campaign["version"]}
        )
    ).status_code == 204
    assert (
        await crm_client.delete(
            f"/api/v1/companies/{company_id}", params={"version": updated["version"]}
        )
    ).status_code == 204


@pytest.mark.asyncio
async def test_manual_search_tasks_preserve_query_and_track_results(
    crm_client: AsyncClient,
) -> None:
    original_query = "  Find 7 companies in Mexico in logistics for Business Development  "
    created_response = await crm_client.post(
        "/api/v1/search-tasks",
        json={
            "original_query": original_query,
            "task_type": "find_companies",
            "result_limit": 5,
        },
    )
    assert created_response.status_code == 201, created_response.text
    created = created_response.json()
    assert created["original_query"] == original_query
    assert created["query_language"] == "en"
    assert created["parsed_country"] == "Mexico"
    assert created["parsed_industry"] == "Logistics"
    assert created["parsed_focus"] == "Business Development"
    assert created["result_limit"] == 7
    assert created["status"] == "QUEUED"

    started_response = await crm_client.post(f"/api/v1/search-tasks/{created['id']}/start")
    assert started_response.status_code == 200, started_response.text
    assert started_response.json()["status"] == "RUNNING"

    cancelled_response = await crm_client.post(f"/api/v1/search-tasks/{created['id']}/cancel")
    assert cancelled_response.status_code == 200, cancelled_response.text
    assert cancelled_response.json()["status"] == "CANCELLED"
    repeated_cancel = await crm_client.post(f"/api/v1/search-tasks/{created['id']}/cancel")
    assert repeated_cancel.status_code == 200
    assert repeated_cancel.json()["status"] == "CANCELLED"

    natural_query = "Проанализируй компанию Airalo, сайт airalo.com"
    natural_response = await crm_client.post(
        "/search-tasks",
        data={"original_query": natural_query, "result_limit": "3"},
        follow_redirects=False,
    )
    assert natural_response.status_code == 303, natural_response.text
    natural_task = await crm_client._test_session.scalar(  # type: ignore[attr-defined]
        select(SearchTask).where(SearchTask.original_query == natural_query)
    )
    assert natural_task is not None
    assert natural_task.task_type == "analyze_company"
    assert natural_task.company_name_or_url == "https://airalo.com"


@pytest.mark.asyncio
async def test_direct_search_task_links_existing_real_company(
    crm_client: AsyncClient,
) -> None:
    suffix = uuid4().hex[:10]
    domain = f"direct-{suffix}.example"
    company_response = await crm_client.post(
        "/api/v1/companies",
        json={"name": f"Direct target {suffix}", "normalized_domain": domain},
    )
    assert company_response.status_code == 201, company_response.text
    company = company_response.json()

    task_response = await crm_client.post(
        "/api/v1/search-tasks",
        json={
            "original_query": f"Analyze {domain}",
            "task_type": "analyze_company",
            "company_name_or_url": f"https://{domain}",
            "result_limit": 1,
        },
    )
    assert task_response.status_code == 201, task_response.text
    task = task_response.json()

    started_response = await crm_client.post(
        f"/api/v1/search-tasks/{task['id']}/results",
        json={"company_id": company["id"], "accepted": True, "complete_task": True},
    )
    assert started_response.status_code == 200, started_response.text
    started = started_response.json()
    assert started["status"] == "COMPLETED"
    assert started["found_count"] == 1
    assert started["accepted_count"] == 1

    page = await crm_client.get("/companies")
    assert page.status_code == 200, page.text
    assert f"Analyze {domain}" not in page.text
    history = await crm_client.get("/search-history")
    assert history.status_code == 200, history.text
    assert f"Analyze {domain}" in history.text

    final_company = (await crm_client.get(f"/api/v1/companies/{company['id']}")).json()
    deleted = await crm_client.delete(
        f"/api/v1/companies/{company['id']}", params={"version": final_company["version"]}
    )
    assert deleted.status_code == 204, deleted.text


@pytest.mark.asyncio
async def test_search_task_executor_reuses_full_pipeline(crm_client: AsyncClient) -> None:
    suffix = uuid4().hex[:10]
    domain = f"executor-{suffix}.example"
    task_response = await crm_client.post(
        "/api/v1/search-tasks",
        json={
            "original_query": "Analyze a public expansion company",
            "task_type": "analyze_company",
            "company_name_or_url": domain,
            "result_limit": 1,
        },
    )
    assert task_response.status_code == 201, task_response.text
    task_id = UUID(task_response.json()["id"])
    session = crm_client._test_session  # type: ignore[attr-defined]
    task = await session.get(SearchTask, task_id)
    assert task is not None
    task.status = "RUNNING"
    task.current_stage = "resolving_company"
    task.attempt_count = 1
    await session.commit()

    class FakeResolver:
        async def resolve(self, _: SearchTask) -> list[ResolvedCompany]:
            return [
                ResolvedCompany(
                    name=f"Blocked Company {suffix}",
                    official_url=f"https://blocked-{domain}/",
                    normalized_domain=f"blocked-{domain}",
                    research_urls=(f"https://blocked-{domain}/",),
                ),
                ResolvedCompany(
                    name=f"Executor Company {suffix}",
                    official_url=f"https://{domain}/about",
                    normalized_domain=domain,
                    research_urls=(f"https://{domain}/about",),
                ),
            ]

    class FakeFetcher:
        async def fetch(self, url: str) -> FetchedDocument:
            if "blocked-" in url:
                raise SafeFetchError("robots_denied", "robots.txt denies this URL")
            body = (
                "<html><body><h1>Executor Company</h1>"
                "<p>International expansion and new product launch.</p>"
                f'<a href="mailto:careers@{domain}">Careers</a>'
                "</body></html>"
            ).encode()
            return FetchedDocument(
                requested_url=url,
                final_url=url,
                redirect_chain=[],
                status_code=200,
                content_type="text/html",
                body=body,
            )

    await execute_claimed_task(
        session,
        task,
        resolver=FakeResolver(),  # type: ignore[arg-type]
        fetcher=FakeFetcher(),  # type: ignore[arg-type]
        run_contact_discovery=False,
    )
    await session.refresh(task)
    assert task.status == "COMPLETED"
    assert task.current_stage == "completed"
    assert task.found_count == 2
    assert task.accepted_count == 1
    assert task.failure_reason is None

    blocked_company = await session.scalar(
        select(Company).where(Company.normalized_domain == f"blocked-{domain}")
    )
    assert blocked_company is not None
    assert blocked_company.pipeline_status == "not_relevant"

    result = await session.scalar(
        select(SearchTaskResult).where(
            SearchTaskResult.search_task_id == task.id,
            SearchTaskResult.accepted.is_(True),
        )
    )
    assert result is not None
    company_response = await crm_client.get(f"/api/v1/companies/{result.company_id}")
    assert company_response.status_code == 200, company_response.text
    company = company_response.json()
    assert company["normalized_domain"] == domain
    assert company["is_synthetic"] is False
    assert company["pipeline_status"] in {"decision_pending", "not_relevant"}

    assert (await crm_client.get(f"/api/v1/companies/{result.company_id}/research/runs")).json()
    assert (await crm_client.get(f"/api/v1/companies/{result.company_id}/opportunities")).json()
    assert (await crm_client.get(f"/api/v1/companies/{result.company_id}/assessments")).json()
    assert (await crm_client.get(f"/api/v1/companies/{result.company_id}/recommendations")).json()
    assert (
        await crm_client.get(f"/api/v1/companies/{result.company_id}/generation/drafts")
    ).json() == []


@pytest.mark.asyncio
async def test_worker_recovers_interrupted_tasks_and_stops_retry_loop(
    crm_client: AsyncClient,
) -> None:
    session = crm_client._test_session  # type: ignore[attr-defined]
    owner_id = await session.scalar(select(SearchTask.owner_id).limit(1))
    if owner_id is None:
        response = await crm_client.post(
            "/api/v1/search-tasks",
            json={
                "original_query": "Synthetic worker recovery owner lookup",
                "task_type": "find_companies",
                "result_limit": 1,
            },
        )
        assert response.status_code == 201, response.text
        owner_id = await session.scalar(select(SearchTask.owner_id).limit(1))
        assert owner_id is not None
    recoverable = SearchTask(
        owner_id=owner_id,
        original_query="Synthetic interrupted task",
        query_language="en",
        task_type="find_companies",
        result_limit=1,
        status="RUNNING",
        current_stage="research_completed",
        attempt_count=1,
    )
    exhausted = SearchTask(
        owner_id=owner_id,
        original_query="Synthetic exhausted task",
        query_language="en",
        task_type="find_companies",
        result_limit=1,
        status="RUNNING",
        current_stage="scoring_completed",
        attempt_count=3,
    )
    session.add_all([recoverable, exhausted])
    await session.commit()

    recovered_count, failed_count = await recover_interrupted_tasks_in_session(session, 3)

    assert recovered_count >= 1
    assert failed_count >= 1
    await session.refresh(recoverable)
    await session.refresh(exhausted)
    assert recoverable.status == "RUNNING"
    assert recoverable.current_stage == "queued_for_execution"
    assert exhausted.status == "FAILED"
    assert exhausted.current_stage == "failed"
    assert exhausted.failure_code == "worker_retry_exhausted"


@pytest.mark.asyncio
async def test_crm_server_rendered_pages_use_postgresql(crm_client: AsyncClient) -> None:
    expected_content = {
        "/companies": "Подобранные компании",
        "/letters": "Письма",
        "/profile": "Мой профиль",
        "/settings": "Настройки",
        "/pipeline": "Pipeline",
        "/contacts": "Профессиональные контакты",
        "/jobs": "Вакансии",
        "/campaigns": "Campaigns",
        "/communications": "Communication timeline",
        "/candidate-profile": "Профессиональный опыт",
    }

    entrypoint = await crm_client.get("/")
    assert entrypoint.status_code == 303
    assert entrypoint.headers["location"] == "/companies"

    for path, marker in expected_content.items():
        response = await crm_client.get(path)
        assert response.status_code == 200, f"{path}: {response.text}"
        assert marker in response.text


@pytest.mark.asyncio
async def test_dashboard_locale_persists_independently_in_local_mode(
    crm_client: AsyncClient,
) -> None:
    switched_en = await crm_client.post(
        "/preferences/locale",
        data={"locale": "en", "next_path": "/settings"},
        follow_redirects=False,
    )
    assert switched_en.status_code == 303
    assert switched_en.headers["location"] == "/settings"
    settings_en = await crm_client.get("/settings")
    companies_en = await crm_client.get("/companies")
    assert "Interface language" in settings_en.text
    assert "Selected companies" in companies_en.text
    assert "Настройки" not in settings_en.text

    switched_ru = await crm_client.post(
        "/preferences/locale",
        data={"locale": "ru", "next_path": "/settings"},
        follow_redirects=False,
    )
    assert switched_ru.status_code == 303
    settings_ru = await crm_client.get("/settings")
    companies_ru = await crm_client.get("/companies")
    assert "Язык интерфейса" in settings_ru.text
    assert "Подобранные компании" in companies_ru.text
    assert 'type="number"' not in companies_ru.text
    assert 'name="result_limit" value="5"' in companies_ru.text
    assert "Interface language" not in settings_ru.text


@pytest.mark.asyncio
async def test_owner_letter_workflow_revisions_defer_restore_and_localization(
    crm_client: AsyncClient,
) -> None:
    session: AsyncSession = crm_client._test_session  # type: ignore[attr-defined]
    company = await session.scalar(select(Company).where(Company.name == "Banco Plata"))
    if company is None:
        pytest.skip("Banco Plata local-pilot fixture is unavailable")
    current = await session.scalar(
        select(MessageDraft)
        .where(MessageDraft.company_id == company.id, MessageDraft.variant == "A")
        .order_by(MessageDraft.revision.desc(), MessageDraft.created_at.desc())
        .limit(1)
    )
    if current is None:
        pytest.skip("Banco Plata Professional draft is unavailable")
    contact = await session.get(Contact, current.contact_id)
    assert contact is not None
    contact_was_suppressed = contact.do_not_contact
    contact.do_not_contact = False
    active_approvals = list(
        await session.scalars(
            select(DraftApproval).where(
                DraftApproval.draft_id == current.id,
                DraftApproval.invalidated_at.is_(None),
                DraftApproval.consumed_at.is_(None),
            )
        )
    )
    for approval in active_approvals:
        approval.invalidated_at = datetime.now(UTC)
        approval.invalidation_reason = "synthetic_workflow_test_setup"
    company.pipeline_status = "review"
    await session.flush()

    ru_page = await crm_client.get(f"/review/{current.id}")
    assert ru_page.status_code == 200
    assert "Выбрать и подтвердить" in ru_page.text
    assert "Переписать с помощью ИИ" in ru_page.text
    assert "Не отправлять" in ru_page.text
    assert "Технические детали" not in ru_page.text
    assert "Local Pilot - Airalo calibration" not in ru_page.text

    revisions_before_unavailable = len(
        list(
            await session.scalars(
                select(MessageDraft).where(
                    MessageDraft.generation_run_id == current.generation_run_id,
                    MessageDraft.variant == current.variant,
                )
            )
        )
    )
    unavailable_rewrite = await crm_client.post(
        f"/review/{current.id}/regenerate",
        data={
            "revision": current.revision,
            "campaign_goal": "Make this less formal",
            "language": "same",
        },
        follow_redirects=False,
    )
    assert unavailable_rewrite.status_code == 303
    assert "error=ai_rewrite_unavailable" in unavailable_rewrite.headers["location"]
    revisions_after_unavailable = len(
        list(
            await session.scalars(
                select(MessageDraft).where(
                    MessageDraft.generation_run_id == current.generation_run_id,
                    MessageDraft.variant == current.variant,
                )
            )
        )
    )
    assert revisions_after_unavailable == revisions_before_unavailable

    selected = await crm_client.post(
        f"/review/{current.id}/approve",
        data={"revision": current.revision, "comment": "Synthetic variant selection"},
        follow_redirects=False,
    )
    assert selected.status_code == 303
    selected_page = await crm_client.get(selected.headers["location"])
    assert "Версия подтверждена" in selected_page.text
    assert "Идентификатор подтверждения" not in selected_page.text

    feedback_response = await crm_client.post(
        f"/review/{current.id}/feedback",
        data={"decision": "good", "reason": "good_personalization", "comment": "Useful"},
        follow_redirects=False,
    )
    assert feedback_response.status_code == 303
    saved_feedback = await session.scalar(
        select(PilotCalibrationNote)
        .where(
            PilotCalibrationNote.company_id == company.id,
            PilotCalibrationNote.category == "draft_owner_feedback",
        )
        .order_by(PilotCalibrationNote.created_at.desc())
    )
    assert saved_feedback is not None
    assert saved_feedback.rule_version == "owner-feedback-v1"
    assert '"decision": "good"' in saved_feedback.observation

    manually_edited = await crm_client.post(
        f"/review/{current.id}/edit",
        data={
            "revision": current.revision,
            "subject": current.subject,
            "body": f"{current.body}\n\nManual owner clarification.",
            "comment": "Synthetic manual edit",
        },
        follow_redirects=False,
    )
    assert manually_edited.status_code == 303
    manual_id = UUID(manually_edited.headers["location"].rsplit("/", 1)[-1])
    manual = await session.get(MessageDraft, manual_id)
    assert manual is not None and manual.revision == current.revision + 1
    approval_after_edit = await session.scalar(
        select(DraftApproval).where(DraftApproval.draft_id == current.id)
    )
    assert approval_after_edit is not None and approval_after_edit.invalidated_at is not None

    app.dependency_overrides[get_ai_rewrite_provider] = lambda: FakeAIRewriteProvider()
    try:
        rewritten_response = await crm_client.post(
            f"/review/{manual.id}/regenerate",
            data={
                "revision": manual.revision,
                "campaign_goal": "Make the second paragraph more natural",
                "language": "same",
            },
            follow_redirects=False,
        )
    finally:
        app.dependency_overrides.pop(get_ai_rewrite_provider, None)
    assert rewritten_response.status_code == 303
    rewritten_id = UUID(rewritten_response.headers["location"].rsplit("/", 1)[-1])
    rewritten = await session.get(MessageDraft, rewritten_id)
    assert rewritten is not None
    assert rewritten.revision == manual.revision + 1
    assert rewritten.provider == "synthetic-ai-provider"

    old_revision_page = await crm_client.get(
        f"/review/{rewritten.id}", params={"view": str(current.id)}
    )
    assert old_revision_page.status_code == 200
    assert "Предыдущая версия" in old_revision_page.text
    assert "Восстановить эту версию" in old_revision_page.text
    restored_response = await crm_client.post(
        f"/review/{rewritten.id}/restore",
        data={
            "revision": rewritten.revision,
            "source_draft_id": str(current.id),
            "comment": "Synthetic history restore",
        },
        follow_redirects=False,
    )
    assert restored_response.status_code == 303
    restored_id = UUID(restored_response.headers["location"].split("?", 1)[0].rsplit("/", 1)[-1])
    restored = await session.get(MessageDraft, restored_id)
    assert restored is not None and restored.revision == rewritten.revision + 1
    assert restored.body == current.body

    confirmed_restore = await crm_client.post(
        f"/review/{restored.id}/approve",
        data={"revision": restored.revision},
        follow_redirects=False,
    )
    assert confirmed_restore.status_code == 303
    confirmed_page = await crm_client.get(confirmed_restore.headers["location"])
    assert "Проверить тестовую доставку" in confirmed_page.text
    assert "disabled" not in confirmed_page.text.split("Проверить тестовую доставку", 1)[0][-200:]

    deferred = await crm_client.post(
        f"/review/{restored.id}/defer",
        data={"revision": restored.revision},
        follow_redirects=False,
    )
    assert deferred.status_code == 303
    assert deferred.headers["location"] == "/letters?tab=deferred"
    deferred_page = await crm_client.get("/letters?tab=deferred")
    assert company.name in deferred_page.text
    assert "Открыть компанию" in deferred_page.text

    returned = await crm_client.post(
        f"/review/{restored.id}/restore-deferred",
        data={"revision": restored.revision},
        follow_redirects=False,
    )
    assert returned.status_code == 303
    assert returned.headers["location"] == "/letters?tab=drafts"

    reconfirmed = await crm_client.post(
        f"/review/{restored.id}/approve",
        data={"revision": restored.revision, "comment": "Reconfirmed after defer"},
        follow_redirects=False,
    )
    assert reconfirmed.status_code == 303
    reconfirmed_page = await crm_client.get(reconfirmed.headers["location"])
    assert "Версия подтверждена" in reconfirmed_page.text

    crm_client.cookies.set("outreach_dashboard_locale", "en")
    english_page = await crm_client.get(f"/review/{restored.id}")
    assert "Select and confirm" in english_page.text
    assert "Rewrite with AI" in english_page.text
    assert "Do not send" in english_page.text
    crm_client.cookies.set("outreach_dashboard_locale", "ru")

    closed = await crm_client.post(
        f"/review/{restored.id}/reject",
        data={"revision": restored.revision},
        follow_redirects=False,
    )
    assert closed.status_code == 303
    assert closed.headers["location"] == "/letters?tab=closed"
    closed_page = await crm_client.get("/letters?tab=closed")
    assert company.name in closed_page.text
    assert "Вернуть в работу" in closed_page.text
    await session.refresh(contact)
    assert contact.do_not_contact is False
    contact.do_not_contact = contact_was_suppressed
