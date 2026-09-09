"""Production issue document lifecycle services."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import DocumentStatus
from app.models.audit import AuditLog
from app.models.catalogs import Product, Unit, Warehouse
from app.models.inventory import ProductionIssue, ProductionIssueItem
from app.services.inventory import post_production_issue_document


class ProductionIssueError(ValueError):
    """Raised when a production issue violates a business rule."""


def _text(value: str | None) -> str | None:
    return value.strip() if value is not None else None


async def _load(
    session: AsyncSession, issue_id: UUID, *, lock: bool = False
) -> ProductionIssue:
    statement = (
        select(ProductionIssue)
        .where(ProductionIssue.id == issue_id)
        .options(
            selectinload(ProductionIssue.warehouse),
            selectinload(ProductionIssue.items).selectinload(ProductionIssueItem.product),
            selectinload(ProductionIssue.items).selectinload(ProductionIssueItem.unit),
            selectinload(ProductionIssue.items).selectinload(ProductionIssueItem.production_issue),
        )
    )
    if lock:
        statement = statement.with_for_update()
    issue = (await session.execute(statement)).scalar_one_or_none()
    if issue is None:
        raise ProductionIssueError("Production issue not found.")
    return issue


async def _validate(
    session: AsyncSession, *, warehouse_id: UUID, items: list[dict[str, Any]]
) -> None:
    warehouse = await session.get(Warehouse, warehouse_id)
    if warehouse is None:
        raise ProductionIssueError("Warehouse not found.")
    if not warehouse.is_active:
        raise ProductionIssueError("Warehouse is inactive and cannot be used.")
    if not items:
        raise ProductionIssueError("A production issue requires at least one item.")
    if len({item["product_id"] for item in items}) != len(items):
        raise ProductionIssueError("A production issue cannot contain duplicate product lines.")
    products = {
        product.id: product
        for product in (
            await session.execute(
                select(Product).where(
                    Product.id.in_({item["product_id"] for item in items})
                )
            )
        ).scalars()
    }
    units = {
        unit.id: unit
        for unit in (
            await session.execute(
                select(Unit).where(Unit.id.in_({item["unit_id"] for item in items}))
            )
        ).scalars()
    }
    for item in items:
        if item["quantity"] <= 0:
            raise ProductionIssueError("Production issue quantities must be greater than zero.")
        product = products.get(item["product_id"])
        if product is None:
            raise ProductionIssueError("Product not found.")
        if not product.is_active:
            raise ProductionIssueError("Product is inactive and cannot be used.")
        unit = units.get(item["unit_id"])
        if unit is None:
            raise ProductionIssueError("Unit not found.")
        if not unit.is_active:
            raise ProductionIssueError("Unit is inactive and cannot be used.")
        if product.unit_id != item["unit_id"]:
            raise ProductionIssueError("Product must use its configured base unit.")


def _item_data(items: list[dict[str, Any]]) -> list[ProductionIssueItem]:
    return [ProductionIssueItem(**{**item, "notes": _text(item.get("notes"))}) for item in items]


async def create_production_issue(
    session: AsyncSession, data: dict[str, Any]
) -> ProductionIssue:
    items = data.pop("items")
    await _validate(session, warehouse_id=data["warehouse_id"], items=items)
    issue = ProductionIssue(
        **{
            key: _text(value) if isinstance(value, str) else value
            for key, value in data.items()
        }
    )
    issue.issued_at = issue.issued_at or datetime.now(UTC)
    issue.items = _item_data(items)
    session.add(issue)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ProductionIssueError("A production issue with the same number already exists.") from exc
    session.add(
        AuditLog(
            action="CREATE",
            entity_type="production_issue",
            entity_id=issue.id,
            new_values={"number": issue.number, "item_count": len(items)},
        )
    )
    return await _load(session, issue.id)


async def list_production_issues(
    session: AsyncSession, *, offset: int, limit: int, search: str | None
) -> tuple[list[ProductionIssue], int]:
    filters = [ProductionIssue.number.ilike(f"%{search.strip()}%")] if search else []
    total = await session.scalar(
        select(func.count()).select_from(ProductionIssue).where(*filters)
    )
    rows = (
        await session.execute(
            select(ProductionIssue)
            .where(*filters)
            .order_by(ProductionIssue.created_at.desc(), ProductionIssue.id)
            .options(
                selectinload(ProductionIssue.warehouse),
                selectinload(ProductionIssue.items).selectinload(ProductionIssueItem.product),
                selectinload(ProductionIssue.items).selectinload(ProductionIssueItem.unit),
            )
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return rows, int(total or 0)


async def update_production_issue(
    session: AsyncSession, issue_id: UUID, data: dict[str, Any]
) -> ProductionIssue:
    issue = await _load(session, issue_id, lock=True)
    if issue.status is not DocumentStatus.DRAFT:
        raise ProductionIssueError("Only draft production issues can be changed.")
    raw_items = data.pop("items", None)
    items = raw_items or [
        {
            "product_id": item.product_id,
            "unit_id": item.unit_id,
            "quantity": item.quantity,
            "notes": item.notes,
        }
        for item in issue.items
    ]
    warehouse_id = data.get("warehouse_id", issue.warehouse_id)
    await _validate(session, warehouse_id=warehouse_id, items=items)
    for key, value in data.items():
        setattr(issue, key, _text(value) if isinstance(value, str) else value)
    if raw_items is not None:
        issue.items = _item_data(items)
    await session.flush()
    session.add(
        AuditLog(
            action="UPDATE",
            entity_type="production_issue",
            entity_id=issue.id,
            new_values={"number": issue.number, "item_count": len(items)},
        )
    )
    return await _load(session, issue.id)


async def post_production_issue_document_service(
    session: AsyncSession, issue_id: UUID
) -> ProductionIssue:
    try:
        return await post_production_issue_document(session, issue_id)
    except ValueError as exc:
        raise ProductionIssueError(str(exc)) from exc


def production_issue_response(issue: ProductionIssue) -> dict[str, Any]:
    return {
        "id": issue.id,
        "number": issue.number,
        "status": issue.status,
        "warehouse_id": issue.warehouse_id,
        "warehouse_name": issue.warehouse.name,
        "issued_at": issue.issued_at,
        "notes": issue.notes,
        "items": [
            {
                "id": item.id,
                "product_id": item.product_id,
                "product_name": item.product.name,
                "unit_id": item.unit_id,
                "quantity": item.quantity,
                "notes": item.notes,
            }
            for item in issue.items
        ],
        "item_count": len(issue.items),
        "created_at": issue.created_at,
        "updated_at": issue.updated_at,
        "posted_at": issue.posted_at,
    }
