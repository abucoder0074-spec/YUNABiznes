"""Reference-data API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.catalogs import (
    Page,
    ProductCreate,
    ProductRead,
    ProductUpdate,
    SupplierCreate,
    SupplierDetail,
    SupplierRead,
    SupplierUpdate,
    UnitCreate,
    UnitRead,
    UnitUpdate,
    WarehouseCreate,
    WarehouseRead,
    WarehouseUpdate,
)
from app.services import catalogs

router = APIRouter(prefix="/api/v1", tags=["catalogs"])


def _paging(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    search: str | None = Query(default=None, min_length=1, max_length=100),
    include_inactive: bool = Query(default=False),
) -> tuple[int, int, str | None, bool]:
    return offset, limit, search, not include_inactive


@router.get("/units", response_model=Page[UnitRead])
async def list_units(
    paging: tuple[int, int, str | None, bool] = Depends(_paging),
    session: AsyncSession = Depends(get_session),
) -> Page[UnitRead]:
    offset, limit, search, active_only = paging
    items, total = await catalogs.list_entities(
        session, catalogs.Unit, offset=offset, limit=limit, search=search, active_only=active_only
    )
    return Page(items=items, total=total, offset=offset, limit=limit)


@router.post("/units", response_model=UnitRead, status_code=status.HTTP_201_CREATED)
async def create_unit(data: UnitCreate, session: AsyncSession = Depends(get_session)) -> UnitRead:
    return await catalogs.create_unit(session, data.model_dump())


@router.patch("/units/{entity_id}", response_model=UnitRead)
async def update_unit(
    entity_id: UUID, data: UnitUpdate, session: AsyncSession = Depends(get_session)
) -> UnitRead:
    return await catalogs.update_unit(session, entity_id, data.model_dump(exclude_unset=True))


@router.get("/products", response_model=Page[ProductRead])
async def list_products(
    paging: tuple[int, int, str | None, bool] = Depends(_paging),
    session: AsyncSession = Depends(get_session),
) -> Page[ProductRead]:
    offset, limit, search, active_only = paging
    items, total = await catalogs.list_entities(
        session, catalogs.Product, offset=offset, limit=limit, search=search, active_only=active_only
    )
    return Page(items=items, total=total, offset=offset, limit=limit)


@router.post("/products", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
async def create_product(
    data: ProductCreate, session: AsyncSession = Depends(get_session)
) -> ProductRead:
    return await catalogs.create_product(session, data.model_dump())


@router.patch("/products/{entity_id}", response_model=ProductRead)
async def update_product(
    entity_id: UUID, data: ProductUpdate, session: AsyncSession = Depends(get_session)
) -> ProductRead:
    return await catalogs.update_product(session, entity_id, data.model_dump(exclude_unset=True))


@router.get("/warehouses", response_model=Page[WarehouseRead])
async def list_warehouses(
    paging: tuple[int, int, str | None, bool] = Depends(_paging),
    session: AsyncSession = Depends(get_session),
) -> Page[WarehouseRead]:
    offset, limit, search, active_only = paging
    items, total = await catalogs.list_entities(
        session, catalogs.Warehouse, offset=offset, limit=limit, search=search, active_only=active_only
    )
    return Page(items=items, total=total, offset=offset, limit=limit)


@router.post("/warehouses", response_model=WarehouseRead, status_code=status.HTTP_201_CREATED)
async def create_warehouse(
    data: WarehouseCreate, session: AsyncSession = Depends(get_session)
) -> WarehouseRead:
    return await catalogs.create_warehouse(session, data.model_dump())


@router.patch("/warehouses/{entity_id}", response_model=WarehouseRead)
async def update_warehouse(
    entity_id: UUID, data: WarehouseUpdate, session: AsyncSession = Depends(get_session)
) -> WarehouseRead:
    return await catalogs.update_warehouse(session, entity_id, data.model_dump(exclude_unset=True))


@router.get("/suppliers", response_model=Page[SupplierRead])
async def list_suppliers(
    paging: tuple[int, int, str | None, bool] = Depends(_paging),
    session: AsyncSession = Depends(get_session),
) -> Page[SupplierRead]:
    offset, limit, search, active_only = paging
    items, total = await catalogs.list_entities(
        session, catalogs.Supplier, offset=offset, limit=limit, search=search, active_only=active_only
    )
    return Page(items=items, total=total, offset=offset, limit=limit)


@router.post("/suppliers", response_model=SupplierRead, status_code=status.HTTP_201_CREATED)
async def create_supplier(
    data: SupplierCreate, session: AsyncSession = Depends(get_session)
) -> SupplierRead:
    return await catalogs.create_supplier(session, data.model_dump())


@router.patch("/suppliers/{entity_id}", response_model=SupplierRead)
async def update_supplier(
    entity_id: UUID, data: SupplierUpdate, session: AsyncSession = Depends(get_session)
) -> SupplierRead:
    return await catalogs.update_supplier(session, entity_id, data.model_dump(exclude_unset=True))


@router.get("/suppliers/{entity_id}", response_model=SupplierDetail)
async def get_supplier(
    entity_id: UUID, session: AsyncSession = Depends(get_session)
) -> SupplierDetail:
    return await catalogs.supplier_detail(session, entity_id)
