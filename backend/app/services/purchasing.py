"""Atomic posting workflows for purchases, supplier payments, and returns."""

from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import DocumentStatus, InventoryTransactionType, SupplierLedgerEntryType
from app.models.audit import AuditLog
from app.models.inventory import InventoryTransaction, Return, ReturnItem
from app.models.purchasing import Payment, PaymentAllocation, Purchase, PurchaseItem, SupplierLedger
from app.repositories.inventory import available_quantity, lock_inventory_position
from app.repositories.purchasing import (
    purchase_financials,
    purchase_item_returned_quantity,
)
from app.services.validation import validate_active_supplier_warehouse, validate_product_units


class DocumentPostingError(ValueError):
    """Raised when a draft document cannot be safely finalized."""


class PaymentAllocationError(DocumentPostingError):
    """Raised for an allocation that would make payment or purchase balances invalid."""


class SupplierReturnError(DocumentPostingError):
    """Raised when a supplier return is not traceable or cannot leave inventory."""


async def _lock_purchase_rows(session: AsyncSession, purchase_ids: set[UUID]) -> dict[UUID, Purchase]:
    if not purchase_ids:
        return {}
    purchases = (
        await session.execute(
            select(Purchase)
            .where(Purchase.id.in_(purchase_ids))
            .order_by(Purchase.id)
            .with_for_update()
        )
    ).scalars().all()
    if len(purchases) != len(purchase_ids):
        raise DocumentPostingError("A referenced purchase no longer exists.")
    return {purchase.id: purchase for purchase in purchases}


async def _assert_no_ledger_event(
    session: AsyncSession, *, source_document_type: str, source_document_id: UUID
) -> None:
    existing = await session.scalar(
        select(func.count())
        .select_from(SupplierLedger)
        .where(
            SupplierLedger.source_document_type == source_document_type,
            SupplierLedger.source_document_id == source_document_id,
        )
    )
    if existing:
        raise DocumentPostingError("This document already has an immutable supplier ledger event.")


async def post_purchase(session: AsyncSession, *, purchase_id: UUID) -> Purchase:
    """Finalize a draft purchase, creating its inventory and payable events atomically."""

    purchase = await session.scalar(
        select(Purchase).where(Purchase.id == purchase_id).with_for_update()
    )
    if purchase is None:
        raise DocumentPostingError("Purchase not found.")
    if purchase.status is not DocumentStatus.DRAFT:
        raise DocumentPostingError("Only draft purchases can be posted.")
    await validate_active_supplier_warehouse(
        session, supplier_id=purchase.supplier_id, warehouse_id=purchase.warehouse_id
    )
    await _assert_no_ledger_event(
        session, source_document_type="PURCHASE", source_document_id=purchase.id
    )
    items = (
        await session.execute(
            select(PurchaseItem).where(PurchaseItem.purchase_id == purchase.id).order_by(PurchaseItem.id)
        )
    ).scalars().all()
    if not items:
        raise DocumentPostingError("A purchase requires at least one item.")
    product_ids = [item.product_id for item in items]
    if len(set(product_ids)) != len(product_ids):
        raise DocumentPostingError("A purchase cannot contain duplicate product lines.")
    for item in items:
        if item.quantity <= 0:
            raise DocumentPostingError("Purchase quantities must be greater than zero.")
        if item.unit_price < 0:
            raise DocumentPostingError("Purchase unit prices cannot be negative.")

    await validate_product_units(session, ((item.product_id, item.unit_id) for item in items))
    positions = {(item.product_id, item.unit_id) for item in items}
    for product_id, _ in sorted(positions, key=lambda position: str(position[0])):
        await lock_inventory_position(
            session, product_id=product_id, warehouse_id=purchase.warehouse_id
        )

    posted_at = datetime.now(UTC)
    for item in items:
        session.add(
            InventoryTransaction(
                transaction_type=InventoryTransactionType.PURCHASE_IN,
                product_id=item.product_id,
                unit_id=item.unit_id,
                warehouse_id=purchase.warehouse_id,
                quantity=item.quantity,
                occurred_at=posted_at,
                source_document_type="PURCHASE",
                source_document_id=purchase.id,
                performed_by_user_id=purchase.created_by_user_id,
                note=item.notes,
            )
        )

    await session.flush()
    gross_amount = (
        await session.execute(
            select(func.coalesce(func.sum(PurchaseItem.total), Decimal("0.00"))).where(
                PurchaseItem.purchase_id == purchase.id
            )
        )
    ).scalar_one()
    if gross_amount > 0:
        session.add(
            SupplierLedger(
                supplier_id=purchase.supplier_id,
                entry_type=SupplierLedgerEntryType.PURCHASE_DEBIT,
                debit_amount=gross_amount,
                credit_amount=Decimal("0.00"),
                currency=purchase.currency,
                occurred_at=posted_at,
                purchase_id=purchase.id,
                source_document_type="PURCHASE",
                source_document_id=purchase.id,
                created_by_user_id=purchase.created_by_user_id,
            )
        )

    purchase.status = DocumentStatus.POSTED
    purchase.posted_at = posted_at
    session.add(
        AuditLog(
            actor_user_id=purchase.created_by_user_id,
            action="POST",
            entity_type="purchase",
            entity_id=purchase.id,
            new_values={"number": purchase.number, "item_count": len(items), "gross_amount": str(gross_amount)},
        )
    )
    return purchase


