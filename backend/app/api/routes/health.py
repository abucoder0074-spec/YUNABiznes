"""Operational health endpoint."""

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.schemas.health import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Confirm the API is running without exposing connection credentials."""

    return HealthResponse(status="ok", environment=settings.app_env)
