"""End-to-end posting flows: purchase -> stock/payable, supplier return, immutability."""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import InventoryTransactionType
from app.models.catalogs import Product, Supplier, Unit, Warehouse
from app.models.inventory import InventoryTransaction, Return, ReturnItem
from app.models.purchasing import Purchase, PurchaseItem
from app.repositories.inventory import available_quantity
from app.repositories.purchasing import purchase_financials, supplier_payable
from app.services.purchasing import SupplierReturnError, post_purchase, post_supplier_return


async def _posted_purchase(session: AsyncSession):
    unit = Unit(name="Kilogram", symbol="kg")
    warehouse = Warehouse(name="Main")
    supplier = Supplier(name="Supplier")
    session.add_all([unit, warehouse, supplier])
    await session.flush()
    product = Product(name="Milk powder", unit_id=unit.id)
    session.add(product)
    await session.flush()
    purchase = Purchase(number=f"P-{uuid4().hex[:6]}", supplier_id=supplier.id, warehouse_id=warehouse.id)
    item = PurchaseItem(
        purchase=purchase,
        product_id=product.id,
        unit_id=unit.id,
        quantity=Decimal("10"),
        unit_price=Decimal("5.00"),
    )
    session.add_all([purchase, item])
    await session.flush()
    await post_purchase(session, purchase_id=purchase.id)
    return unit, product, warehouse, supplier, purchase, item


async def test_post_purchase_creates_stock_and_payable(db_session: AsyncSession) -> None:
    _, product, warehouse, supplier, purchase, _ = await _posted_purchase(db_session)

    assert await available_quantity(db_session, product_id=product.id, warehouse_id=warehouse.id) == Decimal("10")
    assert await supplier_payable(db_session, supplier.id) == Decimal("50.00")
    financials = await purchase_financials(db_session, purchase.id)
    assert financials.outstanding_amount == Decimal("50.00")


async def test_supplier_return_reduces_stock_and_payable(db_session: AsyncSession) -> None:
    unit, product, warehouse, supplier, purchase, item = await _posted_purchase(db_session)
    document = Return(number="R-1", supplier_id=supplier.id, warehouse_id=warehouse.id)
    line = ReturnItem(
        return_document=document,
        purchase_item_id=item.id,
        product_id=product.id,
        unit_id=unit.id,
        quantity=Decimal("4"),
        unit_price=Decimal("5.00"),
    )
    db_session.add_all([document, line])
    await db_session.flush()

    await post_supplier_return(db_session, return_id=document.id)

    assert await available_quantity(db_session, product_id=product.id, warehouse_id=warehouse.id) == Decimal("6")
    assert await supplier_payable(db_session, supplier.id) == Decimal("30.00")
    assert (await purchase_financials(db_session, purchase.id)).outstanding_amount == Decimal("30.00")


async def test_return_with_changed_price_is_rejected(db_session: AsyncSession) -> None:
    unit, product, warehouse, supplier, _, item = await _posted_purchase(db_session)
    document = Return(number="R-2", supplier_id=supplier.id, warehouse_id=warehouse.id)
    line = ReturnItem(
        return_document=document,
        purchase_item_id=item.id,
        product_id=product.id,
        unit_id=unit.id,
        quantity=Decimal("1"),
        unit_price=Decimal("9.00"),
    )
    db_session.add_all([document, line])
    await db_session.flush()

    with pytest.raises(SupplierReturnError):
        async with db_session.begin_nested():
            await post_supplier_return(db_session, return_id=document.id)


async def test_untraceable_return_is_rejected(db_session: AsyncSession) -> None:
    unit, product, warehouse, supplier, _, _ = await _posted_purchase(db_session)
    document = Return(number="R-3", supplier_id=supplier.id, warehouse_id=warehouse.id)
    line = ReturnItem(
        return_document=document,
        product_id=product.id,
        unit_id=unit.id,
        quantity=Decimal("1"),
        unit_price=Decimal("5.00"),
    )
    db_session.add_all([document, line])
    await db_session.flush()

    with pytest.raises(SupplierReturnError):
        async with db_session.begin_nested():
            await post_supplier_return(db_session, return_id=document.id)


async def test_posted_purchase_items_cannot_change(db_session: AsyncSession) -> None:
    *_, item = await _posted_purchase(db_session)

    item.quantity = Decimal("99")
    with pytest.raises(ValueError, match="draft"):
        await db_session.flush()
    db_session.expire(item)


async def test_adjustment_without_reason_is_rejected(db_session: AsyncSession) -> None:
    unit, product, warehouse, *_ = await _posted_purchase(db_session)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                InventoryTransaction(
                    transaction_type=InventoryTransactionType.ADJUSTMENT_IN,
                    product_id=product.id,
                    unit_id=unit.id,
                    warehouse_id=warehouse.id,
                    quantity=Decimal("1"),
                    source_document_type="adjustment",
                    source_document_id=uuid4(),
                )
            )
            await db_session.flush()
