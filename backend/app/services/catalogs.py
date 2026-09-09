"""Business services for reference-data lifecycle and supplier detail."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.audit import AuditLog
from app.models.catalogs import Product, Supplier, Unit, Warehouse
from app.models.inventory import Return, ReturnItem
from app.models.purchasing import Payment, Purchase, PurchaseItem


class CatalogError(ValueError):
    """Raised when a catalog operation violates a business rule."""


def _clean(value: str | None) -> str | None:
    return value.strip() if value is not None else None


def _audit_value(value: Any) -> Any:
    if isinstance(value, (UUID, Decimal, Enum)):
        return str(value)
    return value


async def _get_or_404(session: AsyncSession, model: type[Any], entity_id: UUID) -> Any:
    entity = await session.get(model, entity_id, with_for_update=True)
    if entity is None:
        raise CatalogError(f"{model.__name__} not found.")
    return entity


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


async def _save(session: AsyncSession, entity: Any, *, action: str, values: dict[str, Any]) -> Any:
    session.add(entity)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise CatalogError("A catalog entity with the same unique value already exists.") from exc
    await _audit(session, action=action, entity_type=entity.__class__.__name__, entity_id=entity.id, values=values)
    return entity


async def list_entities(
    session: AsyncSession,
    model: type[Any],
    *,
    offset: int,
    limit: int,
    search: str | None,
    active_only: bool,
) -> tuple[list[Any], int]:
    filters = [model.is_active.is_(True)] if active_only else []
    if search:
        pattern = f"%{search.strip()}%"
        fields = [model.name]
        if hasattr(model, "code"):
            fields.append(model.code)
        filters.append(or_(*(field.ilike(pattern) for field in fields)))
    query = select(model).where(*filters).order_by(model.name, model.id)
    if model is Product:
        query = query.options(selectinload(Product.unit))
    total = await session.scalar(select(func.count()).select_from(model).where(*filters))
    rows = (await session.execute(query.offset(offset).limit(limit))).scalars().all()
    return rows, int(total or 0)


async def create_unit(session: AsyncSession, data: dict[str, Any]) -> Unit:
    data = {key: _clean(value) if isinstance(value, str) else value for key, value in data.items()}
    return await _save(session, Unit(**data), action="CREATE", values=data)


async def update_unit(session: AsyncSession, entity_id: UUID, data: dict[str, Any]) -> Unit:
    entity = await _get_or_404(session, Unit, entity_id)
    data = {key: _clean(value) if isinstance(value, str) else value for key, value in data.items()}
    for key, value in data.items():
        setattr(entity, key, value)
    await session.flush()
    await _audit(session, action="UPDATE", entity_type="Unit", entity_id=entity.id, values=data)
    return entity


async def create_product(session: AsyncSession, data: dict[str, Any]) -> Product:
    unit = await session.get(Unit, data["unit_id"])
    if unit is None or not unit.is_active:
        raise CatalogError("An active unit is required.")
    data = {key: _clean(value) if isinstance(value, str) else value for key, value in data.items()}
    entity = Product(**data)
    entity.unit = unit
    return await _save(session, entity, action="CREATE", values=data)


async def update_product(session: AsyncSession, entity_id: UUID, data: dict[str, Any]) -> Product:
    entity = await _get_or_404(session, Product, entity_id)
    if data.get("unit_id") is not None:
        unit = await session.get(Unit, data["unit_id"])
        if unit is None or not unit.is_active:
            raise CatalogError("An active unit is required.")
    data = {key: _clean(value) if isinstance(value, str) else value for key, value in data.items()}
    for key, value in data.items():
        setattr(entity, key, value)
    await session.flush()
    await session.refresh(entity, ["unit"])
    await _audit(session, action="UPDATE", entity_type="Product", entity_id=entity.id, values=data)
    return entity


async def create_warehouse(session: AsyncSession, data: dict[str, Any]) -> Warehouse:
    data = {key: _clean(value) if isinstance(value, str) else value for key, value in data.items()}
    return await _save(session, Warehouse(**data), action="CREATE", values=data)


async def update_warehouse(session: AsyncSession, entity_id: UUID, data: dict[str, Any]) -> Warehouse:
    entity = await _get_or_404(session, Warehouse, entity_id)
    data = {key: _clean(value) if isinstance(value, str) else value for key, value in data.items()}
    for key, value in data.items():
        setattr(entity, key, value)
    await session.flush()
    await _audit(session, action="UPDATE", entity_type="Warehouse", entity_id=entity.id, values=data)
    return entity


async def create_supplier(session: AsyncSession, data: dict[str, Any]) -> Supplier:
    data = {key: _clean(value) if isinstance(value, str) else value for key, value in data.items()}
    return await _save(session, Supplier(**data), action="CREATE", values=data)


async def update_supplier(session: AsyncSession, entity_id: UUID, data: dict[str, Any]) -> Supplier:
    entity = await _get_or_404(session, Supplier, entity_id)
    data = {key: _clean(value) if isinstance(value, str) else value for key, value in data.items()}
    for key, value in data.items():
        setattr(entity, key, value)
    await session.flush()
    await _audit(session, action="UPDATE", entity_type="Supplier", entity_id=entity.id, values=data)
    return entity


async def supplier_detail(session: AsyncSession, entity_id: UUID) -> dict[str, Any]:
    supplier = await _get_or_404(session, Supplier, entity_id)
    purchase_count = await session.scalar(
        select(func.count()).select_from(Purchase).where(Purchase.supplier_id == entity_id)
    )
    payment_count = await session.scalar(
        select(func.count()).select_from(Payment).where(Payment.supplier_id == entity_id)
    )
    return_count = await session.scalar(
        select(func.count()).select_from(Return).where(Return.supplier_id == entity_id)
    )
    payable = await session.scalar(
        select(func.coalesce(func.sum(PurchaseItem.total), Decimal("0.00")))
        .join(Purchase, Purchase.id == PurchaseItem.purchase_id)
        .where(Purchase.supplier_id == entity_id, Purchase.status == "POSTED")
    )
    paid = await session.scalar(
        select(func.coalesce(func.sum(Payment.amount), Decimal("0.00"))).where(
            Payment.supplier_id == entity_id, Payment.status == "POSTED"
        )
    )
    returned = await session.scalar(
        select(func.coalesce(func.sum(ReturnItem.total), Decimal("0.00")))
        .join(Return, Return.id == ReturnItem.return_id)
        .where(Return.supplier_id == entity_id, Return.status == "POSTED")
    )
    total_payable = (Decimal(payable or 0) - Decimal(returned or 0)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    total_paid = Decimal(paid or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    outstanding = (total_payable - total_paid).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        **{
            field: getattr(supplier, field)
            for field in (
                "id",
                "name",
                "code",
                "tax_id",
                "phone",
                "email",
                "address",
                "notes",
                "is_active",
            )
        },
        "purchase_count": int(purchase_count or 0),
        "payment_count": int(payment_count or 0),
        "return_count": int(return_count or 0),
        "total_payable": total_payable,
        "total_paid": total_paid,
        "outstanding_debt": outstanding,
    }
