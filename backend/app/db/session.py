"""Async SQLAlchemy engine and transaction-scoped session dependency."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class DatabaseSessionManager:
    """Owns the engine and creates a transaction for each request."""

    def __init__(self) -> None:
        self.engine: AsyncEngine | None = None
        self.session_factory: async_sessionmaker[AsyncSession] | None = None

    def initialize(self, database_url: str) -> None:
        if self.engine is not None:
            return
        self.engine = create_async_engine(database_url, pool_pre_ping=True)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def dispose(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()
        self.engine = None
        self.session_factory = None

    async def session(self) -> AsyncIterator[AsyncSession]:
        if self.session_factory is None:
            raise RuntimeError("Database session manager has not been initialized.")
        async with self.session_factory() as session:
            async with session.begin():
                yield session


database = DatabaseSessionManager()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that commits or rolls back the request atomically."""

    async for session in database.session():
        yield session
