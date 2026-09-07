"""Financial queries derived from immutable documents and ledger events."""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import DocumentStatus
from app.models.inventory import Return, ReturnItem
from app.models.purchasing import Payment, PaymentAllocation, PurchaseItem, SupplierLedger

ZERO_MONEY = Decimal("0.00")


@dataclass(frozen=True, slots=True)
class PurchaseFinancials:
    gross_amount: Decimal
    returned_amount: Decimal
    allocated_amount: Decimal

    @property
    def outstanding_amount(self) -> Decimal:
        return self.gross_amount - self.returned_amount - self.allocated_amount


async def purchase_financials(session: AsyncSession, purchase_id: UUID) -> PurchaseFinancials:
    """Calculate one posted purchase's payable from its immutable event sources."""

    gross_amount = (
        await session.execute(
            select(func.coalesce(func.sum(PurchaseItem.total), ZERO_MONEY)).where(
                PurchaseItem.purchase_id == purchase_id
            )
        )
    ).scalar_one()
    returned_amount = (
        await session.execute(
            select(func.coalesce(func.sum(ReturnItem.total), ZERO_MONEY))
            .join(Return, Return.id == ReturnItem.return_id)
            .join(PurchaseItem, PurchaseItem.id == ReturnItem.purchase_item_id)
            .where(PurchaseItem.purchase_id == purchase_id, Return.status == DocumentStatus.POSTED)
        )
    ).scalar_one()
    allocated_amount = (
        await session.execute(
            select(func.coalesce(func.sum(PaymentAllocation.amount), ZERO_MONEY))
            .join(Payment, Payment.id == PaymentAllocation.payment_id)
            .where(
                PaymentAllocation.purchase_id == purchase_id,
                Payment.status == DocumentStatus.POSTED,
            )
        )
    ).scalar_one()
    return PurchaseFinancials(
        gross_amount=Decimal(gross_amount),
        returned_amount=Decimal(returned_amount),
        allocated_amount=Decimal(allocated_amount),
    )


async def purchase_item_returned_quantity(session: AsyncSession, purchase_item_id: UUID) -> Decimal:
    """Return quantity already posted against one purchased line."""

    quantity = (
        await session.execute(
            select(func.coalesce(func.sum(ReturnItem.quantity), Decimal("0")))
            .join(Return, Return.id == ReturnItem.return_id)
            .where(
                ReturnItem.purchase_item_id == purchase_item_id,
                Return.status == DocumentStatus.POSTED,
            )
        )
    ).scalar_one()
    return Decimal(quantity)


async def supplier_payable(session: AsyncSession, supplier_id: UUID) -> Decimal:
    """Calculate supplier debt from ledger debits less ledger credits."""

    amount = (
        await session.execute(
            select(
                func.coalesce(
                    func.sum(SupplierLedger.debit_amount - SupplierLedger.credit_amount), ZERO_MONEY
                )
            ).where(SupplierLedger.supplier_id == supplier_id)
        )
    ).scalar_one()
    return Decimal(amount)
