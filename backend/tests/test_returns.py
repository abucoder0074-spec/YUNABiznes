"""Supplier return workflow regression tests."""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import DocumentStatus, InventoryTransactionType, SupplierLedgerEntryType
from app.models.audit import AuditLog
from app.models.inventory import InventoryTransaction
from app.models.purchasing import SupplierLedger
from app.services.catalogs import (
    create_product,
    create_supplier,
    create_unit,
    create_warehouse,
    update_product,
)
from app.services.purchases import create_purchase, post_purchase_document
from app.services.returns import (
    ReturnError,
    create_return,
    list_returns,
    post_return_document,
    update_return,
)


async def setup_return_catalog(session: AsyncSession) -> dict[str, object]:
    unit = await create_unit(session, {"name": f"kg-{uuid4().hex[:6]}", "symbol": f"k{uuid4().hex[:3]}"})
    other_unit = await create_unit(
        session, {"name": f"piece-{uuid4().hex[:6]}", "symbol": f"p{uuid4().hex[:3]}"}
    )
    product = await create_product(
        session, {"name": f"Sugar-{uuid4().hex[:6]}", "code": f"S-{uuid4().hex[:8]}", "unit_id": unit.id}
    )
    other_product = await create_product(
        session, {"name": f"Flour-{uuid4().hex[:6]}", "code": f"F-{uuid4().hex[:8]}", "unit_id": unit.id}
    )
    supplier = await create_supplier(session, {"name": f"Supplier-{uuid4().hex[:6]}"})
    other_supplier = await create_supplier(session, {"name": f"Other-{uuid4().hex[:6]}"})
    warehouse = await create_warehouse(session, {"name": f"Warehouse-{uuid4().hex[:6]}"})
    other_warehouse = await create_warehouse(session, {"name": f"Other-Warehouse-{uuid4().hex[:6]}"})
    return locals()


async def create_purchase_for_return(
    session: AsyncSession, catalog: dict[str, object], *, quantity: str = "10", price: str = "8.00"
):
    purchase = await create_purchase(
        session,
        {
            "number": f"PUR-{uuid4().hex[:8]}",
            "supplier_id": catalog["supplier"].id,
            "warehouse_id": catalog["warehouse"].id,
            "items": [
                {
                    "product_id": catalog["product"].id,
                    "unit_id": catalog["unit"].id,
                    "quantity": Decimal(quantity),
                    "unit_price": Decimal(price),
                }
            ],
        },
    )
    return await post_purchase_document(session, purchase.id)


def return_data(catalog: dict[str, object], purchase, *, quantity: str = "2", price: str = "8.00"):
    item = purchase.items[0]
    return {
        "number": f"RET-{uuid4().hex[:8]}",
        "supplier_id": catalog["supplier"].id,
        "warehouse_id": catalog["warehouse"].id,
        "items": [
            {
                "purchase_item_id": item.id,
                "product_id": catalog["product"].id,
                "unit_id": catalog["unit"].id,
                "quantity": Decimal(quantity),
                "unit_price": Decimal(price),
            }
        ],
    }


async def test_create_list_update_draft_return(db_session: AsyncSession) -> None:
    catalog = await setup_return_catalog(db_session)
    purchase = await create_purchase_for_return(db_session, catalog)
    document = await create_return(db_session, return_data(catalog, purchase))
    assert document.status is DocumentStatus.DRAFT
    assert document.total_amount == Decimal("16.00")
    await update_return(db_session, document.id, {"notes": "supplier credit"})
    rows, total = await list_returns(db_session, offset=0, limit=10, search=document.number)
    assert total == 1
    assert rows[0].notes == "supplier credit"


