"""Reusable validation helpers for posting services."""

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalogs import Product


async def validate_product_units(
    session: AsyncSession, positions: Iterable[tuple[UUID, UUID]]
) -> None:
    """Ensure all inventory movements use the product's configured base unit."""

    expected_units = {product_id: unit_id for product_id, unit_id in positions}
    if not expected_units:
        return
    rows = await session.execute(
        select(Product.id, Product.unit_id, Product.is_active).where(Product.id.in_(expected_units))
    )
    products = {product_id: (unit_id, is_active) for product_id, unit_id, is_active in rows}
    for product_id, unit_id in expected_units.items():
        product = products.get(product_id)
        if product is None:
            raise ValueError(f"Unknown product {product_id}.")
        expected_unit_id, is_active = product
        if not is_active:
            raise ValueError(f"Product {product_id} is inactive and cannot be posted.")
        if expected_unit_id != unit_id:
            raise ValueError(f"Product {product_id} must use its configured base unit.")