async def post_payment(session: AsyncSession, *, payment_id: UUID) -> Payment:
    """Finalize a supplier payment after validating all direct purchase allocations."""

    payment = await session.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
    if payment is None:
        raise DocumentPostingError("Payment not found.")
    if payment.status is not DocumentStatus.DRAFT:
        raise DocumentPostingError("Only draft payments can be posted.")
    await validate_active_supplier_warehouse(session, supplier_id=payment.supplier_id)
    await _assert_no_ledger_event(session, source_document_type="payment", source_document_id=payment.id)
    allocations = (
        await session.execute(
            select(PaymentAllocation)
            .where(PaymentAllocation.payment_id == payment.id)
            .order_by(PaymentAllocation.id)
        )
    ).scalars().all()
    allocated_amount = sum((allocation.amount for allocation in allocations), Decimal("0.00"))
    if allocated_amount > payment.amount:
        raise PaymentAllocationError("Payment allocations cannot exceed the payment amount.")

    requested_by_purchase: dict[UUID, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for allocation in allocations:
        if allocation.purchase_id is not None:
            requested_by_purchase[allocation.purchase_id] += allocation.amount
    purchases = await _lock_purchase_rows(session, set(requested_by_purchase))
    for purchase_id, requested_amount in requested_by_purchase.items():
        purchase = purchases[purchase_id]
        if purchase.status is not DocumentStatus.POSTED:
            raise PaymentAllocationError("Payments can only be allocated to posted purchases.")
        if purchase.supplier_id != payment.supplier_id:
            raise PaymentAllocationError("A payment can only be allocated to the same supplier's purchase.")
        financials = await purchase_financials(session, purchase_id)
        if requested_amount > financials.outstanding_amount:
            raise PaymentAllocationError("Payment allocations cannot exceed a purchase's outstanding amount.")

    posted_at = datetime.now(UTC)
    session.add(
        SupplierLedger(
            supplier_id=payment.supplier_id,
            entry_type=SupplierLedgerEntryType.PAYMENT_CREDIT,
            debit_amount=Decimal("0.00"),
            credit_amount=payment.amount,
            occurred_at=posted_at,
            payment_id=payment.id,
            source_document_type="payment",
            source_document_id=payment.id,
            created_by_user_id=payment.created_by_user_id,
        )
    )
    await session.flush()
    payment.status = DocumentStatus.POSTED
    payment.posted_at = posted_at
    session.add(
        AuditLog(
            actor_user_id=payment.created_by_user_id,
            action="POST",
            entity_type="payment",
            entity_id=payment.id,
            new_values={
                "number": payment.number,
                "amount": str(payment.amount),
                "allocated_amount": str(allocated_amount),
            },
        )
    )
    return payment


async def post_supplier_return(session: AsyncSession, *, return_id: UUID) -> Return:
    """Finalize a supplier return, reducing stock and the supplier payable together."""

    return_document = await session.scalar(
        select(Return).where(Return.id == return_id).with_for_update()
    )
    if return_document is None:
        raise SupplierReturnError("Supplier return not found.")
    if return_document.status is not DocumentStatus.DRAFT:
        raise SupplierReturnError("Only draft supplier returns can be posted.")
    await validate_active_supplier_warehouse(
        session, supplier_id=return_document.supplier_id, warehouse_id=return_document.warehouse_id
    )
    await _assert_no_ledger_event(
        session, source_document_type="supplier_return", source_document_id=return_document.id
    )
    items = (
        await session.execute(
            select(ReturnItem).where(ReturnItem.return_id == return_document.id).order_by(ReturnItem.id)
        )
    ).scalars().all()
    if not items:
        raise SupplierReturnError("A supplier return requires at least one item.")
    await validate_product_units(session, ((item.product_id, item.unit_id) for item in items))

    source_item_ids = {item.purchase_item_id for item in items if item.purchase_item_id is not None}
    source_rows = (
        await session.execute(
            select(PurchaseItem, Purchase)
            .join(Purchase, Purchase.id == PurchaseItem.purchase_id)
            .where(PurchaseItem.id.in_(source_item_ids))
            .order_by(PurchaseItem.id)
            .with_for_update()
        )
    ).all() if source_item_ids else []
    sources = {purchase_item.id: (purchase_item, purchase) for purchase_item, purchase in source_rows}
    if len(sources) != len(source_item_ids):
        raise SupplierReturnError("A referenced purchase item no longer exists.")
    await _lock_purchase_rows(session, {purchase.id for _, purchase in source_rows})

    requested_returns: dict[UUID, Decimal] = defaultdict(lambda: Decimal("0"))
    for item in items:
        if item.purchase_item_id is None:
            raise SupplierReturnError("Every supplier return item must reference its purchase item.")
        purchase_item, purchase = sources[item.purchase_item_id]
        if purchase.status is not DocumentStatus.POSTED:
            raise SupplierReturnError("Supplier returns must reference posted purchases.")
        if purchase.supplier_id != return_document.supplier_id:
            raise SupplierReturnError("A return item must belong to the selected supplier.")
        if purchase_item.product_id != item.product_id or purchase_item.unit_id != item.unit_id:
            raise SupplierReturnError("A return item must match its original purchased product and unit.")
        if purchase.warehouse_id != return_document.warehouse_id:
            raise SupplierReturnError("A return must use the original purchase warehouse.")
        if item.unit_price != purchase_item.unit_price:
            raise SupplierReturnError("A return item price must match its original purchase price.")
        requested_returns[purchase_item.id] += item.quantity

    for purchase_item_id, requested_quantity in requested_returns.items():
        purchase_item, _ = sources[purchase_item_id]
        returned_quantity = await purchase_item_returned_quantity(session, purchase_item_id)
        if returned_quantity + requested_quantity > purchase_item.quantity:
            raise SupplierReturnError("Return quantity cannot exceed the original purchased quantity.")

    positions = {(item.product_id, item.unit_id) for item in items}
    for product_id, _ in sorted(positions, key=lambda position: str(position[0])):
        await lock_inventory_position(
            session, product_id=product_id, warehouse_id=return_document.warehouse_id
        )
    requested_stock: dict[UUID, Decimal] = defaultdict(lambda: Decimal("0"))
    for item in items:
        requested_stock[item.product_id] += item.quantity
    for product_id, quantity in requested_stock.items():
        available = await available_quantity(
            session, product_id=product_id, warehouse_id=return_document.warehouse_id
        )
        if available < quantity:
            raise SupplierReturnError("Supplier return cannot exceed the available warehouse stock.")

    posted_at = datetime.now(UTC)
    for item in items:
        session.add(
            InventoryTransaction(
                transaction_type=InventoryTransactionType.SUPPLIER_RETURN_OUT,
                product_id=item.product_id,
                unit_id=item.unit_id,
                warehouse_id=return_document.warehouse_id,
                quantity=item.quantity,
                occurred_at=posted_at,
                source_document_type="supplier_return",
                source_document_id=return_document.id,
                performed_by_user_id=return_document.authorized_by_user_id,
                note=item.notes,
            )
        )
    await session.flush()
    return_total = (
        await session.execute(
            select(func.coalesce(func.sum(ReturnItem.total), Decimal("0.00"))).where(
                ReturnItem.return_id == return_document.id
            )
        )
    ).scalar_one()
    if return_total > 0:
        session.add(
            SupplierLedger(
                supplier_id=return_document.supplier_id,
                entry_type=SupplierLedgerEntryType.RETURN_CREDIT,
                debit_amount=Decimal("0.00"),
                credit_amount=return_total,
                occurred_at=posted_at,
                return_id=return_document.id,
                source_document_type="supplier_return",
                source_document_id=return_document.id,
                created_by_user_id=return_document.authorized_by_user_id,
            )
        )
    return_document.status = DocumentStatus.POSTED
    return_document.posted_at = posted_at
    session.add(
        AuditLog(
            actor_user_id=return_document.authorized_by_user_id,
            action="POST",
            entity_type="supplier_return",
            entity_id=return_document.id,
            new_values={
                "number": return_document.number,
                "item_count": len(items),
                "total": str(return_total),
            },
        )
    )
    return return_document
