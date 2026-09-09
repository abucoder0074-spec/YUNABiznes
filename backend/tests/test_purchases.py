"""Purchase workflow regression tests."""

from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import DocumentStatus, InventoryTransactionType, SupplierLedgerEntryType
from app.db.session import get_session
from app.main import app
from app.models.audit import AuditLog
from app.models.inventory import InventoryTransaction
from app.models.purchasing import SupplierLedger
from app.services.catalogs import (
    create_product,
    create_supplier,
    create_unit,
    create_warehouse,
    update_supplier,
)
from app.services.purchases import (
    PurchaseError,
    create_purchase,
    list_purchases,
    post_purchase_document,
    purchase_response,
    update_purchase,
)


async def setup_catalog(session: AsyncSession) -> dict[str, object]:
    unit = await create_unit(session, {"name": f"kg-{uuid4().hex[:6]}", "symbol": f"k{uuid4().hex[:3]}"})
    other_unit = await create_unit(session, {"name": f"piece-{uuid4().hex[:6]}", "symbol": f"p{uuid4().hex[:3]}"})
    product = await create_product(
        session, {"name": f"Cacao-{uuid4().hex[:6]}", "code": f"C-{uuid4().hex[:8]}", "unit_id": unit.id}
    )
    other_product = await create_product(
        session,
        {"name": f"Milk-{uuid4().hex[:6]}", "code": f"M-{uuid4().hex[:8]}", "unit_id": unit.id},
    )
    supplier = await create_supplier(session, {"name": f"Supplier-{uuid4().hex[:6]}"})
    warehouse = await create_warehouse(session, {"name": f"Warehouse-{uuid4().hex[:6]}"})
    return {
        "unit": unit,
        "other_unit": other_unit,
        "product": product,
        "other_product": other_product,
        "supplier": supplier,
        "warehouse": warehouse,
    }


def purchase_data(catalog: dict[str, object], *, items: list[dict[str, object]] | None = None) -> dict:
    product = catalog["product"]
    unit = catalog["unit"]
    return {
        "number": f"PUR-{uuid4().hex[:8]}",
        "supplier_id": catalog["supplier"].id,
        "warehouse_id": catalog["warehouse"].id,
        "items": items
        or [
            {
                "product_id": product.id,
                "unit_id": unit.id,
                "quantity": Decimal("2.5000"),
                "unit_price": Decimal("10.00"),
            }
        ],
    }


async def test_create_draft_purchase_and_total(db_session: AsyncSession) -> None:
    catalog = await setup_catalog(db_session)
    purchase = await create_purchase(db_session, purchase_data(catalog))
    assert purchase.status is DocumentStatus.DRAFT
    assert purchase.total_amount == Decimal("25.00")
    assert await db_session.scalar(select(func.count()).select_from(InventoryTransaction)) == 0
    assert await db_session.scalar(select(func.count()).select_from(SupplierLedger)) == 0


async def test_multi_item_purchase_detail_and_list_search(db_session: AsyncSession) -> None:
    catalog = await setup_catalog(db_session)
    purchase = await create_purchase(
        db_session,
        purchase_data(
            catalog,
            items=[
                {
                    "product_id": catalog["product"].id,
                    "unit_id": catalog["unit"].id,
                    "quantity": Decimal("2"),
                    "unit_price": Decimal("10.00"),
                },
                {
                    "product_id": catalog["other_product"].id,
                    "unit_id": catalog["unit"].id,
                    "quantity": Decimal("3"),
                    "unit_price": Decimal("4.00"),
                },
            ],
        ),
    )
    rows, total = await list_purchases(db_session, offset=0, limit=10, search=purchase.number)
    assert total == 1
    assert len(rows[0].items) == 2
    assert purchase_response(rows[0])["purchase_total"] == Decimal("32.00")


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("quantity", Decimal("0"), "quantities"),
        ("quantity", Decimal("-1"), "greater"),
        ("unit_price", Decimal("-0.01"), "prices"),
    ],
)
async def test_invalid_purchase_values_rejected(
    db_session: AsyncSession, field: str, value: Decimal, message: str
) -> None:
    catalog = await setup_catalog(db_session)
    item = purchase_data(catalog)["items"][0]
    item[field] = value
    with pytest.raises(PurchaseError, match=message):
        await create_purchase(db_session, purchase_data(catalog, items=[item]))


async def test_inactive_supplier_and_warehouse_rejected(db_session: AsyncSession) -> None:
    catalog = await setup_catalog(db_session)
    await update_supplier(db_session, catalog["supplier"].id, {"is_active": False})
    with pytest.raises(PurchaseError, match="inactive"):
        await create_purchase(db_session, purchase_data(catalog))
    catalog["supplier"].is_active = True
    catalog["warehouse"].is_active = False
    with pytest.raises(PurchaseError, match="inactive"):
        await create_purchase(db_session, purchase_data(catalog))


