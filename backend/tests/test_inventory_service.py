"""Tests for the atomic production-issue stock safeguard."""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import InventoryTransactionType
from app.models.catalogs import Product, Unit, Warehouse
from app.models.inventory import InventoryTransaction
from app.repositories.inventory import available_quantity
from app.services.inventory import (
    InsufficientStockError,
    ProductionIssueLine,
    post_production_issue,
)


async def test_production_issue_cannot_exceed_calculated_stock(db_session: AsyncSession) -> None:
    unit = Unit(name="Kilogram", symbol="kg")
    warehouse = Warehouse(name="Main warehouse")
    db_session.add_all([unit, warehouse])
    await db_session.flush()
    product = Product(name="Cacao", unit_id=unit.id)
    db_session.add(product)
    await db_session.flush()
    db_session.add(
        InventoryTransaction(
            transaction_type=InventoryTransactionType.PURCHASE_IN,
            product_id=product.id,
            unit_id=unit.id,
            warehouse_id=warehouse.id,
            quantity=Decimal("10.0000"),
            source_document_type="purchase",
            source_document_id=uuid4(),
        )
    )
    await db_session.flush()

    with pytest.raises(InsufficientStockError):
        async with db_session.begin_nested():
            await post_production_issue(
                db_session,
                number="ISS-0001",
                warehouse_id=warehouse.id,
                issued_by_user_id=None,
                lines=[ProductionIssueLine(product.id, unit.id, Decimal("10.0001"))],
            )

    assert await available_quantity(db_session, product_id=product.id, warehouse_id=warehouse.id) == Decimal(
        "10.0000"
    )
    movement_count = await db_session.scalar(select(func.count()).select_from(InventoryTransaction))
    assert movement_count == 1
