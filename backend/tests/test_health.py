"""Basic API availability test."""

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from app.core.config import get_settings
from app.main import app


def test_health_endpoint_reports_environment(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("APP_ENV", "test")
    get_settings.cache_clear()

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "environment": "test"}
    get_settings.cache_clear()
