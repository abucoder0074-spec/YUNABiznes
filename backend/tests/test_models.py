"""Relationship, calculated-value, and database-constraint tests."""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import InventoryTransactionType, PaymentMethod
from app.models.catalogs import Product, Supplier, Unit, Warehouse
from app.models.inventory import InventoryTransaction
from app.models.purchasing import Payment, PaymentAllocation, Purchase, PurchaseItem


async def create_catalog(session: AsyncSession) -> tuple[Unit, Product, Warehouse]:
    unit = Unit(name="Kilogram", symbol="kg")
    warehouse = Warehouse(name="Main warehouse")
    session.add_all([unit, warehouse])
    await session.flush()
    product = Product(name="Sugar", code="SUGAR", unit_id=unit.id)
    session.add(product)
    await session.flush()
    return unit, product, warehouse


async def test_model_creation_and_product_unit_relationship(db_session: AsyncSession) -> None:
    unit, product, _ = await create_catalog(db_session)

    assert product.unit_id == unit.id
    assert product.unit.name == "Kilogram"


async def test_supplier_purchase_relationship(db_session: AsyncSession) -> None:
    _, _, warehouse = await create_catalog(db_session)
    supplier = Supplier(name="Supplier ABC", code="ABC")
    db_session.add(supplier)
    await db_session.flush()
    purchase = Purchase(number="PUR-0001", supplier_id=supplier.id, warehouse_id=warehouse.id)
    db_session.add(purchase)
    await db_session.flush()

    assert purchase.supplier_id == supplier.id
    assert purchase.warehouse_id == warehouse.id


async def test_purchase_item_total_is_database_generated(db_session: AsyncSession) -> None:
    unit, product, warehouse = await create_catalog(db_session)
    supplier = Supplier(name="Supplier ABC")
    db_session.add(supplier)
    await db_session.flush()
    purchase = Purchase(number="PUR-0002", supplier_id=supplier.id, warehouse_id=warehouse.id)
    db_session.add(purchase)
    await db_session.flush()
    item = PurchaseItem(
        purchase=purchase,
        product_id=product.id,
        unit_id=unit.id,
        quantity=Decimal("12.5000"),
        unit_price=Decimal("4.20"),
    )
    db_session.add(item)
    await db_session.flush()
    await db_session.refresh(item)
    await db_session.refresh(purchase, attribute_names=["items"])

    assert item.total == Decimal("52.50")
    assert purchase.total_amount == Decimal("52.50")


async def test_payment_allocation_can_target_a_purchase(db_session: AsyncSession) -> None:
    _, _, warehouse = await create_catalog(db_session)
    supplier = Supplier(name="Supplier ABC")
    db_session.add(supplier)
    await db_session.flush()
    purchase = Purchase(number="PUR-0003", supplier_id=supplier.id, warehouse_id=warehouse.id)
    payment = Payment(
        number="PAY-0001",
        supplier_id=supplier.id,
        amount=Decimal("100.00"),
        method=PaymentMethod.BANK_TRANSFER,
    )
    db_session.add_all([purchase, payment])
    await db_session.flush()
    allocation = PaymentAllocation(payment_id=payment.id, purchase_id=purchase.id, amount=Decimal("60.00"))
    db_session.add(allocation)
    await db_session.flush()

    assert allocation.payment_id == payment.id
    assert allocation.purchase_id == purchase.id


async def test_inventory_transaction_rejects_zero_quantity(db_session: AsyncSession) -> None:
    unit, product, warehouse = await create_catalog(db_session)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                InventoryTransaction(
                    transaction_type=InventoryTransactionType.PURCHASE_IN,
                    product_id=product.id,
                    unit_id=unit.id,
                    warehouse_id=warehouse.id,
                    quantity=Decimal("0"),
                    source_document_type="purchase",
                    source_document_id=uuid4(),
                )
            )
            await db_session.flush()
