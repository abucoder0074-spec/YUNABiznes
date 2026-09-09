"""Purchasing, payment allocation, and supplier accounting models."""

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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import DocumentStatus, PaymentMethod, SupplierLedgerEntryType
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.types import MONEY, QUANTITY

if TYPE_CHECKING:
    from app.models.catalogs import Product, Supplier, Unit, Warehouse
    from app.models.identity import User
    from app.models.inventory import Return, ReturnItem


class Purchase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "purchases"
    __table_args__ = (Index("ix_purchases_supplier_date", "supplier_id", "purchased_at"),)

    number: Mapped[str] = mapped_column(String(80), unique=True)
    supplier_id: Mapped[UUID] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), index=True
    )
    warehouse_id: Mapped[UUID] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), index=True
    )
    purchased_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, native_enum=False, create_constraint=True),
        default=DocumentStatus.DRAFT,
        server_default=DocumentStatus.DRAFT.value,
    )
    currency: Mapped[str] = mapped_column(String(3), default="UZS", server_default="UZS")
    notes: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))

    supplier: Mapped[Supplier] = relationship(back_populates="purchases")
    warehouse: Mapped[Warehouse] = relationship(back_populates="purchases")
    created_by: Mapped[User | None] = relationship(back_populates="purchases_created")
    items: Mapped[list[PurchaseItem]] = relationship(
        back_populates="purchase", cascade="all, delete-orphan"
    )
    allocations: Mapped[list[PaymentAllocation]] = relationship(back_populates="purchase")
    ledger_entries: Mapped[list[SupplierLedger]] = relationship(back_populates="purchase")

    @property
    def total_amount(self) -> Decimal:
        """Calculate total from stored line totals; this is never an editable balance field."""

        return sum(((item.total or Decimal("0")) for item in self.items), Decimal("0"))

    @property
    def paid_amount(self) -> Decimal:
        """Calculate allocations from posted payments only."""

        return sum(
            (
                allocation.amount
                for allocation in self.allocations
                if allocation.payment is not None
                and allocation.payment.status is DocumentStatus.POSTED
            ),
            Decimal("0"),
        )

    @property
    def outstanding_amount(self) -> Decimal:
        """Return the remaining debt for this purchase, never below zero."""

        return max(self.total_amount - self.paid_amount, Decimal("0"))


class PurchaseItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "purchase_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_purchase_items_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="ck_purchase_items_unit_price_nonnegative"),
        Index("ix_purchase_items_product", "product_id"),
    )

    purchase_id: Mapped[UUID] = mapped_column(
        ForeignKey("purchases.id", ondelete="RESTRICT"), index=True
    )
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    unit_id: Mapped[UUID] = mapped_column(ForeignKey("units.id", ondelete="RESTRICT"))
    quantity: Mapped[Decimal] = mapped_column(QUANTITY)
    unit_price: Mapped[Decimal] = mapped_column(MONEY)
    total: Mapped[Decimal | None] = mapped_column(
        MONEY, Computed("quantity * unit_price", persisted=True), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text)

    purchase: Mapped[Purchase] = relationship(back_populates="items")
    product: Mapped[Product] = relationship(back_populates="purchase_items")
    unit: Mapped[Unit] = relationship()
    return_items: Mapped[list[ReturnItem]] = relationship(back_populates="purchase_item")


class Payment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        Index("ix_payments_supplier_date", "supplier_id", "paid_at"),
    )

    number: Mapped[str] = mapped_column(String(80), unique=True)
    supplier_id: Mapped[UUID] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), index=True
    )
    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    amount: Mapped[Decimal] = mapped_column(MONEY)
    method: Mapped[PaymentMethod] = mapped_column(
        Enum(PaymentMethod, native_enum=False, create_constraint=True)
    )
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, native_enum=False, create_constraint=True),
        default=DocumentStatus.DRAFT,
        server_default=DocumentStatus.DRAFT.value,
    )
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reference_number: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))

    supplier: Mapped[Supplier] = relationship(back_populates="payments")
    created_by: Mapped[User | None] = relationship(back_populates="payments_created")
    allocations: Mapped[list[PaymentAllocation]] = relationship(
        back_populates="payment", cascade="all, delete-orphan"
    )
    ledger_entries: Mapped[list[SupplierLedger]] = relationship(back_populates="payment")

    @property
    def allocated_amount(self) -> Decimal:
        return sum((allocation.amount for allocation in self.allocations), Decimal("0"))

    @property
    def unallocated_amount(self) -> Decimal:
        return self.amount - self.allocated_amount


