"""Environment-backed application configuration."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Runtime settings. Required connection settings are never hard-coded."""

    database_url: str = Field(validation_alias="DATABASE_URL")
    postgres_db: str | None = Field(default=None, validation_alias="POSTGRES_DB")
    postgres_user: str | None = Field(default=None, validation_alias="POSTGRES_USER")
    postgres_password: str | None = Field(default=None, validation_alias="POSTGRES_PASSWORD")
    app_env: str = Field(default="development", validation_alias="APP_ENV")

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value.startswith(("postgresql+asyncpg://", "sqlite+aiosqlite://")):
            message = "DATABASE_URL must use postgresql+asyncpg (or sqlite+aiosqlite for tests)."
            raise ValueError(message)
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the immutable, cached settings instance for this process."""

    return Settings()
