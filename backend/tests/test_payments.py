"""Payment, allocation, and supplier debt regression tests."""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import DocumentStatus, PaymentMethod, SupplierLedgerEntryType
from app.models.audit import AuditLog
from app.models.inventory import Return, ReturnItem
from app.models.purchasing import PaymentAllocation, SupplierLedger
from app.services.catalogs import (
    create_product,
    create_supplier,
    create_unit,
    create_warehouse,
    update_supplier,
)
from app.services.payments import (
    PaymentError,
    add_allocation,
    create_payment,
    list_payments,
    payment_allocations,
    post_payment_document,
    purchase_balance,
    supplier_debt,
    update_payment,
)
from app.services.purchases import create_purchase, post_purchase_document


async def setup_payment_catalog(session: AsyncSession) -> dict[str, object]:
    unit = await create_unit(session, {"name": f"kg-{uuid4().hex[:6]}", "symbol": f"k{uuid4().hex[:3]}"})
    product = await create_product(
        session, {"name": f"Cacao-{uuid4().hex[:6]}", "code": f"C-{uuid4().hex[:8]}", "unit_id": unit.id}
    )
    second_product = await create_product(
        session,
        {"name": f"Milk-{uuid4().hex[:6]}", "code": f"M-{uuid4().hex[:8]}", "unit_id": unit.id},
    )
    supplier = await create_supplier(session, {"name": f"Supplier-{uuid4().hex[:6]}"})
    other_supplier = await create_supplier(session, {"name": f"Other-{uuid4().hex[:6]}"})
    warehouse = await create_warehouse(session, {"name": f"Warehouse-{uuid4().hex[:6]}"})
    return locals()


async def create_posted_purchase(
    session: AsyncSession, catalog: dict[str, object], *, supplier_key: str = "supplier", price: str = "40.00"
):
    purchase = await create_purchase(
        session,
        {
            "number": f"PUR-{uuid4().hex[:8]}",
            "supplier_id": catalog[supplier_key].id,
            "warehouse_id": catalog["warehouse"].id,
            "items": [
                {
                    "product_id": catalog["product"].id,
                    "unit_id": catalog["unit"].id,
                    "quantity": Decimal("1"),
                    "unit_price": Decimal(price),
                }
            ],
        },
    )
    return await post_purchase_document(session, purchase.id)


def payment_data(catalog: dict[str, object], amount: str = "100.00") -> dict:
    return {
        "number": f"PAY-{uuid4().hex[:8]}",
        "supplier_id": catalog["supplier"].id,
        "amount": Decimal(amount),
        "method": PaymentMethod.CASH,
    }


async def test_payment_draft_create_list_update_and_unallocated(db_session: AsyncSession) -> None:
    catalog = await setup_payment_catalog(db_session)
    payment = await create_payment(db_session, payment_data(catalog, "100.00"))
    assert payment.status is DocumentStatus.DRAFT
    assert payment.unallocated_amount == Decimal("100.00")
    await update_payment(db_session, payment.id, {"notes": "cash advance"})
    rows, total = await list_payments(db_session, offset=0, limit=10, search=payment.number)
    assert total == 1
    assert rows[0].notes == "cash advance"


async def test_invalid_amount_and_inactive_supplier_rejected(db_session: AsyncSession) -> None:
    catalog = await setup_payment_catalog(db_session)
    with pytest.raises(PaymentError, match="greater than zero"):
        await create_payment(db_session, {**payment_data(catalog), "amount": Decimal("0")})
    await update_supplier(db_session, catalog["supplier"].id, {"is_active": False})
    with pytest.raises(PaymentError, match="inactive"):
        await create_payment(db_session, payment_data(catalog))


