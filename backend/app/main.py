"""FastAPI application for YUNABiznes."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import get_settings
from app.db.session import database


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialize and cleanly dispose of the shared async database engine."""

    database.initialize(get_settings().database_url)
    try:
        yield
    finally:
        await database.dispose()


app = FastAPI(title="YUNABiznes Inventory API", version="0.1.0", lifespan=lifespan)
app.include_router(api_router)
