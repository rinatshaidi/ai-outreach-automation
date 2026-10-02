"""Durable single-process worker for queued Local Pilot Search Tasks."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.infrastructure.db.session import SessionFactory
from app.modules.mailbox.gmail import GmailProviderError, sync_gmail_replies
from app.modules.search_tasks.daily import queue_daily_discovery_if_due
from app.modules.search_tasks.executor import execute_search_task_by_id, task_audit
from app.modules.search_tasks.models import SearchTask
from app.modules.search_tasks.schemas import SearchTaskStatus

logger = logging.getLogger("app.background_worker")
QUEUED_STAGE = "queued_for_execution"


async def recover_interrupted_tasks_in_session(
    session: AsyncSession, max_attempts: int
) -> tuple[int, int]:
    """Apply recovery decisions inside the caller's transaction."""

    recovered = 0
    failed = 0
    tasks = list(
        await session.scalars(
            select(SearchTask).where(
                SearchTask.status == SearchTaskStatus.RUNNING.value,
                SearchTask.current_stage.is_not(None),
                SearchTask.current_stage != QUEUED_STAGE,
            )
        )
    )
    for task in tasks:
        previous_stage = task.current_stage
        if task.attempt_count >= max_attempts:
            task.status = SearchTaskStatus.FAILED.value
            task.current_stage = "failed"
            task.failure_code = "worker_retry_exhausted"
            task.failure_reason = (
                "Background processing was interrupted repeatedly. "
                "Review the task and start a new attempt manually."
            )
            task.completed_at = datetime.now(UTC)
            task_audit(
                session,
                task,
                "search_task_retry_exhausted",
                result="failed",
                safe_diff={
                    "previous_stage": previous_stage,
                    "attempt_count": task.attempt_count,
                },
            )
            failed += 1
        else:
            task.current_stage = QUEUED_STAGE
            task.failure_code = None
            task.failure_reason = None
            task_audit(
                session,
                task,
                "search_task_recovered_by_worker",
                safe_diff={
                    "previous_stage": previous_stage,
                    "attempt_count": task.attempt_count,
                },
            )
            recovered += 1
    await session.commit()
    return recovered, failed


async def recover_interrupted_tasks(max_attempts: int) -> tuple[int, int]:
    """Requeue interrupted work, or fail it after the configured retry ceiling."""

    async with SessionFactory() as session:
        recovered, failed = await recover_interrupted_tasks_in_session(session, max_attempts)
    if recovered or failed:
        logger.warning("worker_recovery recovered=%s failed=%s", recovered, failed)
    return recovered, failed


async def queued_task_ids(limit: int = 10) -> list[UUID]:
    """Return a bounded FIFO batch. Atomic claiming still happens in the executor."""

    async with SessionFactory() as session:
        return list(
            await session.scalars(
                select(SearchTask.id)
                .where(
                    SearchTask.status == SearchTaskStatus.RUNNING.value,
                    or_(
                        SearchTask.current_stage.is_(None),
                        SearchTask.current_stage == QUEUED_STAGE,
                    ),
                )
                .order_by(SearchTask.created_at)
                .limit(limit)
            )
        )


async def execute_with_heartbeat(
    task_id: UUID, *, heartbeat_path: Path, interval_seconds: int
) -> bool:
    """Keep liveness independent of a legitimately long research task."""

    execution = asyncio.create_task(execute_search_task_by_id(task_id))
    try:
        while not execution.done():
            await asyncio.wait({execution}, timeout=max(1, min(interval_seconds, 20)))
            write_heartbeat(heartbeat_path)
        return await execution
    finally:
        if not execution.done():
            execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)


def write_heartbeat(path: Path) -> None:
    path.write_text(datetime.now(UTC).isoformat(), encoding="ascii")


async def run_forever(
    *,
    poll_seconds: int,
    max_attempts: int,
    heartbeat_path: Path,
) -> None:
    """Poll durable DB state and execute tasks sequentially for the single-owner MVP."""

    await recover_interrupted_tasks(max_attempts)
    settings = get_settings()
    next_mailbox_sync = 0.0
    logger.info(
        "background_worker_started poll_seconds=%s max_attempts=%s",
        poll_seconds,
        max_attempts,
    )
    while True:
        write_heartbeat(heartbeat_path)
        if settings.daily_discovery_enabled:
            async with SessionFactory() as session:
                daily_task = await queue_daily_discovery_if_due(
                    session,
                    now=datetime.now(UTC),
                    timezone_name=settings.user_timezone,
                    scheduled_hour=settings.daily_discovery_hour,
                    result_limit=settings.daily_discovery_result_limit,
                )
            if daily_task is not None:
                logger.info("daily_discovery_queued task_id=%s", daily_task.id)
        task_ids = await queued_task_ids()
        for task_id in task_ids:
            logger.info("background_worker_processing task_id=%s", task_id)
            await execute_with_heartbeat(
                task_id,
                heartbeat_path=heartbeat_path,
                interval_seconds=poll_seconds,
            )
        if settings.gmail_sync_enabled and time.monotonic() >= next_mailbox_sync:
            try:
                async with SessionFactory() as session:
                    synchronized = await sync_gmail_replies(session, settings)
                if synchronized:
                    logger.info("gmail_reply_sync completed=%s", synchronized)
            except GmailProviderError as exc:
                logger.warning("gmail_reply_sync_failed code=%s", exc.code)
            except Exception:
                logger.exception("gmail_reply_sync_failed code=unexpected")
            next_mailbox_sync = time.monotonic() + settings.gmail_sync_interval_seconds
        if not task_ids:
            await asyncio.sleep(poll_seconds)
