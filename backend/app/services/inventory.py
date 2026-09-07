"""Atomic posting foundation for production issue documents."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import DocumentStatus, InventoryTransactionType
from app.models.audit import AuditLog
from app.models.inventory import InventoryTransaction, ProductionIssue, ProductionIssueItem
from app.repositories.inventory import available_quantity, lock_inventory_position
from app.services.validation import validate_product_units


class InsufficientStockError(ValueError):
    """Raised before any production-out transaction is persisted."""


@dataclass(frozen=True, slots=True)
class ProductionIssueLine:
    product_id: UUID
    unit_id: UUID
    quantity: Decimal
    notes: str | None = None


async def post_production_issue(
    session: AsyncSession,
    *,
    number: str,
    warehouse_id: UUID,
    issued_by_user_id: UUID | None,
    lines: list[ProductionIssueLine],
    notes: str | None = None,
) -> ProductionIssue:
    """Create an issue and its stock events atomically after checking each balance.

    The caller owns the surrounding ``session.begin()`` transaction. PostgreSQL row locks
    serialize concurrent deductions against movements already recorded for the same stock.
    """

    if not lines:
        raise ValueError("A production issue requires at least one item.")
    if any(line.quantity <= 0 for line in lines):
        raise ValueError("Production issue quantities must be greater than zero.")

    await validate_product_units(session, ((line.product_id, line.unit_id) for line in lines))

    requested: dict[tuple[UUID, UUID], Decimal] = {}
    for line in lines:
        key = (line.product_id, line.unit_id)
        requested[key] = requested.get(key, Decimal("0")) + line.quantity

    for product_id, _ in sorted(requested, key=lambda position: str(position[0])):
        await lock_inventory_position(session, product_id=product_id, warehouse_id=warehouse_id)

    for (product_id, _), quantity in requested.items():
        balance = await available_quantity(session, product_id=product_id, warehouse_id=warehouse_id)
        if balance < quantity:
            raise InsufficientStockError(
                f"Insufficient stock for product {product_id}: available {balance}, requested {quantity}."
            )

    issued_at = datetime.now(UTC)
    issue = ProductionIssue(
        number=number,
        warehouse_id=warehouse_id,
        issued_by_user_id=issued_by_user_id,
        issued_at=issued_at,
        status=DocumentStatus.DRAFT,
        notes=notes,
    )
    session.add(issue)
    await session.flush()

    for line in lines:
        session.add(
            ProductionIssueItem(
                production_issue_id=issue.id,
                product_id=line.product_id,
                unit_id=line.unit_id,
                quantity=line.quantity,
                notes=line.notes,
            )
        )
        session.add(
            InventoryTransaction(
                transaction_type=InventoryTransactionType.PRODUCTION_OUT,
                product_id=line.product_id,
                unit_id=line.unit_id,
                warehouse_id=warehouse_id,
                quantity=line.quantity,
                occurred_at=issued_at,
                source_document_type="production_issue",
                source_document_id=issue.id,
                performed_by_user_id=issued_by_user_id,
                note=line.notes,
            )
        )

    await session.flush()
    issue.status = DocumentStatus.POSTED
    issue.posted_at = issued_at
    session.add(
        AuditLog(
            actor_user_id=issued_by_user_id,
            action="POST",
            entity_type="production_issue",
            entity_id=issue.id,
            new_values={"number": number, "line_count": len(lines), "status": DocumentStatus.POSTED.value},
        )
    )
    return issue
