"""Schemas used by operational endpoints."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    environment: str
