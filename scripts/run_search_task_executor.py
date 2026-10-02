"""Execute one existing RUNNING Search Task for the Local Pilot."""

import argparse
import asyncio
from uuid import UUID

import app.main  # noqa: F401 - register every SQLAlchemy model for standalone execution
from app.modules.search_tasks.executor import (
    execute_search_task_by_id,
    requeue_completed_task_for_refresh,
    requeue_interrupted_task_by_id,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True, type=UUID)
    parser.add_argument("--retry-interrupted", action="store_true")
    parser.add_argument("--refresh-completed", action="store_true")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    if args.retry_interrupted:
        await requeue_interrupted_task_by_id(args.task_id)
    if args.refresh_completed:
        await requeue_completed_task_for_refresh(args.task_id)
    claimed = await execute_search_task_by_id(args.task_id)
    print("processed" if claimed else "not_claimed")


if __name__ == "__main__":
    asyncio.run(main())
