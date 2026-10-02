"""Async SQLAlchemy engine and request-scoped session."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()
engine = create_async_engine(
    settings.database_url.get_secret_value(),
    pool_pre_ping=True,
    echo=False,
)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session


async def close_database() -> None:
    await engine.dispose()