class PaymentAllocation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payment_allocations"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payment_allocations_amount_positive"),
        Index("ix_payment_allocations_purchase", "purchase_id"),
        Index(
            "uq_payment_allocations_general_payment",
            "payment_id",
            unique=True,
            postgresql_where=text("purchase_id IS NULL"),
            sqlite_where=text("purchase_id IS NULL"),
        ),
    )

    payment_id: Mapped[UUID] = mapped_column(
        ForeignKey("payments.id", ondelete="RESTRICT"), index=True
    )
    purchase_id: Mapped[UUID | None] = mapped_column(ForeignKey("purchases.id", ondelete="RESTRICT"))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    notes: Mapped[str | None] = mapped_column(Text)

    payment: Mapped[Payment] = relationship(back_populates="allocations", lazy="joined")
    purchase: Mapped[Purchase | None] = relationship(back_populates="allocations")


class SupplierLedger(UUIDPrimaryKeyMixin, Base):
    """Immutable supplier accounting event; debt is its debits minus credits."""

    __tablename__ = "supplier_ledger"
    __table_args__ = (
        CheckConstraint("debit_amount >= 0", name="ck_supplier_ledger_debit_nonnegative"),
        CheckConstraint("credit_amount >= 0", name="ck_supplier_ledger_credit_nonnegative"),
        CheckConstraint(
            "(debit_amount > 0 AND credit_amount = 0) OR "
            "(credit_amount > 0 AND debit_amount = 0)",
            name="ck_supplier_ledger_one_sided_entry",
        ),
        CheckConstraint(
            "(entry_type = 'PURCHASE_DEBIT' AND purchase_id IS NOT NULL "
            "AND payment_id IS NULL AND return_id IS NULL) OR "
            "(entry_type = 'PAYMENT_CREDIT' AND payment_id IS NOT NULL "
            "AND purchase_id IS NULL AND return_id IS NULL) OR "
            "(entry_type = 'RETURN_CREDIT' AND return_id IS NOT NULL "
            "AND purchase_id IS NULL AND payment_id IS NULL) OR "
            "(entry_type IN ('ADJUSTMENT_DEBIT', 'ADJUSTMENT_CREDIT') "
            "AND purchase_id IS NULL AND payment_id IS NULL AND return_id IS NULL)",
            name="ck_supplier_ledger_entry_reference",
        ),
        Index("ix_supplier_ledger_supplier_date", "supplier_id", "occurred_at"),
    )

    supplier_id: Mapped[UUID] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), index=True
    )
    entry_type: Mapped[SupplierLedgerEntryType] = mapped_column(
        Enum(SupplierLedgerEntryType, native_enum=False, create_constraint=True)
    )
    debit_amount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), server_default="0")
    credit_amount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), server_default="0")
    currency: Mapped[str] = mapped_column(String(3), default="UZS", server_default="UZS")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    purchase_id: Mapped[UUID | None] = mapped_column(ForeignKey("purchases.id", ondelete="RESTRICT"))
    payment_id: Mapped[UUID | None] = mapped_column(ForeignKey("payments.id", ondelete="RESTRICT"))
    return_id: Mapped[UUID | None] = mapped_column(ForeignKey("returns.id", ondelete="RESTRICT"))
    source_document_type: Mapped[str] = mapped_column(String(80))
    source_document_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    description: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))

    supplier: Mapped[Supplier] = relationship(back_populates="ledger_entries")
    purchase: Mapped[Purchase | None] = relationship(back_populates="ledger_entries")
    payment: Mapped[Payment | None] = relationship(back_populates="ledger_entries")
    return_document: Mapped[Return | None] = relationship(back_populates="ledger_entries")
    created_by: Mapped[User | None] = relationship(back_populates="ledger_entries")
