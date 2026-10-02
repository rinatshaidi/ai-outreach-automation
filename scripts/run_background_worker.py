"""Run the production background worker without Redis or Celery."""

import asyncio
import logging
import tempfile
from pathlib import Path

import app.main  # noqa: F401 - register every SQLAlchemy model
from app.config import get_settings
from app.modules.search_tasks.worker import run_forever


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())
    await run_forever(
        poll_seconds=settings.background_worker_poll_seconds,
        max_attempts=settings.background_worker_max_attempts,
        heartbeat_path=Path(tempfile.gettempdir()) / "ai-outreach-worker-heartbeat",
    )


if __name__ == "__main__":
    asyncio.run(main())
