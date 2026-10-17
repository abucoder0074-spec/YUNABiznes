"""Immutable inventory events and production/return documents."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import DocumentStatus, InventoryTransactionType
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.types import MONEY, QUANTITY

if TYPE_CHECKING:
    from app.models.catalogs import Product, Supplier, Unit, Warehouse
    from app.models.identity import User
    from app.models.purchasing import PurchaseItem, SupplierLedger


class InventoryTransaction(UUIDPrimaryKeyMixin, Base):
    """Append-only source of truth for all inventory balances."""

    __tablename__ = "inventory_transactions"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_inventory_transactions_quantity_positive"),
        CheckConstraint(
            "transaction_type NOT IN ('ADJUSTMENT_IN', 'ADJUSTMENT_OUT') "
            "OR (reason IS NOT NULL AND length(trim(reason)) > 0)",
            name="ck_inventory_adjustments_require_reason",
        ),
        Index("ix_inventory_balance_lookup", "warehouse_id", "product_id", "occurred_at"),
        Index("ix_inventory_transactions_source", "source_document_type", "source_document_id"),
    )

    transaction_type: Mapped[InventoryTransactionType] = mapped_column(
        Enum(InventoryTransactionType, native_enum=False, create_constraint=True), index=True
    )
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), index=True
    )
    unit_id: Mapped[UUID] = mapped_column(ForeignKey("units.id", ondelete="RESTRICT"))
    warehouse_id: Mapped[UUID] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), index=True
    )
    quantity: Mapped[Decimal] = mapped_column(QUANTITY)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    source_document_type: Mapped[str] = mapped_column(String(80))
    source_document_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    performed_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reason: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)

    product: Mapped[Product] = relationship(back_populates="inventory_transactions")
    unit: Mapped[Unit] = relationship()
    warehouse: Mapped[Warehouse] = relationship(back_populates="inventory_transactions")
    performed_by: Mapped[User | None] = relationship(back_populates="inventory_transactions")


class ProductionIssue(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "production_issues"
    __table_args__ = (Index("ix_production_issues_warehouse_date", "warehouse_id", "issued_at"),)

    number: Mapped[str] = mapped_column(String(80), unique=True)
    warehouse_id: Mapped[UUID] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), index=True
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, native_enum=False, create_constraint=True),
        default=DocumentStatus.DRAFT,
        server_default=DocumentStatus.DRAFT.value,
    )
    notes: Mapped[str | None] = mapped_column(Text)
    issued_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    warehouse: Mapped[Warehouse] = relationship(back_populates="production_issues")
    issued_by: Mapped[User | None] = relationship(back_populates="production_issues")
    items: Mapped[list[ProductionIssueItem]] = relationship(
        back_populates="production_issue", cascade="all, delete-orphan"
    )


class ProductionIssueItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "production_issue_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_production_issue_items_quantity_positive"),
        Index("ix_production_issue_items_product", "product_id"),
    )

    production_issue_id: Mapped[UUID] = mapped_column(
        ForeignKey("production_issues.id", ondelete="RESTRICT"), index=True
    )
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    unit_id: Mapped[UUID] = mapped_column(ForeignKey("units.id", ondelete="RESTRICT"))
    quantity: Mapped[Decimal] = mapped_column(QUANTITY)
    notes: Mapped[str | None] = mapped_column(Text)

    production_issue: Mapped[ProductionIssue] = relationship(back_populates="items")
    product: Mapped[Product] = relationship(back_populates="production_issue_items")
    unit: Mapped[Unit] = relationship()


class Return(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Supplier-return document; posting later creates stock and ledger events together."""

    __tablename__ = "returns"
    __table_args__ = (Index("ix_returns_supplier_date", "supplier_id", "returned_at"),)

    number: Mapped[str] = mapped_column(String(80), unique=True)
    supplier_id: Mapped[UUID] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), index=True
    )
    warehouse_id: Mapped[UUID] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), index=True
    )
    returned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, native_enum=False, create_constraint=True),
        default=DocumentStatus.DRAFT,
        server_default=DocumentStatus.DRAFT.value,
    )
    notes: Mapped[str | None] = mapped_column(Text)
    authorized_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    supplier: Mapped[Supplier] = relationship(back_populates="returns")
    warehouse: Mapped[Warehouse] = relationship(back_populates="returns")
    authorized_by: Mapped[User | None] = relationship(back_populates="returns_authorized")
    items: Mapped[list[ReturnItem]] = relationship(back_populates="return_document", cascade="all, delete-orphan")
    ledger_entries: Mapped[list[SupplierLedger]] = relationship(back_populates="return_document")


class ReturnItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "return_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_return_items_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="ck_return_items_unit_price_nonnegative"),
        Index("ix_return_items_product", "product_id"),
    )

    return_id: Mapped[UUID] = mapped_column(ForeignKey("returns.id", ondelete="RESTRICT"), index=True)
    purchase_item_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("purchase_items.id", ondelete="RESTRICT"), index=True
    )
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    unit_id: Mapped[UUID] = mapped_column(ForeignKey("units.id", ondelete="RESTRICT"))
    quantity: Mapped[Decimal] = mapped_column(QUANTITY)
    unit_price: Mapped[Decimal] = mapped_column(MONEY)
    total: Mapped[Decimal | None] = mapped_column(
        MONEY, Computed("quantity * unit_price", persisted=True), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text)

    return_document: Mapped[Return] = relationship(back_populates="items")
    purchase_item: Mapped[PurchaseItem | None] = relationship(back_populates="return_items")
    product: Mapped[Product] = relationship(back_populates="return_items")
    unit: Mapped[Unit] = relationship()
