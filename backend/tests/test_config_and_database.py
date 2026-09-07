"""Configuration and connection tests."""

from sqlalchemy import text

from app.core.config import Settings
from app.db.session import DatabaseSessionManager


def test_settings_accept_async_database_url() -> None:
    settings = Settings(DATABASE_URL="sqlite+aiosqlite:///:memory:", APP_ENV="test")

    assert settings.app_env == "test"
    assert settings.database_url == "sqlite+aiosqlite:///:memory:"


async def test_session_manager_connects_transactionally() -> None:
    manager = DatabaseSessionManager()
    manager.initialize("sqlite+aiosqlite:///:memory:")

    async for session in manager.session():
        assert (await session.execute(text("SELECT 1"))).scalar_one() == 1

    await manager.dispose()
