"""Controlled physical stock-count workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import DocumentStatus, InventoryTransactionType
from app.models.audit import AuditLog
from app.models.inventory import InventoryTransaction, StockAdjustment
from app.repositories.inventory import available_quantity, lock_inventory_position
from app.services.validation import validate_active_supplier_warehouse, validate_product_units


class StockAdjustmentError(ValueError):
    """Raised when a physical stock count cannot be safely recorded."""


def _text(value: str | None) -> str | None:
    return value.strip() if value is not None else None


async def _load(session: AsyncSession, adjustment_id: UUID, *, lock: bool = False) -> StockAdjustment:
    statement = (
        select(StockAdjustment)
        .where(StockAdjustment.id == adjustment_id)
        .options(
            selectinload(StockAdjustment.warehouse),
            selectinload(StockAdjustment.product),
            selectinload(StockAdjustment.unit),
        )
    )
    if lock:
        statement = statement.with_for_update()
    adjustment = (await session.execute(statement)).scalar_one_or_none()
    if adjustment is None:
        raise StockAdjustmentError("Stock adjustment not found.")
    return adjustment


async def _validate(session: AsyncSession, data: dict[str, Any]) -> None:
    if data["counted_quantity"] < 0:
        raise StockAdjustmentError("Counted quantity cannot be negative.")
    reason = _text(data.get("reason"))
    if not reason:
        raise StockAdjustmentError("A stock adjustment requires a reason.")
    try:
        await validate_active_supplier_warehouse(session, warehouse_id=data["warehouse_id"])
        await validate_product_units(session, [(data["product_id"], data["unit_id"])])
    except ValueError as exc:
        raise StockAdjustmentError(str(exc)) from exc


async def create_adjustment(session: AsyncSession, data: dict[str, Any]) -> StockAdjustment:
    await _validate(session, data)
    adjustment = StockAdjustment(
        **{key: _text(value) if isinstance(value, str) else value for key, value in data.items()},
        counted_at=data.get("counted_at") or datetime.now(UTC),
    )
    session.add(adjustment)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise StockAdjustmentError("A stock adjustment with the same number already exists.") from exc
    session.add(
        AuditLog(
            action="CREATE",
            entity_type="stock_adjustment",
            entity_id=adjustment.id,
            new_values={
                "number": adjustment.number,
                "counted_quantity": str(adjustment.counted_quantity),
                "reason": adjustment.reason,
            },
        )
    )
    return await _load(session, adjustment.id)


async def update_adjustment(
    session: AsyncSession, adjustment_id: UUID, data: dict[str, Any]
) -> StockAdjustment:
    adjustment = await _load(session, adjustment_id, lock=True)
    if adjustment.status is not DocumentStatus.DRAFT:
        raise StockAdjustmentError("Only draft stock adjustments can be changed.")
    candidate = {
        "warehouse_id": adjustment.warehouse_id,
        "product_id": adjustment.product_id,
        "unit_id": adjustment.unit_id,
        "counted_quantity": data.get("counted_quantity", adjustment.counted_quantity),
        "reason": data.get("reason", adjustment.reason),
    }
    await _validate(session, candidate)
    for key, value in data.items():
        setattr(adjustment, key, _text(value) if isinstance(value, str) else value)
    await session.flush()
    session.add(
        AuditLog(
            action="UPDATE",
            entity_type="stock_adjustment",
            entity_id=adjustment.id,
            new_values={"number": adjustment.number, "counted_quantity": str(adjustment.counted_quantity)},
        )
    )
    return await _load(session, adjustment.id)


async def post_adjustment(session: AsyncSession, adjustment_id: UUID) -> StockAdjustment:
    adjustment = await _load(session, adjustment_id, lock=True)
    if adjustment.status is not DocumentStatus.DRAFT:
        raise StockAdjustmentError("Only draft stock adjustments can be posted.")
    await _validate(
        session,
        {
            "warehouse_id": adjustment.warehouse_id,
            "product_id": adjustment.product_id,
            "unit_id": adjustment.unit_id,
            "counted_quantity": adjustment.counted_quantity,
            "reason": adjustment.reason,
        },
    )
    await lock_inventory_position(
        session, product_id=adjustment.product_id, warehouse_id=adjustment.warehouse_id
    )
    system_quantity = await available_quantity(
        session, product_id=adjustment.product_id, warehouse_id=adjustment.warehouse_id
    )
    difference = adjustment.counted_quantity - system_quantity
    posted_at = datetime.now(UTC)
    if difference:
        session.add(
            InventoryTransaction(
                transaction_type=(
                    InventoryTransactionType.ADJUSTMENT_IN
                    if difference > 0
                    else InventoryTransactionType.ADJUSTMENT_OUT
                ),
                product_id=adjustment.product_id,
                unit_id=adjustment.unit_id,
                warehouse_id=adjustment.warehouse_id,
                quantity=abs(difference),
                occurred_at=posted_at,
                source_document_type="STOCK_ADJUSTMENT",
                source_document_id=adjustment.id,
                performed_by_user_id=adjustment.created_by_user_id,
                reason=adjustment.reason,
                note=adjustment.notes,
            )
        )
    adjustment.system_quantity = system_quantity
    adjustment.difference_quantity = difference
    adjustment.status = DocumentStatus.POSTED
    adjustment.posted_at = posted_at
    session.add(
        AuditLog(
            actor_user_id=adjustment.created_by_user_id,
            action="POST",
            entity_type="stock_adjustment",
            entity_id=adjustment.id,
            new_values={
                "number": adjustment.number,
                "system_quantity": str(system_quantity),
                "counted_quantity": str(adjustment.counted_quantity),
                "difference_quantity": str(difference),
            },
            reason=adjustment.reason,
        )
    )
    await session.flush()
    return await _load(session, adjustment.id)


async def list_adjustments(
    session: AsyncSession, *, offset: int, limit: int, search: str | None
) -> tuple[list[StockAdjustment], int]:
    filters = [StockAdjustment.number.ilike(f"%{search.strip()}%")] if search else []
    total = await session.scalar(select(func.count()).select_from(StockAdjustment).where(*filters))
    rows = (
        await session.execute(
            select(StockAdjustment)
            .where(*filters)
            .order_by(StockAdjustment.created_at.desc(), StockAdjustment.id)
            .options(
                selectinload(StockAdjustment.warehouse),
                selectinload(StockAdjustment.product),
                selectinload(StockAdjustment.unit),
            )
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return rows, int(total or 0)


def adjustment_response(adjustment: StockAdjustment) -> dict[str, Any]:
    return {
        "id": adjustment.id,
        "number": adjustment.number,
        "warehouse_id": adjustment.warehouse_id,
        "warehouse_name": adjustment.warehouse.name,
        "product_id": adjustment.product_id,
        "product_name": adjustment.product.name,
        "unit_id": adjustment.unit_id,
        "unit_symbol": adjustment.unit.symbol,
        "counted_quantity": adjustment.counted_quantity,
        "system_quantity": adjustment.system_quantity,
        "difference_quantity": adjustment.difference_quantity,
        "reason": adjustment.reason,
        "notes": adjustment.notes,
        "counted_at": adjustment.counted_at,
        "status": adjustment.status,
        "created_at": adjustment.created_at,
        "posted_at": adjustment.posted_at,
    }
