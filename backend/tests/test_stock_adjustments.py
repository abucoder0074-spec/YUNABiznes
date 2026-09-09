"""Regression tests for counted stock adjustments."""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import DocumentStatus, InventoryTransactionType
from app.models.catalogs import Product, Unit, Warehouse
from app.models.inventory import InventoryTransaction
from app.repositories.inventory import available_quantity
from app.services.adjustments import StockAdjustmentError, create_adjustment, post_adjustment


async def test_stock_adjustment_reconciles_counted_and_system_quantity(db_session: AsyncSession) -> None:
    unit = Unit(name="Kilogram", symbol="kg")
    warehouse = Warehouse(name="Stock room")
    db_session.add_all([unit, warehouse])
    await db_session.flush()
    product = Product(name="Wheat", unit_id=unit.id)
    db_session.add(product)
    await db_session.flush()

    db_session.add(
        InventoryTransaction(
            transaction_type=InventoryTransactionType.PURCHASE_IN,
            product_id=product.id,
            unit_id=unit.id,
            warehouse_id=warehouse.id,
            quantity=Decimal("10"),
            source_document_type="purchase",
            source_document_id=uuid4(),
            reason="Initial stock",
        )
    )
    await db_session.flush()

    adjustment = await create_adjustment(
        db_session,
        {
            "number": "SA-0001",
            "warehouse_id": warehouse.id,
            "product_id": product.id,
            "unit_id": unit.id,
            "counted_quantity": Decimal("15"),
            "reason": "Physical count",
            "notes": "Reconciled against receipt",
        },
    )

    assert adjustment.status is DocumentStatus.DRAFT
    posted = await post_adjustment(db_session, adjustment.id)
    assert posted.status is DocumentStatus.POSTED
    assert await available_quantity(db_session, product_id=product.id, warehouse_id=warehouse.id) == Decimal("15")

    movement = (await db_session.execute(
        select(InventoryTransaction).where(InventoryTransaction.source_document_type == "STOCK_ADJUSTMENT")
    )).scalar_one()
    assert movement.transaction_type is InventoryTransactionType.ADJUSTMENT_IN
    assert movement.quantity == Decimal("5")


async def test_stock_adjustment_rejects_negative_count(db_session: AsyncSession) -> None:
    unit = Unit(name="Box", symbol="box")
    warehouse = Warehouse(name="Box room")
    db_session.add_all([unit, warehouse])
    await db_session.flush()
    product = Product(name="Boxes", unit_id=unit.id)
    db_session.add(product)
    await db_session.flush()

    with pytest.raises(StockAdjustmentError):
        await create_adjustment(
            db_session,
            {
                "number": "SA-0002",
                "warehouse_id": warehouse.id,
                "product_id": product.id,
                "unit_id": unit.id,
                "counted_quantity": Decimal("-1"),
                "reason": "Bad count",
            },
        )
