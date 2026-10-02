"""Manual Search Task API and owner-facing form actions."""

from datetime import UTC, datetime
from typing import Annotated, cast
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select

from app.api.crm import DbSession
from app.modules.audit.models import AuditEvent
from app.modules.auth.models import User
from app.modules.crm.models import Company
from app.modules.search_tasks.models import SearchTask, SearchTaskResult
from app.modules.search_tasks.parsing import infer_search_task_intent, parse_search_query
from app.modules.search_tasks.schemas import (
    SearchTaskCreate,
    SearchTaskRead,
    SearchTaskResultCreate,
    SearchTaskStatus,
    SearchTaskType,
)

api_router = APIRouter(prefix="/api/v1/search-tasks", tags=["search-tasks"])
web_router = APIRouter(include_in_schema=False)


def api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


async def owner_for_request(request: Request, session: DbSession) -> User:
    owner = cast(User | None, getattr(request.state, "owner", None))
    if owner is not None:
        stored = await session.get(User, owner.id)
        if stored is not None:
            return stored
    stored = await session.scalar(
        select(User).where(User.status == "active").order_by(User.created_at).limit(1)
    )
    if stored is None:
        raise api_error(409, "owner_missing", "The local owner account must exist")
    return cast(User, stored)


def audit(
    session: DbSession,
    request: Request,
    task: SearchTask,
    action: str,
    safe_diff: dict[str, object] | None = None,
) -> None:
    session.add(
        AuditEvent(
            actor="owner",
            action=action,
            entity_type="search_task",
            entity_id=str(task.id),
            result="success",
            safe_diff=safe_diff,
            request_id=str(getattr(request.state, "request_id", "missing-request-id")),
        )
    )


async def create_task_record(
    payload: SearchTaskCreate, request: Request, session: DbSession
) -> SearchTask:
    owner = await owner_for_request(request, session)
    parsed = parse_search_query(payload.original_query)
    direct_target = payload.company_name_or_url or parsed.direct_target
    if payload.task_type == SearchTaskType.ANALYZE_COMPANY and not direct_target:
        raise api_error(
            422,
            "company_target_required",
            "Company name or URL is required for direct analysis",
        )
    task = SearchTask(
        owner_id=owner.id,
        original_query=payload.original_query,
        query_language=parsed.language,
        task_type=payload.task_type.value,
        parsed_country=parsed.country,
        parsed_region=parsed.region,
        parsed_industry=parsed.industry,
        parsed_focus=parsed.focus,
        company_name_or_url=direct_target,
        result_limit=parsed.explicit_limit or payload.result_limit,
        status=SearchTaskStatus.QUEUED.value,
    )
    session.add(task)
    await session.flush()
    audit(
        session,
        request,
        task,
        "search_task_created",
        {
            "task_type": task.task_type,
            "query_language": task.query_language,
            "parsed_country": task.parsed_country,
            "parsed_region": task.parsed_region,
            "parsed_industry": task.parsed_industry,
            "parsed_focus": task.parsed_focus,
            "result_limit": task.result_limit,
        },
    )
    await session.commit()
    await session.refresh(task)
    return task


async def task_for_owner(task_id: UUID, request: Request, session: DbSession) -> SearchTask:
    owner = await owner_for_request(request, session)
    task = await session.get(SearchTask, task_id)
    if task is None or task.owner_id != owner.id:
        raise api_error(404, "search_task_not_found", "Search task was not found")
    return task


def target_domain(value: str) -> str | None:
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return parsed.hostname.removeprefix("www.") if parsed.hostname else None


async def link_existing_direct_company(task: SearchTask, session: DbSession) -> Company | None:
    target = (task.company_name_or_url or "").strip()
    domain = target_domain(target)
    query = select(Company).where(Company.is_synthetic.is_(False))
    if domain:
        query = query.where(Company.normalized_domain == domain)
    else:
        query = query.where(func.lower(Company.name) == target.lower())
    company = await session.scalar(query.limit(1))
    if company is None:
        return None
    existing = await session.get(
        SearchTaskResult,
        {"search_task_id": task.id, "company_id": company.id},
    )
    if existing is None:
        session.add(
            SearchTaskResult(
                search_task_id=task.id,
                company_id=company.id,
                accepted=True,
                linked_at=datetime.now(UTC),
            )
        )
    task.found_count = 1
    task.accepted_count = 1
    task.status = SearchTaskStatus.COMPLETED.value
    task.completed_at = datetime.now(UTC)
    return company


async def start_task_record(task: SearchTask, request: Request, session: DbSession) -> SearchTask:
    if task.status != SearchTaskStatus.QUEUED.value:
        raise api_error(409, "invalid_search_task_status", "Only a queued task can be started")
    task.status = SearchTaskStatus.RUNNING.value
    task.started_at = datetime.now(UTC)
    task.current_stage = "queued_for_execution"
    task.failure_code = None
    task.failure_reason = None
    audit(
        session,
        request,
        task,
        "search_task_started",
        {"executor_queued": True},
    )
    await session.commit()
    await session.refresh(task)
    return task


