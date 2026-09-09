"""Supplier return document lifecycle services."""

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
from app.models.catalogs import Unit
from app.models.inventory import Return, ReturnItem
from app.models.purchasing import Purchase, PurchaseItem
from app.repositories.purchasing import purchase_item_returned_quantity
from app.services.purchasing import DocumentPostingError, post_supplier_return
from app.services.validation import validate_active_supplier_warehouse, validate_product_units


class ReturnError(ValueError):
    """Raised when a supplier return violates an accounting or stock rule."""


def _text(value: str | None) -> str | None:
    return value.strip() if value is not None else None


async def _load_return(
    session: AsyncSession, return_id: UUID, *, lock: bool = False
) -> Return:
    statement = (
        select(Return)
        .where(Return.id == return_id)
        .options(
            selectinload(Return.supplier),
            selectinload(Return.warehouse),
            selectinload(Return.items).selectinload(ReturnItem.product),
            selectinload(Return.items).selectinload(ReturnItem.unit),
            selectinload(Return.items).selectinload(ReturnItem.return_document),
            selectinload(Return.items)
            .selectinload(ReturnItem.purchase_item)
            .selectinload(PurchaseItem.purchase),
        )
    )
    if lock:
        statement = statement.with_for_update()
    result = await session.execute(statement)
    document = result.scalar_one_or_none()
    if document is None:
        raise ReturnError("Supplier return not found.")
    return document


async def _source_items(
    session: AsyncSession, item_data: list[dict[str, Any]]
) -> dict[UUID, tuple[PurchaseItem, Purchase]]:
    ids = {item["purchase_item_id"] for item in item_data}
    if len(ids) != len(item_data):
        raise ReturnError("A return cannot contain duplicate purchase item lines.")
    rows = (
        await session.execute(
            select(PurchaseItem, Purchase)
            .join(Purchase, Purchase.id == PurchaseItem.purchase_id)
            .where(PurchaseItem.id.in_(ids))
        )
    ).all()
    sources = {item.id: (item, purchase) for item, purchase in rows}
    if len(sources) != len(ids):
        raise ReturnError("A referenced purchase item no longer exists.")
    return sources


