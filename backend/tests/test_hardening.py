"""Hardening regression tests for allocations and posted document immutability."""

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import PaymentMethod
from app.models.catalogs import Product, Supplier, Unit, Warehouse
from app.models.purchasing import Payment, PaymentAllocation, Purchase, PurchaseItem
from app.services.purchasing import PaymentAllocationError, post_payment, post_purchase


async def create_catalog(session: AsyncSession):
    unit = Unit(name="Unit", symbol="u")
    warehouse = Warehouse(name="Main")
    session.add_all([unit, warehouse])
    await session.flush()
    product = Product(name="Item", unit_id=unit.id)
    session.add(product)
    await session.flush()
    return unit, product, warehouse


async def test_payment_over_allocation_rejected(db_session: AsyncSession) -> None:
    unit, product, warehouse = await create_catalog(db_session)
    supplier = Supplier(name="S1")
    db_session.add(supplier)
    await db_session.flush()

    purchase = Purchase(number="P1", supplier_id=supplier.id, warehouse_id=warehouse.id)
    item = PurchaseItem(purchase=purchase, product_id=product.id, unit_id=unit.id, quantity=Decimal("1"), unit_price=Decimal("100.00"))
    db_session.add_all([purchase, item])
    await db_session.flush()
    await post_purchase(db_session, purchase_id=purchase.id)

    payment = Payment(number="PAY1", supplier_id=supplier.id, amount=Decimal("200.00"), method=PaymentMethod.CASH)
    db_session.add(payment)
    await db_session.flush()

    # Create allocations that sum to more than the payment amount
    a1 = PaymentAllocation(payment_id=payment.id, purchase_id=purchase.id, amount=Decimal("150.00"))
    a2 = PaymentAllocation(payment_id=payment.id, purchase_id=purchase.id, amount=Decimal("60.00"))
    db_session.add_all([a1, a2])
    await db_session.flush()

    with pytest.raises(PaymentAllocationError):
        async with db_session.begin_nested():
            await post_payment(db_session, payment_id=payment.id)


async def test_purchase_over_allocation_rejected(db_session: AsyncSession) -> None:
    unit, product, warehouse = await create_catalog(db_session)
    supplier = Supplier(name="S2")
    db_session.add(supplier)
    await db_session.flush()

    purchase = Purchase(number="P2", supplier_id=supplier.id, warehouse_id=warehouse.id)
    item = PurchaseItem(purchase=purchase, product_id=product.id, unit_id=unit.id, quantity=Decimal("4"), unit_price=Decimal("100.00"))
    db_session.add_all([purchase, item])
    await db_session.flush()
    await post_purchase(db_session, purchase_id=purchase.id)

    # First payment covers 300
    p1 = Payment(number="PAY2", supplier_id=supplier.id, amount=Decimal("300.00"), method=PaymentMethod.CASH)
    db_session.add(p1)
    await db_session.flush()
    db_session.add(PaymentAllocation(payment_id=p1.id, purchase_id=purchase.id, amount=Decimal("300.00")))
    await db_session.flush()
    await post_payment(db_session, payment_id=p1.id)

    # Second payment attempts to allocate 200 more but only 100 outstanding remains
    p2 = Payment(number="PAY3", supplier_id=supplier.id, amount=Decimal("200.00"), method=PaymentMethod.CASH)
    db_session.add(p2)
    await db_session.flush()
    db_session.add(PaymentAllocation(payment_id=p2.id, purchase_id=purchase.id, amount=Decimal("200.00")))
    await db_session.flush()

    with pytest.raises(PaymentAllocationError):
        async with db_session.begin_nested():
            await post_payment(db_session, payment_id=p2.id)


async def test_cross_supplier_allocation_rejected(db_session: AsyncSession) -> None:
    unit, product, warehouse = await create_catalog(db_session)
    s1 = Supplier(name="A")
    s2 = Supplier(name="B")
    db_session.add_all([s1, s2])
    await db_session.flush()

    purchase = Purchase(number="PX", supplier_id=s2.id, warehouse_id=warehouse.id)
    item = PurchaseItem(purchase=purchase, product_id=product.id, unit_id=unit.id, quantity=Decimal("1"), unit_price=Decimal("50.00"))
    db_session.add_all([purchase, item])
    await db_session.flush()
    await post_purchase(db_session, purchase_id=purchase.id)

    payment = Payment(number="PAYX", supplier_id=s1.id, amount=Decimal("100.00"), method=PaymentMethod.CASH)
    db_session.add(payment)
    await db_session.flush()
    db_session.add(PaymentAllocation(payment_id=payment.id, purchase_id=purchase.id, amount=Decimal("50.00")))
    await db_session.flush()

    with pytest.raises(PaymentAllocationError):
        async with db_session.begin_nested():
            await post_payment(db_session, payment_id=payment.id)


async def test_posted_purchase_is_mutable_demonstrates_risk(db_session: AsyncSession) -> None:
    """Demonstrate that posted documents are currently mutable (risk)."""
    unit, product, warehouse = await create_catalog(db_session)
    supplier = Supplier(name="Smut")
    db_session.add(supplier)
    await db_session.flush()

    purchase = Purchase(number="PMUT", supplier_id=supplier.id, warehouse_id=warehouse.id)
    item = PurchaseItem(purchase=purchase, product_id=product.id, unit_id=unit.id, quantity=Decimal("1"), unit_price=Decimal("10.00"))
    db_session.add_all([purchase, item])
    await db_session.flush()
    await post_purchase(db_session, purchase_id=purchase.id)

    # Attempt to modify a posted purchase; currently the DB/model allows it (no DB trigger)
    new_supplier = Supplier(name="Other")
    db_session.add(new_supplier)
    await db_session.flush()
    purchase.supplier_id = new_supplier.id
    await db_session.flush()

    await db_session.refresh(purchase)
    assert purchase.supplier_id == new_supplier.id
