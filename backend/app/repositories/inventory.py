"""Inventory-balance queries derived from immutable transactions."""

from decimal import Decimal
from hashlib import blake2b
from uuid import UUID

from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import InventoryTransactionType
from app.models.inventory import InventoryTransaction

INBOUND_TRANSACTION_TYPES = (
    InventoryTransactionType.OPENING_BALANCE,
    InventoryTransactionType.PURCHASE_IN,
    InventoryTransactionType.PURCHASE_RETURN_IN,
    InventoryTransactionType.ADJUSTMENT_IN,
    InventoryTransactionType.TRANSFER_IN,
)


async def lock_stock_rows(session: AsyncSession, *, product_id: UUID, warehouse_id: UUID) -> None:
    """Lock prior movements for one balance while a posting transaction is validated."""

    statement = (
        select(InventoryTransaction.id)
        .where(
            InventoryTransaction.product_id == product_id,
            InventoryTransaction.warehouse_id == warehouse_id,
        )
        .with_for_update()
    )
    await session.execute(statement)


def inventory_lock_key(*, product_id: UUID, warehouse_id: UUID) -> int:
    """Return a stable signed bigint key for PostgreSQL transaction advisory locks."""

    source = f"inventory:{warehouse_id}:{product_id}".encode()
    digest = blake2b(source, digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


async def lock_inventory_position(
    session: AsyncSession, *, product_id: UUID, warehouse_id: UUID
) -> None:
    """Serialize all postings for one product/warehouse position.

    PostgreSQL advisory locks also work when no prior inventory event exists, unlike a
    row lock. SQLite has no equivalent and uses the previous row-lock fallback for tests.
    """

    if session.get_bind().dialect.name == "postgresql":
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": inventory_lock_key(product_id=product_id, warehouse_id=warehouse_id)},
        )
        return
    await lock_stock_rows(session, product_id=product_id, warehouse_id=warehouse_id)


async def available_quantity(
    session: AsyncSession, *, product_id: UUID, warehouse_id: UUID
) -> Decimal:
    """Calculate stock from events. No product-level balance field is maintained."""

    direction = case(
        (InventoryTransaction.transaction_type.in_(INBOUND_TRANSACTION_TYPES), 1),
        else_=-1,
    )
    statement = select(
        func.coalesce(func.sum(InventoryTransaction.quantity * direction), Decimal("0"))
    ).where(
        InventoryTransaction.product_id == product_id,
        InventoryTransaction.warehouse_id == warehouse_id,
    )
    value = (await session.execute(statement)).scalar_one()
    return Decimal(value)
