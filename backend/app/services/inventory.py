"""Atomic posting foundation for production issue documents."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import DocumentStatus, InventoryTransactionType
from app.models.audit import AuditLog
from app.models.catalogs import Unit
from app.models.inventory import InventoryTransaction, ProductionIssue, ProductionIssueItem
from app.repositories.inventory import available_quantity, lock_inventory_position
from app.services.validation import validate_active_supplier_warehouse, validate_product_units


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

    await validate_active_supplier_warehouse(session, warehouse_id=warehouse_id)
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

    await session.flush()
    return await post_production_issue_document(session, issue.id)


async def post_production_issue_document(
    session: AsyncSession, issue_id: UUID
) -> ProductionIssue:
    """Post an existing draft issue atomically after locking its source rows."""

    issue = (
        await session.execute(
            select(ProductionIssue)
            .where(ProductionIssue.id == issue_id)
            .options(selectinload(ProductionIssue.items))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if issue is None:
        raise ValueError("Production issue not found.")
    if issue.status is not DocumentStatus.DRAFT:
        raise ValueError("Only draft production issues can be posted.")
    if not issue.items:
        raise ValueError("A production issue requires at least one item.")

    await validate_active_supplier_warehouse(session, warehouse_id=issue.warehouse_id)
    positions: dict[tuple[UUID, UUID], Decimal] = {}
    for item in issue.items:
        if item.quantity <= 0:
            raise ValueError("Production issue quantities must be greater than zero.")
        key = (item.product_id, item.unit_id)
        positions[key] = positions.get(key, Decimal("0")) + item.quantity
    if len({item.product_id for item in issue.items}) != len(issue.items):
        raise ValueError("A production issue cannot contain duplicate product lines.")
    await validate_product_units(session, positions)
    unit_rows = await session.execute(
        select(Unit.id, Unit.is_active).where(Unit.id.in_({unit_id for _, unit_id in positions}))
    )
    active_units = {unit_id for unit_id, active in unit_rows if active}
    if active_units != {unit_id for _, unit_id in positions}:
        raise ValueError("Production issue items must use active units.")

    for product_id, _ in sorted(positions, key=lambda position: str(position[0])):
        await lock_inventory_position(
            session, product_id=product_id, warehouse_id=issue.warehouse_id
        )
    for (product_id, _), quantity in positions.items():
        available = await available_quantity(
            session, product_id=product_id, warehouse_id=issue.warehouse_id
        )
        if available < quantity:
            raise InsufficientStockError(
                f"Insufficient stock for product {product_id}: available {available}, requested {quantity}."
            )

    posted_at = datetime.now(UTC)
    for item in issue.items:
        session.add(
            InventoryTransaction(
                transaction_type=InventoryTransactionType.PRODUCTION_OUT,
                product_id=item.product_id,
                unit_id=item.unit_id,
                warehouse_id=issue.warehouse_id,
                quantity=item.quantity,
                occurred_at=posted_at,
                source_document_type="PRODUCTION_ISSUE",
                source_document_id=issue.id,
                performed_by_user_id=issue.issued_by_user_id,
                note=item.notes,
            )
        )
    issue.status = DocumentStatus.POSTED
    issue.posted_at = posted_at
    session.add(
        AuditLog(
            actor_user_id=issue.issued_by_user_id,
            action="POST",
            entity_type="production_issue",
            entity_id=issue.id,
            new_values={
                "number": issue.number,
                "line_count": len(issue.items),
                "status": DocumentStatus.POSTED.value,
            },
        )
    )
    await session.flush()
    return issue
