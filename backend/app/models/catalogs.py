"""Reference data for raw materials, units, suppliers, and warehouses."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.types import QUANTITY

if TYPE_CHECKING:
    from app.models.inventory import (
        InventoryTransaction,
        ProductionIssue,
        ProductionIssueItem,
        Return,
        ReturnItem,
    )
    from app.models.purchasing import Payment, Purchase, PurchaseItem, SupplierLedger


class Unit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "units"

    name: Mapped[str] = mapped_column(String(80), unique=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    products: Mapped[list[Product]] = relationship(back_populates="unit")


class Product(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("minimum_stock IS NULL OR minimum_stock >= 0", name="ck_products_minimum_stock"),
        CheckConstraint("safety_stock IS NULL OR safety_stock >= 0", name="ck_products_safety_stock"),
    )

    name: Mapped[str] = mapped_column(String(255), index=True)
    code: Mapped[str | None] = mapped_column(String(80), unique=True)
    unit_id: Mapped[UUID] = mapped_column(ForeignKey("units.id", ondelete="RESTRICT"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    minimum_stock: Mapped[Decimal | None] = mapped_column(QUANTITY)
    safety_stock: Mapped[Decimal | None] = mapped_column(QUANTITY)
    notes: Mapped[str | None] = mapped_column(Text)

    unit: Mapped[Unit] = relationship(back_populates="products")
    purchase_items: Mapped[list[PurchaseItem]] = relationship(back_populates="product")
    inventory_transactions: Mapped[list[InventoryTransaction]] = relationship(back_populates="product")
    production_issue_items: Mapped[list[ProductionIssueItem]] = relationship(back_populates="product")
    return_items: Mapped[list[ReturnItem]] = relationship(back_populates="product")


class Warehouse(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "warehouses"

    name: Mapped[str] = mapped_column(String(255), unique=True)
    code: Mapped[str | None] = mapped_column(String(80), unique=True)
    location: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    notes: Mapped[str | None] = mapped_column(Text)

    purchases: Mapped[list[Purchase]] = relationship(back_populates="warehouse")
    inventory_transactions: Mapped[list[InventoryTransaction]] = relationship(back_populates="warehouse")
    production_issues: Mapped[list[ProductionIssue]] = relationship(back_populates="warehouse")
    returns: Mapped[list[Return]] = relationship(back_populates="warehouse")


class Supplier(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "suppliers"

    name: Mapped[str] = mapped_column(String(255), index=True)
    code: Mapped[str | None] = mapped_column(String(80), unique=True)
    tax_id: Mapped[str | None] = mapped_column(String(80), unique=True)
    phone: Mapped[str | None] = mapped_column(String(80))
    email: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    notes: Mapped[str | None] = mapped_column(Text)

    purchases: Mapped[list[Purchase]] = relationship(back_populates="supplier")
    payments: Mapped[list[Payment]] = relationship(back_populates="supplier")
    returns: Mapped[list[Return]] = relationship(back_populates="supplier")
    ledger_entries: Mapped[list[SupplierLedger]] = relationship(back_populates="supplier")
