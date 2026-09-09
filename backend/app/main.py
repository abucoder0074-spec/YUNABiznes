"""FastAPI application for YUNABiznes."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError

from app.api.errors import catalog_error_handler, integrity_error_handler, validation_error_handler
from app.api.router import api_router
from app.core.config import get_settings
from app.db.session import database
from app.services.catalogs import CatalogError
from app.services.payments import PaymentError
from app.services.production import ProductionIssueError
from app.services.purchases import PurchaseError
from app.services.returns import ReturnError


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialize and cleanly dispose of the shared async database engine."""

    database.initialize(get_settings().database_url)
    try:
        yield
    finally:
        await database.dispose()


app = FastAPI(title="YUNABiznes Inventory API", version="0.1.0", lifespan=lifespan)
app.add_exception_handler(CatalogError, catalog_error_handler)
app.add_exception_handler(PurchaseError, catalog_error_handler)
app.add_exception_handler(PaymentError, catalog_error_handler)
app.add_exception_handler(ReturnError, catalog_error_handler)
app.add_exception_handler(ProductionIssueError, catalog_error_handler)
app.add_exception_handler(IntegrityError, integrity_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.include_router(api_router)
