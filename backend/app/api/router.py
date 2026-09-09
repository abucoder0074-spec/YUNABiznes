"""Top-level API router."""

from fastapi import APIRouter

from app.api.routes.catalogs import router as catalogs_router
from app.api.routes.health import router as health_router
from app.api.routes.inventory import router as inventory_router
from app.api.routes.operations import router as operations_router
from app.api.routes.payments import router as payments_router
from app.api.routes.production import router as production_router
from app.api.routes.purchases import router as purchases_router
from app.api.routes.returns import router as returns_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["system"])
api_router.include_router(catalogs_router)
api_router.include_router(purchases_router)
api_router.include_router(payments_router)
api_router.include_router(returns_router)
api_router.include_router(production_router)
api_router.include_router(inventory_router)
api_router.include_router(operations_router)