async def test_inactive_product_and_invalid_unit_rejected(db_session: AsyncSession) -> None:
    catalog = await setup_catalog(db_session)
    catalog["product"].is_active = False
    with pytest.raises((PurchaseError, ValueError), match="inactive"):
        await create_purchase(db_session, purchase_data(catalog))

    catalog["product"].is_active = True
    item = purchase_data(catalog)["items"][0]
    item["unit_id"] = catalog["other_unit"].id
    with pytest.raises((PurchaseError, ValueError), match="must use"):
        await create_purchase(db_session, purchase_data(catalog, items=[item]))


async def test_duplicate_product_lines_rejected(db_session: AsyncSession) -> None:
    catalog = await setup_catalog(db_session)
    item = purchase_data(catalog)["items"][0]
    with pytest.raises(PurchaseError, match="duplicate"):
        await create_purchase(db_session, purchase_data(catalog, items=[item, item.copy()]))


async def test_post_purchase_creates_inventory_and_ledger(db_session: AsyncSession) -> None:
    catalog = await setup_catalog(db_session)
    purchase = await create_purchase(db_session, purchase_data(catalog))
    posted = await post_purchase_document(db_session, purchase.id)
    assert posted.status is DocumentStatus.POSTED
    transaction = await db_session.scalar(select(InventoryTransaction))
    ledger = await db_session.scalar(select(SupplierLedger))
    assert transaction is not None
    assert transaction.transaction_type is InventoryTransactionType.PURCHASE_IN
    assert transaction.source_document_type == "PURCHASE"
    assert transaction.source_document_id == purchase.id
    assert ledger is not None
    assert ledger.entry_type is SupplierLedgerEntryType.PURCHASE_DEBIT
    assert ledger.debit_amount == Decimal("25.00")


async def test_double_post_and_posted_mutation_rejected(db_session: AsyncSession) -> None:
    catalog = await setup_catalog(db_session)
    purchase = await create_purchase(db_session, purchase_data(catalog))
    await post_purchase_document(db_session, purchase.id)
    with pytest.raises(PurchaseError, match="Only draft"):
        await post_purchase_document(db_session, purchase.id)
    with pytest.raises(PurchaseError, match="Only draft"):
        await update_purchase(db_session, purchase.id, {"notes": "changed"})


async def test_posting_rollback_keeps_draft_and_events(db_session: AsyncSession) -> None:
    catalog = await setup_catalog(db_session)
    purchase = await create_purchase(db_session, purchase_data(catalog))
    catalog["product"].is_active = False
    with pytest.raises((PurchaseError, ValueError), match="inactive"):
        async with db_session.begin_nested():
            await post_purchase_document(db_session, purchase.id)
    await db_session.refresh(purchase)
    assert purchase.status is DocumentStatus.DRAFT
    assert await db_session.scalar(select(func.count()).select_from(InventoryTransaction)) == 0
    assert await db_session.scalar(select(func.count()).select_from(SupplierLedger)) == 0


async def test_purchase_mutation_is_audited(db_session: AsyncSession) -> None:
    catalog = await setup_catalog(db_session)
    purchase = await create_purchase(db_session, purchase_data(catalog))
    await update_purchase(db_session, purchase.id, {"notes": "updated"})
    audit_count = await db_session.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.entity_id == purchase.id)
    )
    assert audit_count == 2


async def test_purchase_api_create_list_and_detail(db_session: AsyncSession) -> None:
    catalog = await setup_catalog(db_session)

    async def override_session():
        yield db_session

    app.dependency_overrides[get_session] = override_session
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/purchases",
                json={
                    **{
                        "number": "PUR-API-001",
                        "supplier_id": str(catalog["supplier"].id),
                        "warehouse_id": str(catalog["warehouse"].id),
                    },
                    "items": [
                        {
                            "product_id": str(catalog["product"].id),
                            "unit_id": str(catalog["unit"].id),
                            "quantity": "2",
                            "unit_price": "10.00",
                        }
                    ],
                },
            )
            assert response.status_code == 201
            purchase_id = response.json()["id"]
            assert response.json()["purchase_total"] == "20.00"

            listing = await client.get("/api/v1/purchases?limit=1&search=PUR-API")
            assert listing.status_code == 200
            assert listing.json()["total"] == 1

            detail = await client.get(f"/api/v1/purchases/{purchase_id}")
            assert detail.status_code == 200
            assert detail.json()["items"][0]["line_total"] == "20.00"
    finally:
        app.dependency_overrides.pop(get_session, None)