async def test_post_payment_creates_credit_ledger_and_audit(db_session: AsyncSession) -> None:
    catalog = await setup_payment_catalog(db_session)
    payment = await create_payment(db_session, payment_data(catalog, "75.00"))
    posted = await post_payment_document(db_session, payment.id)
    assert posted.status is DocumentStatus.POSTED
    assert posted.posted_at is not None
    ledger = await db_session.scalar(select(SupplierLedger).where(SupplierLedger.payment_id == payment.id))
    assert ledger is not None
    assert ledger.entry_type is SupplierLedgerEntryType.PAYMENT_CREDIT
    assert ledger.credit_amount == Decimal("75.00")
    assert await db_session.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.entity_id == payment.id)
    ) == 2


async def test_double_post_and_posted_payment_update_rejected(db_session: AsyncSession) -> None:
    catalog = await setup_payment_catalog(db_session)
    payment = await create_payment(db_session, payment_data(catalog))
    await post_payment_document(db_session, payment.id)
    with pytest.raises(PaymentError, match="Only draft"):
        await post_payment_document(db_session, payment.id)
    with pytest.raises(PaymentError, match="Only draft"):
        await update_payment(db_session, payment.id, {"notes": "tamper"})


async def test_allocate_one_and_multiple_purchases_partial_and_full(
    db_session: AsyncSession,
) -> None:
    catalog = await setup_payment_catalog(db_session)
    first = await create_posted_purchase(db_session, catalog, price="40.00")
    second = await create_posted_purchase(db_session, catalog, price="30.00")
    payment = await create_payment(db_session, payment_data(catalog, "50.00"))
    await add_allocation(db_session, payment.id, {"purchase_id": first.id, "amount": Decimal("40.00")})
    updated = await add_allocation(
        db_session, payment.id, {"purchase_id": second.id, "amount": Decimal("10.00")}
    )
    assert updated.allocated_amount == Decimal("50.00")
    assert updated.unallocated_amount == Decimal("0.00")
    assert len(await payment_allocations(db_session, payment.id)) == 2
    await post_payment_document(db_session, payment.id)
    balance = await purchase_balance(db_session, second.id)
    assert balance["paid_amount"] == Decimal("10.00")
    assert balance["outstanding_amount"] == Decimal("20.00")


async def test_allocation_invariants_rejected(db_session: AsyncSession) -> None:
    catalog = await setup_payment_catalog(db_session)
    purchase = await create_posted_purchase(db_session, catalog, price="40.00")
    payment = await create_payment(db_session, payment_data(catalog, "30.00"))
    with pytest.raises(PaymentError, match="payment amount"):
        await add_allocation(
            db_session, payment.id, {"purchase_id": purchase.id, "amount": Decimal("30.01")}
        )
    await add_allocation(db_session, payment.id, {"purchase_id": purchase.id, "amount": Decimal("30.00")})
    with pytest.raises(PaymentError, match="already has"):
        await add_allocation(
            db_session, payment.id, {"purchase_id": purchase.id, "amount": Decimal("1.00")}
        )
    other = await create_posted_purchase(db_session, catalog, price="10.00")
    with pytest.raises(PaymentError, match="payment amount"):
        await add_allocation(db_session, payment.id, {"purchase_id": other.id, "amount": Decimal("1.00")})


async def test_cross_supplier_draft_purchase_and_posted_allocation_rejected(
    db_session: AsyncSession,
) -> None:
    catalog = await setup_payment_catalog(db_session)
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
                    "quantity": Decimal("1"),
                    "unit_price": Decimal("10.00"),
                }
            ],
        },
    )
    payment = await create_payment(db_session, payment_data(catalog))
    with pytest.raises(PaymentError, match="posted purchase"):
        await add_allocation(db_session, payment.id, {"purchase_id": draft.id, "amount": Decimal("1")})

    other = await create_posted_purchase(
        db_session, catalog, supplier_key="other_supplier", price="10.00"
    )
    with pytest.raises(PaymentError, match="suppliers"):
        await add_allocation(db_session, payment.id, {"purchase_id": other.id, "amount": Decimal("1")})


