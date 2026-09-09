"""Purchase document lifecycle services."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import DocumentStatus
from app.models.audit import AuditLog
from app.models.purchasing import Purchase, PurchaseItem
from app.services.purchasing import DocumentPostingError, post_purchase
from app.services.validation import validate_active_supplier_warehouse, validate_product_units


class PurchaseError(ValueError):
    """Raised when a purchase draft cannot be created or changed."""


def _normalize_text(value: str | None) -> str | None:
    return value.strip() if value is not None else None


async def _audit(session: AsyncSession, action: str, purchase: Purchase) -> None:
    session.add(
        AuditLog(
            action=action,
            entity_type="Purchase",
            entity_id=purchase.id,
            new_values={
                "number": purchase.number,
                "status": purchase.status.value,
                "purchase_total": str(purchase.total_amount),
            },
        )
    )


async def _validate_draft(
    session: AsyncSession,
    *,
    supplier_id: UUID,
    warehouse_id: UUID,
    items: list[dict[str, Any]],
) -> None:
    await validate_active_supplier_warehouse(
        session, supplier_id=supplier_id, warehouse_id=warehouse_id
    )
    if not items:
        raise PurchaseError("A purchase requires at least one item.")
    product_units = [(item["product_id"], item["unit_id"]) for item in items]
    await validate_product_units(session, product_units)
    product_ids = [product_id for product_id, _ in product_units]
    if len(set(product_ids)) != len(product_ids):
        raise PurchaseError("A purchase cannot contain duplicate product lines.")
    for item in items:
        if item["quantity"] <= 0:
            raise PurchaseError("Purchase quantities must be greater than zero.")
        if item["unit_price"] < 0:
            raise PurchaseError("Purchase unit prices cannot be negative.")


def _item_values(item: dict[str, Any]) -> dict[str, Any]:
    return {
        **item,
        "notes": _normalize_text(item.get("notes")),
    }


async def _load_purchase(session: AsyncSession, purchase_id: UUID, *, lock: bool = False) -> Purchase:
    statement = (
        select(Purchase)
        .where(Purchase.id == purchase_id)
        .options(
            selectinload(Purchase.supplier),
            selectinload(Purchase.warehouse),
            selectinload(Purchase.items).selectinload(PurchaseItem.product),
            selectinload(Purchase.items).selectinload(PurchaseItem.unit),
        )
    )
    if lock:
        statement = statement.with_for_update()
    purchase = (await session.execute(statement)).scalar_one_or_none()
    if purchase is None:
        raise PurchaseError("Purchase not found.")
    return purchase


async def create_purchase(session: AsyncSession, data: dict[str, Any]) -> Purchase:
    items = [_item_values(item) for item in data.pop("items")]
    try:
        await _validate_draft(
            session,
            supplier_id=data["supplier_id"],
            warehouse_id=data["warehouse_id"],
            items=items,
        )
    except ValueError as exc:
        raise PurchaseError(str(exc)) from exc
    purchase = Purchase(
        **{key: _normalize_text(value) if isinstance(value, str) else value for key, value in data.items()}
    )
    purchase.items = [PurchaseItem(**item) for item in items]
    session.add(purchase)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise PurchaseError("A purchase with the same number already exists.") from exc
    await _audit(session, "CREATE", purchase)
    return await _load_purchase(session, purchase.id)


async def list_purchases(
    session: AsyncSession, *, offset: int, limit: int, search: str | None
) -> tuple[list[Purchase], int]:
    filters = []
    if search:
        filters.append(Purchase.number.ilike(f"%{search.strip()}%"))
    total = await session.scalar(select(func.count()).select_from(Purchase).where(*filters))
    rows = (
        await session.execute(
            select(Purchase)
            .where(*filters)
            .order_by(Purchase.created_at.desc(), Purchase.id)
            .options(
                selectinload(Purchase.supplier),
                selectinload(Purchase.warehouse),
                selectinload(Purchase.items).selectinload(PurchaseItem.product),
                selectinload(Purchase.items).selectinload(PurchaseItem.unit),
            )
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return rows, int(total or 0)


async def update_purchase(
    session: AsyncSession, purchase_id: UUID, data: dict[str, Any]
) -> Purchase:
    purchase = await _load_purchase(session, purchase_id, lock=True)
    if purchase.status is not DocumentStatus.DRAFT:
        raise PurchaseError("Only draft purchases can be changed.")
    item_data = data.pop("items", None)
    supplier_id = data.get("supplier_id", purchase.supplier_id)
    warehouse_id = data.get("warehouse_id", purchase.warehouse_id)
    items = [_item_values(item) for item in item_data] if item_data is not None else [
        {
            "product_id": item.product_id,
            "unit_id": item.unit_id,
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "notes": item.notes,
        }
        for item in purchase.items
    ]
    try:
        await _validate_draft(
            session, supplier_id=supplier_id, warehouse_id=warehouse_id, items=items
        )
    except ValueError as exc:
        raise PurchaseError(str(exc)) from exc
    for key, value in data.items():
        setattr(purchase, key, _normalize_text(value) if isinstance(value, str) else value)
    if item_data is not None:
        purchase.items = [PurchaseItem(**item) for item in items]
    await session.flush()
    await _audit(session, "UPDATE", purchase)
    return await _load_purchase(session, purchase.id)


async def post_purchase_document(session: AsyncSession, purchase_id: UUID) -> Purchase:
    try:
        purchase = await post_purchase(session, purchase_id=purchase_id)
    except (DocumentPostingError, ValueError) as exc:
        raise PurchaseError(str(exc)) from exc
    return await _load_purchase(session, purchase.id)


def purchase_response(purchase: Purchase) -> dict[str, Any]:
    return {
        "id": purchase.id,
        "number": purchase.number,
        "status": purchase.status,
        "supplier_id": purchase.supplier_id,
        "supplier_name": purchase.supplier.name,
        "warehouse_id": purchase.warehouse_id,
        "warehouse_name": purchase.warehouse.name,
        "currency": purchase.currency,
        "notes": purchase.notes,
        "items": [
            {
                "id": item.id,
                "product_id": item.product_id,
                "product_name": item.product.name,
                "unit_id": item.unit_id,
                "unit": item.unit,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "line_total": item.total or Decimal("0.00"),
                "notes": item.notes,
            }
            for item in purchase.items
        ],
        "purchase_total": purchase.total_amount,
        "created_at": purchase.created_at,
        "posted_at": purchase.posted_at,
    }