async def _validate_items(
    session: AsyncSession,
    *,
    supplier_id: UUID,
    warehouse_id: UUID,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    await validate_active_supplier_warehouse(
        session, supplier_id=supplier_id, warehouse_id=warehouse_id
    )
    sources = await _source_items(session, items)
    await validate_product_units(
        session, ((item["product_id"], item["unit_id"]) for item in items)
    )
    unit_ids = {item["unit_id"] for item in items}
    active_units = {
        unit_id
        for unit_id, is_active in (
            await session.execute(select(Unit.id, Unit.is_active).where(Unit.id.in_(unit_ids)))
        )
        if is_active
    }
    if active_units != unit_ids:
        raise ReturnError("Return items must use active units.")
    normalized: list[dict[str, Any]] = []
    for item in items:
        source_item, purchase = sources[item["purchase_item_id"]]
        if purchase.status is not DocumentStatus.POSTED:
            raise ReturnError("Supplier returns must reference posted purchases.")
        if purchase.supplier_id != supplier_id:
            raise ReturnError("A return item must belong to the selected supplier.")
        if purchase.warehouse_id != warehouse_id:
            raise ReturnError("A return must use the original purchase warehouse.")
        if source_item.product_id != item["product_id"]:
            raise ReturnError("A return item must match its original purchased product.")
        if source_item.unit_id != item["unit_id"]:
            raise ReturnError("A return item must match its original purchased unit.")
        client_price = item.get("unit_price")
        if client_price is not None and client_price != source_item.unit_price:
            raise ReturnError("A return item price must match its original purchase price.")
        returned = await purchase_item_returned_quantity(session, source_item.id)
        if returned + item["quantity"] > source_item.quantity:
            raise ReturnError("Return quantity cannot exceed the remaining returnable quantity.")
        normalized.append(
            {
                **item,
                "unit_price": source_item.unit_price,
                "notes": _text(item.get("notes")),
            }
        )
    return normalized


async def create_return(session: AsyncSession, data: dict[str, Any]) -> Return:
    items = data.pop("items")
    try:
        items = await _validate_items(
            session,
            supplier_id=data["supplier_id"],
            warehouse_id=data["warehouse_id"],
            items=items,
        )
    except ValueError as exc:
        raise ReturnError(str(exc)) from exc
    document = Return(
        **{key: _text(value) if isinstance(value, str) else value for key, value in data.items()}
    )
    document.items = [ReturnItem(**item) for item in items]
    session.add(document)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ReturnError("A supplier return with the same number already exists.") from exc
    session.add(
        AuditLog(
            action="CREATE",
            entity_type="supplier_return",
            entity_id=document.id,
            new_values={"number": document.number, "item_count": len(items)},
        )
    )
    return await _load_return(session, document.id)


async def list_returns(
    session: AsyncSession, *, offset: int, limit: int, search: str | None
) -> tuple[list[Return], int]:
    filters = [Return.number.ilike(f"%{search.strip()}%")] if search else []
    total = await session.scalar(select(func.count()).select_from(Return).where(*filters))
    rows = (
        await session.execute(
            select(Return)
            .where(*filters)
            .order_by(Return.created_at.desc(), Return.id)
            .options(
                selectinload(Return.supplier),
                selectinload(Return.warehouse),
                selectinload(Return.items).selectinload(ReturnItem.product),
                selectinload(Return.items).selectinload(ReturnItem.unit),
            )
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return rows, int(total or 0)


async def update_return(
    session: AsyncSession, return_id: UUID, data: dict[str, Any]
) -> Return:
    document = await _load_return(session, return_id, lock=True)
    if document.status is not DocumentStatus.DRAFT:
        raise ReturnError("Only draft supplier returns can be changed.")
    raw_items = data.pop("items", None)
    items = raw_items or [
        {
            "purchase_item_id": item.purchase_item_id,
            "purchase_id": item.purchase_item.purchase_id,
            "purchase_number": item.purchase_item.purchase.number,
            "product_id": item.product_id,
            "unit_id": item.unit_id,
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "notes": item.notes,
        }
        for item in document.items
    ]
    try:
        items = await _validate_items(
            session,
            supplier_id=data.get("supplier_id", document.supplier_id),
            warehouse_id=data.get("warehouse_id", document.warehouse_id),
            items=items,
        )
    except ValueError as exc:
        raise ReturnError(str(exc)) from exc
    for key, value in data.items():
        setattr(document, key, _text(value) if isinstance(value, str) else value)
    if raw_items is not None:
        document.items = [ReturnItem(**item) for item in items]
    await session.flush()
    session.add(
        AuditLog(
            action="UPDATE",
            entity_type="supplier_return",
            entity_id=document.id,
            new_values={"number": document.number, "item_count": len(items)},
        )
    )
    return await _load_return(session, document.id)


async def post_return_document(session: AsyncSession, return_id: UUID) -> Return:
    try:
        document = await post_supplier_return(session, return_id=return_id)
    except (DocumentPostingError, ValueError) as exc:
        raise ReturnError(str(exc)) from exc
    return await _load_return(session, document.id)


def return_response(document: Return) -> dict[str, Any]:
    return {
        "id": document.id,
        "number": document.number,
        "status": document.status,
        "supplier_id": document.supplier_id,
        "supplier_name": document.supplier.name,
        "warehouse_id": document.warehouse_id,
        "warehouse_name": document.warehouse.name,
        "notes": document.notes,
        "items": [
            {
                "id": item.id,
                "purchase_item_id": item.purchase_item_id,
                "product_id": item.product_id,
                "product_name": item.product.name,
                "unit_id": item.unit_id,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "line_total": item.total or Decimal("0.00"),
                "notes": item.notes,
            }
            for item in document.items
        ],
        "return_total": document.total_amount if hasattr(document, "total_amount") else sum(
            (item.total or Decimal("0.00") for item in document.items), Decimal("0.00")
        ),
        "created_at": document.created_at,
        "posted_at": document.posted_at,
    }