async def test_draft_purchase_and_invalid_return_values_rejected(db_session: AsyncSession) -> None:
    catalog = await setup_return_catalog(db_session)
    draft = await create_purchase(
        db_session,
        {
            "number": f"PUR-{uuid4().hex[:8]}",
            "supplier_id": catalog["supplier"].id,
            "warehouse_id": catalog["warehouse"].id,
            "items": [
                {
                    "product_id": catalog["product"].id,
                    "unit_id": catalog["unit"].id,
                    "quantity": Decimal("5"),
                    "unit_price": Decimal("8"),
                }
            ],
        },
    )
    with pytest.raises(ReturnError, match="posted purchases"):
        await create_return(db_session, return_data(catalog, draft))

    purchase = await create_purchase_for_return(db_session, catalog)
    with pytest.raises(ReturnError, match="remaining"):
        await create_return(db_session, return_data(catalog, purchase, quantity="11"))
    with pytest.raises(ReturnError, match="price"):
        await create_return(db_session, return_data(catalog, purchase, price="1"))


@pytest.mark.parametrize(
    "field,message",
    [
        ("supplier_id", "supplier"),
        ("warehouse_id", "warehouse"),
        ("product_id", "product"),
        ("unit_id", "unit"),
    ],
)
async def test_return_source_consistency_rejected(
    db_session: AsyncSession, field: str, message: str
) -> None:
    catalog = await setup_return_catalog(db_session)
    purchase = await create_purchase_for_return(db_session, catalog)
    data = return_data(catalog, purchase)
    if field == "supplier_id":
        data[field] = catalog["other_supplier"].id
    elif field == "warehouse_id":
        data[field] = catalog["other_warehouse"].id
    elif field == "product_id":
        data["items"][0][field] = catalog["other_product"].id
    else:
        data["items"][0][field] = catalog["other_unit"].id
    with pytest.raises(ReturnError, match=message):
        await create_return(db_session, data)


async def test_post_return_creates_inventory_credit_and_audit(db_session: AsyncSession) -> None:
    catalog = await setup_return_catalog(db_session)
    purchase = await create_purchase_for_return(db_session, catalog)
    document = await create_return(db_session, return_data(catalog, purchase, quantity="2"))
    posted = await post_return_document(db_session, document.id)
    assert posted.status is DocumentStatus.POSTED
    transaction = await db_session.scalar(
        select(InventoryTransaction).where(InventoryTransaction.source_document_id == document.id)
    )
    ledger = await db_session.scalar(select(SupplierLedger).where(SupplierLedger.return_id == document.id))
    assert transaction is not None
    assert transaction.transaction_type is InventoryTransactionType.SUPPLIER_RETURN_OUT
    assert transaction.quantity == Decimal("2")
    assert ledger is not None
    assert ledger.entry_type is SupplierLedgerEntryType.RETURN_CREDIT
    assert ledger.credit_amount == Decimal("16.00")
    assert await db_session.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.entity_id == document.id)
    ) == 2


async def test_partial_returns_and_remaining_quantity(db_session: AsyncSession) -> None:
    catalog = await setup_return_catalog(db_session)
    purchase = await create_purchase_for_return(db_session, catalog, quantity="10")
    first = await create_return(db_session, return_data(catalog, purchase, quantity="4"))
    await post_return_document(db_session, first.id)
    second = await create_return(db_session, return_data(catalog, purchase, quantity="6"))
    await post_return_document(db_session, second.id)
    with pytest.raises(ReturnError, match="remaining"):
        await create_return(db_session, return_data(catalog, purchase, quantity="1"))


async def test_return_stock_failure_rolls_back_and_posted_return_is_immutable(
    db_session: AsyncSession,
) -> None:
    catalog = await setup_return_catalog(db_session)
    purchase = await create_purchase_for_return(db_session, catalog, quantity="2")
    document = await create_return(db_session, return_data(catalog, purchase, quantity="1"))
    await update_product(db_session, catalog["product"].id, {"is_active": False})
    with pytest.raises(ReturnError, match="inactive"):
        async with db_session.begin_nested():
            await post_return_document(db_session, document.id)
    await db_session.refresh(document)
    assert document.status is DocumentStatus.DRAFT
    assert await db_session.scalar(
        select(func.count()).select_from(SupplierLedger).where(SupplierLedger.return_id == document.id)
    ) == 0

    catalog["product"].is_active = True
    await post_return_document(db_session, document.id)
    with pytest.raises(ReturnError, match="Only draft"):
        await post_return_document(db_session, document.id)
    item = document.items[0]
    item.quantity = Decimal("2")
    with pytest.raises(ValueError, match="Items"):
        await db_session.flush()