async def test_posted_allocation_cannot_be_changed_or_added(db_session: AsyncSession) -> None:
    catalog = await setup_payment_catalog(db_session)
    purchase = await create_posted_purchase(db_session, catalog)
    payment = await create_payment(db_session, payment_data(catalog))
    await add_allocation(db_session, payment.id, {"purchase_id": purchase.id, "amount": Decimal("10.00")})
    await post_payment_document(db_session, payment.id)
    with pytest.raises(PaymentError, match="posted payments"):
        await add_allocation(db_session, payment.id, {"purchase_id": purchase.id, "amount": Decimal("1.00")})
    allocation = (await payment_allocations(db_session, payment.id))[0]
    allocation.amount = Decimal("1.00")
    with pytest.raises(ValueError, match="Allocations"):
        await db_session.flush()


async def test_supplier_debt_and_purchase_balance_include_only_posted_documents(
    db_session: AsyncSession,
) -> None:
    catalog = await setup_payment_catalog(db_session)
    purchase = await create_posted_purchase(db_session, catalog, price="40.00")
    draft_payment = await create_payment(db_session, payment_data(catalog, "5.00"))
    posted_payment = await create_payment(db_session, payment_data(catalog, "20.00"))
    await post_payment_document(db_session, posted_payment.id)

    supplier_return = Return(
        number=f"RET-{uuid4().hex[:8]}",
        supplier_id=catalog["supplier"].id,
        warehouse_id=catalog["warehouse"].id,
        status=DocumentStatus.POSTED,
    )
    supplier_return.items = [
        ReturnItem(
            purchase_item_id=purchase.items[0].id,
            product_id=catalog["product"].id,
            unit_id=catalog["unit"].id,
            quantity=Decimal("1"),
            unit_price=Decimal("5.00"),
        )
    ]
    db_session.add(supplier_return)
    await db_session.flush()

    debt = await supplier_debt(db_session, catalog["supplier"].id)
    balance = await purchase_balance(db_session, purchase.id)
    assert draft_payment.status is DocumentStatus.DRAFT
    assert debt == {
        "total_purchases": Decimal("40.00"),
        "total_paid": Decimal("20.00"),
        "total_returns": Decimal("5.00"),
        "outstanding_debt": Decimal("15.00"),
    }
    assert balance["returned_amount"] == Decimal("5.00")
    assert balance["outstanding_amount"] == Decimal("35.00")


async def test_payment_api_create_detail_and_balance(db_session: AsyncSession) -> None:
    import httpx

    from app.db.session import get_session
    from app.main import app

    catalog = await setup_payment_catalog(db_session)

    async def override_session():
        yield db_session

    app.dependency_overrides[get_session] = override_session
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/payments",
                json={
                    "number": "PAY-API-001",
                    "supplier_id": str(catalog["supplier"].id),
                    "amount": "25.00",
                    "method": "CASH",
                },
            )
            assert response.status_code == 201
            payment_id = response.json()["id"]
            detail = await client.get(f"/api/v1/payments/{payment_id}")
            assert detail.status_code == 200
            assert detail.json()["unallocated_amount"] == "25.00"
    finally:
        app.dependency_overrides.pop(get_session, None)


async def test_failed_allocation_rolls_back_without_creating_an_event(
    db_session: AsyncSession,
) -> None:
    catalog = await setup_payment_catalog(db_session)
    purchase = await create_posted_purchase(db_session, catalog, price="20.00")
    payment = await create_payment(db_session, payment_data(catalog, "30.00"))
    with pytest.raises(PaymentError, match="outstanding"):
        async with db_session.begin_nested():
            await add_allocation(
                db_session,
                payment.id,
                {"purchase_id": purchase.id, "amount": Decimal("20.01")},
            )
    assert await db_session.scalar(
        select(func.count()).select_from(PaymentAllocation).where(PaymentAllocation.payment_id == payment.id)
    ) == 0
