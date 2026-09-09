"""Catalog service regression tests for Phase 2."""

from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.main import app
from app.models.audit import AuditLog
from app.models.catalogs import Product, Warehouse
from app.services.catalogs import (
    CatalogError,
    create_product,
    create_supplier,
    create_unit,
    create_warehouse,
    list_entities,
    supplier_detail,
    update_unit,
)


async def test_catalog_create_list_search_pagination_and_audit(db_session: AsyncSession) -> None:
    unit = await create_unit(db_session, {"name": "Kilogram", "symbol": "kg"})
    await create_unit(db_session, {"name": "Liter", "symbol": "l"})
    product = await create_product(
        db_session,
        {"name": "Cacao", "code": "CACAO", "unit_id": unit.id, "minimum_stock": Decimal("2.5")},
    )
    await create_warehouse(db_session, {"name": "Main", "code": "MAIN"})

    rows, total = await list_entities(
        db_session, Product, offset=0, limit=1, search="cacao", active_only=True
    )
    assert [row.id for row in rows] == [product.id]
    assert total == 1
    assert await db_session.scalar(select(func.count()).select_from(AuditLog)) == 4


async def test_catalog_update_and_inactive_unit_is_rejected(db_session: AsyncSession) -> None:
    unit = await create_unit(db_session, {"name": "Kilogram", "symbol": "kg"})
    await update_unit(db_session, unit.id, {"is_active": False})
    with pytest.raises(CatalogError, match="active unit"):
        await create_product(db_session, {"name": "Cacao", "unit_id": unit.id})


async def test_duplicate_catalog_values_are_rejected(db_session: AsyncSession) -> None:
    await create_unit(db_session, {"name": "Kilogram", "symbol": "kg"})
    with pytest.raises(CatalogError, match="same unique value"):
        async with db_session.begin_nested():
            await create_unit(db_session, {"name": "Kilogram", "symbol": "other"})


async def test_supplier_detail_exposes_accounting_ready_totals(db_session: AsyncSession) -> None:
    supplier = await create_supplier(db_session, {"name": "Supplier A", "code": "SUP-A"})
    detail = await supplier_detail(db_session, supplier.id)
    assert detail["purchase_count"] == 0
    assert detail["payment_count"] == 0
    assert detail["return_count"] == 0
    assert detail["total_payable"] == Decimal("0")
    assert detail["total_paid"] == Decimal("0")
    assert detail["outstanding_debt"] == Decimal("0")


async def test_inactive_entities_are_hidden_by_default(db_session: AsyncSession) -> None:
    warehouse = await create_warehouse(db_session, {"name": "Main"})
    warehouse.is_active = False
    await db_session.flush()
    active_rows, active_total = await list_entities(
        db_session, Warehouse, offset=0, limit=50, search=None, active_only=True
    )
    all_rows, all_total = await list_entities(
        db_session, Warehouse, offset=0, limit=50, search=None, active_only=False
    )
    assert active_rows == []
    assert active_total == 0
    assert [row.id for row in all_rows] == [warehouse.id]
    assert all_total == 1


async def test_catalog_api_create_update_list_and_supplier_detail(
    db_session: AsyncSession,
) -> None:
    async def override_session():
        yield db_session

    app.dependency_overrides[get_session] = override_session
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            unit_response = await client.post("/api/v1/units", json={"name": "Kilogram", "symbol": "kg"})
            assert unit_response.status_code == 201
            unit_id = unit_response.json()["id"]

            product_response = await client.post(
                "/api/v1/products",
                json={"name": "Cacao", "code": "CACAO", "unit_id": unit_id},
            )
            assert product_response.status_code == 201
            assert product_response.json()["unit"]["symbol"] == "kg"

            list_response = await client.get("/api/v1/products?search=cacao&limit=1")
            assert list_response.status_code == 200
            assert list_response.json()["total"] == 1

            update_response = await client.patch(
                f"/api/v1/units/{unit_id}", json={"name": "Kilogram updated"}
            )
            assert update_response.status_code == 200

            supplier_response = await client.post(
                "/api/v1/suppliers", json={"name": "Supplier A", "code": "SUP-A"}
            )
            supplier_id = supplier_response.json()["id"]
            detail_response = await client.get(f"/api/v1/suppliers/{supplier_id}")
            assert detail_response.status_code == 200
            assert detail_response.json()["outstanding_debt"] == "0.00"

            invalid_response = await client.post("/api/v1/units", json={"name": "", "symbol": "x"})
            assert invalid_response.status_code == 422
            assert invalid_response.json()["error"]["code"] == "validation_error"
    finally:
        app.dependency_overrides.pop(get_session, None)
