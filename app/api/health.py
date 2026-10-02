"""Liveness and readiness endpoints."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.session import get_db_session

router = APIRouter(prefix="/api/v1/health", tags=["health"])
logger = logging.getLogger("app.health")


@router.get("/live", summary="Process liveness")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", summary="Application readiness")
async def readiness(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, str]:
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.warning(
            "readiness_database_unavailable",
            extra={"safe_error_code": type(exc).__name__},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "database_unavailable", "message": "Database is not ready"},
        ) from exc
    return {"status": "ok", "database": "ok"}
