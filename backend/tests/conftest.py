"""Shared isolated database fixtures for the foundation tests."""

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - ensures every table is registered
from app.db.base import Base


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Provide a clean in-memory schema for each test without a PostgreSQL dependency."""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()

    await engine.dispose()
