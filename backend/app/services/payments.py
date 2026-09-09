"""Payment, allocation, and supplier debt services."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import DocumentStatus
from app.models.audit import AuditLog
from app.models.catalogs import Supplier
from app.models.inventory import Return, ReturnItem
from app.models.purchasing import Payment, PaymentAllocation, Purchase, PurchaseItem
from app.repositories.purchasing import purchase_financials
from app.services.purchasing import DocumentPostingError, post_payment

MONEY_ZERO = Decimal("0.00")


class PaymentError(ValueError):
    """Raised when a payment or allocation violates an accounting rule."""


def _money(value: Decimal | int | None) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _clean(value: str | None) -> str | None:
    return value.strip() if value is not None else None


def _audit_value(value: Any) -> Any:
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    return value


async def _load_payment(session: AsyncSession, payment_id: UUID, *, lock: bool = False) -> Payment:
    statement = (
        select(Payment)
        .where(Payment.id == payment_id)
        .options(
            selectinload(Payment.supplier),
            selectinload(Payment.allocations),
        )
    )
    if lock:
        statement = statement.with_for_update()
    statement = statement.execution_options(populate_existing=True)
    payment = (await session.execute(statement)).scalar_one_or_none()
    if payment is None:
        raise PaymentError("Payment not found.")
    return payment


async def _require_active_supplier(session: AsyncSession, supplier_id: UUID) -> None:
    supplier = await session.get(Supplier, supplier_id)
    if supplier is None:
        raise PaymentError("Supplier not found.")
    if not supplier.is_active:
        raise PaymentError("Supplier is inactive and cannot be used.")


async def _audit(
    session: AsyncSession, *, action: str, entity_type: str, entity_id: UUID, values: dict[str, Any]
) -> None:
    session.add(
        AuditLog(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            new_values={key: _audit_value(value) for key, value in values.items()},
        )
    )


async def create_payment(session: AsyncSession, data: dict[str, Any]) -> Payment:
    await _require_active_supplier(session, data["supplier_id"])
    if data["amount"] <= 0:
        raise PaymentError("Payment amount must be greater than zero.")
    data = {
        key: _clean(value) if isinstance(value, str) else value
        for key, value in data.items()
    }
    payment = Payment(**data)
    session.add(payment)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise PaymentError("A payment with the same number already exists.") from exc
    await _audit(
        session,
        action="CREATE",
        entity_type="Payment",
        entity_id=payment.id,
        values={"number": payment.number, "amount": payment.amount},
    )
    return await _load_payment(session, payment.id)


async def list_payments(
    session: AsyncSession, *, offset: int, limit: int, search: str | None
) -> tuple[list[Payment], int]:
    filters = []
    if search:
        filters.append(Payment.number.ilike(f"%{search.strip()}%"))
    total = await session.scalar(select(func.count()).select_from(Payment).where(*filters))
    rows = (
        await session.execute(
            select(Payment)
            .where(*filters)
            .order_by(Payment.created_at.desc(), Payment.id)
            .options(selectinload(Payment.supplier), selectinload(Payment.allocations))
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return rows, int(total or 0)


async def update_payment(
    session: AsyncSession, payment_id: UUID, data: dict[str, Any]
) -> Payment:
    payment = await _load_payment(session, payment_id, lock=True)
    if payment.status is not DocumentStatus.DRAFT:
        raise PaymentError("Only draft payments can be changed.")
    supplier_id = data.get("supplier_id", payment.supplier_id)
    await _require_active_supplier(session, supplier_id)
    for key, value in data.items():
        setattr(payment, key, _clean(value) if isinstance(value, str) else value)
    if payment.amount <= 0:
        raise PaymentError("Payment amount must be greater than zero.")
    if payment.allocated_amount > payment.amount:
        raise PaymentError("Payment allocations cannot exceed the payment amount.")
    await session.flush()
    await _audit(
        session,
        action="UPDATE",
        entity_type="Payment",
        entity_id=payment.id,
        values={"number": payment.number, "amount": payment.amount},
    )
    return await _load_payment(session, payment.id)


async def add_allocation(
    session: AsyncSession, payment_id: UUID, data: dict[str, Any]
) -> Payment:
    payment = await _load_payment(session, payment_id, lock=True)
    if payment.status is DocumentStatus.POSTED:
        raise PaymentError("Allocations cannot be added to posted payments.")
    if payment.status is not DocumentStatus.DRAFT:
        raise PaymentError("Only draft payments can receive allocations.")
    if data["amount"] <= 0:
        raise PaymentError("Allocation amount must be greater than zero.")

    purchase = await session.scalar(
        select(Purchase).where(Purchase.id == data["purchase_id"]).with_for_update()
    )
    if purchase is None:
        raise PaymentError("Purchase not found.")
    if purchase.status is not DocumentStatus.POSTED:
        raise PaymentError("Allocations require a posted purchase.")
    if purchase.supplier_id != payment.supplier_id:
        raise PaymentError("Payment and purchase suppliers must match.")
    if any(allocation.purchase_id == purchase.id for allocation in payment.allocations):
        raise PaymentError("This payment already has an allocation for the purchase.")

    financials = await purchase_financials(session, purchase.id)
    if data["amount"] > financials.outstanding_amount:
        raise PaymentError("Allocation exceeds the purchase outstanding amount.")
    if payment.allocated_amount + data["amount"] > payment.amount:
        raise PaymentError("Payment allocations cannot exceed the payment amount.")

    session.add(
        PaymentAllocation(
            payment_id=payment.id,
            purchase_id=purchase.id,
            amount=data["amount"],
            notes=_clean(data.get("notes")),
        )
    )
    await session.flush()
    await _audit(
        session,
        action="ALLOCATE",
        entity_type="Payment",
        entity_id=payment.id,
        values={"purchase_id": purchase.id, "amount": data["amount"]},
    )
    return await _load_payment(session, payment.id)


async def post_payment_document(session: AsyncSession, payment_id: UUID) -> Payment:
    try:
        payment = await post_payment(session, payment_id=payment_id)
    except (DocumentPostingError, ValueError) as exc:
        raise PaymentError(str(exc)) from exc
    return await _load_payment(session, payment.id)


async def payment_allocations(session: AsyncSession, payment_id: UUID) -> list[PaymentAllocation]:
    payment = await _load_payment(session, payment_id)
    return payment.allocations


async def purchase_balance(session: AsyncSession, purchase_id: UUID) -> dict[str, Decimal]:
    purchase = await session.get(Purchase, purchase_id)
    if purchase is None:
        raise PaymentError("Purchase not found.")
    financials = await purchase_financials(session, purchase_id)
    return {
        "purchase_total": _money(financials.gross_amount),
        "paid_amount": _money(financials.allocated_amount),
        "returned_amount": _money(financials.returned_amount),
        "outstanding_amount": _money(financials.outstanding_amount),
    }


async def supplier_debt(session: AsyncSession, supplier_id: UUID) -> dict[str, Decimal]:
    supplier = await session.get(Supplier, supplier_id)
    if supplier is None:
        raise PaymentError("Supplier not found.")
    total_purchases = await session.scalar(
        select(func.coalesce(func.sum(PurchaseItem.total), MONEY_ZERO))
        .join(Purchase, Purchase.id == PurchaseItem.purchase_id)
        .where(Purchase.supplier_id == supplier_id, Purchase.status == DocumentStatus.POSTED)
    )
    total_paid = await session.scalar(
        select(func.coalesce(func.sum(Payment.amount), MONEY_ZERO)).where(
            Payment.supplier_id == supplier_id, Payment.status == DocumentStatus.POSTED
        )
    )
    total_returns = await session.scalar(
        select(func.coalesce(func.sum(ReturnItem.total), MONEY_ZERO))
        .join(Return, Return.id == ReturnItem.return_id)
        .where(Return.supplier_id == supplier_id, Return.status == DocumentStatus.POSTED)
    )
    purchases = _money(total_purchases)
    paid = _money(total_paid)
    returns = _money(total_returns)
    return {
        "total_purchases": purchases,
        "total_paid": paid,
        "total_returns": returns,
        "outstanding_debt": _money(purchases - paid - returns),
    }


def payment_response(payment: Payment) -> dict[str, Any]:
    allocated = _money(payment.allocated_amount)
    return {
        "id": payment.id,
        "number": payment.number,
        "supplier_id": payment.supplier_id,
        "supplier_name": payment.supplier.name,
        "paid_at": payment.paid_at,
        "amount": payment.amount,
        "method": payment.method,
        "status": payment.status,
        "reference_number": payment.reference_number,
        "notes": payment.notes,
        "allocated_amount": allocated,
        "unallocated_amount": _money(payment.amount - allocated),
        "allocations": payment.allocations,
        "created_at": payment.created_at,
        "posted_at": getattr(payment, "posted_at", None),
    }