@api_router.get("", response_model=list[SearchTaskRead])
async def list_search_tasks(request: Request, session: DbSession) -> list[SearchTask]:
    owner = await owner_for_request(request, session)
    return list(
        await session.scalars(
            select(SearchTask)
            .where(SearchTask.owner_id == owner.id)
            .order_by(SearchTask.created_at.desc())
            .limit(100)
        )
    )


@api_router.post("", response_model=SearchTaskRead, status_code=status.HTTP_201_CREATED)
async def create_search_task(
    payload: SearchTaskCreate, request: Request, session: DbSession
) -> SearchTask:
    return await create_task_record(payload, request, session)


@api_router.post("/{task_id}/start", response_model=SearchTaskRead)
async def start_search_task(
    task_id: UUID,
    request: Request,
    session: DbSession,
) -> SearchTask:
    return await start_task_record(
        await task_for_owner(task_id, request, session), request, session
    )


@api_router.post("/{task_id}/cancel", response_model=SearchTaskRead)
async def cancel_search_task(task_id: UUID, request: Request, session: DbSession) -> SearchTask:
    task = await task_for_owner(task_id, request, session)
    if task.status in {
        SearchTaskStatus.COMPLETED.value,
        SearchTaskStatus.FAILED.value,
        SearchTaskStatus.CANCELLED.value,
    }:
        return task
    task.status = SearchTaskStatus.CANCELLED.value
    task.completed_at = datetime.now(UTC)
    audit(session, request, task, "search_task_cancelled")
    await session.commit()
    await session.refresh(task)
    return task


@api_router.post("/{task_id}/results", response_model=SearchTaskRead)
async def attach_search_task_result(
    task_id: UUID,
    payload: SearchTaskResultCreate,
    request: Request,
    session: DbSession,
) -> SearchTask:
    task = await task_for_owner(task_id, request, session)
    company = await session.get(Company, payload.company_id)
    if company is None:
        raise api_error(404, "company_not_found", "Company was not found")
    existing = await session.get(
        SearchTaskResult,
        {"search_task_id": task.id, "company_id": company.id},
    )
    if existing is None:
        session.add(
            SearchTaskResult(
                search_task_id=task.id,
                company_id=company.id,
                accepted=payload.accepted,
                linked_at=datetime.now(UTC),
            )
        )
    else:
        existing.accepted = payload.accepted
    await session.flush()
    task.found_count = int(
        await session.scalar(
            select(func.count())
            .select_from(SearchTaskResult)
            .where(SearchTaskResult.search_task_id == task.id)
        )
        or 0
    )
    task.accepted_count = int(
        await session.scalar(
            select(func.count())
            .select_from(SearchTaskResult)
            .where(
                SearchTaskResult.search_task_id == task.id,
                SearchTaskResult.accepted.is_(True),
            )
        )
        or 0
    )
    if payload.complete_task:
        task.status = SearchTaskStatus.COMPLETED.value
        task.completed_at = datetime.now(UTC)
    audit(
        session,
        request,
        task,
        "search_task_result_linked",
        {"company_id": str(company.id), "accepted": payload.accepted},
    )
    await session.commit()
    await session.refresh(task)
    return task


@web_router.post("/search-tasks")
async def create_search_task_form(
    request: Request,
    session: DbSession,
    original_query: Annotated[str, Form()],
    task_type: Annotated[SearchTaskType | None, Form()] = None,
    result_limit: Annotated[int, Form()] = 5,
    company_name_or_url: Annotated[str, Form()] = "",
) -> RedirectResponse:
    inferred_type, inferred_target = infer_search_task_intent(original_query)
    # The owner-facing form is natural-language first. Legacy/advanced form
    # values are accepted, but an empty direct target no longer forces the
    # default "find" mode when the text clearly asks for one-company analysis.
    resolved_type = task_type
    if resolved_type is None or (
        resolved_type == SearchTaskType.FIND_COMPANIES and not company_name_or_url
    ):
        resolved_type = SearchTaskType(inferred_type)
    resolved_target = company_name_or_url or inferred_target
    task = await create_task_record(
        SearchTaskCreate(
            original_query=original_query,
            task_type=resolved_type,
            company_name_or_url=resolved_target,
            result_limit=result_limit,
        ),
        request,
        session,
    )
    await start_task_record(task, request, session)
    return RedirectResponse("/companies?task=started#search", status_code=303)


@web_router.post("/search-tasks/{task_id}/start")
async def start_search_task_form(
    task_id: UUID,
    request: Request,
    session: DbSession,
) -> RedirectResponse:
    task = await task_for_owner(task_id, request, session)
    await start_task_record(task, request, session)
    return RedirectResponse("/companies?task=started#search-tasks", status_code=303)


@web_router.post("/search-tasks/{task_id}/cancel")
async def cancel_search_task_form(
    task_id: UUID, request: Request, session: DbSession
) -> RedirectResponse:
    task = await cancel_search_task(task_id, request, session)
    notice = "cancelled" if task.status == SearchTaskStatus.CANCELLED.value else "finished"
    return RedirectResponse(f"/companies?task={notice}#search-tasks", status_code=303)
