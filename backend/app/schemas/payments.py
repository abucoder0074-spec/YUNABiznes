"""Request and response schemas for supplier payments and allocations."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import DocumentStatus, PaymentMethod


class PaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: str = Field(min_length=1, max_length=80)
    supplier_id: UUID
    paid_at: datetime | None = None
    amount: Decimal = Field(gt=0)
    method: PaymentMethod
    reference_number: str | None = Field(default=None, max_length=120)
    notes: str | None = None


class PaymentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_id: UUID | None = None
    paid_at: datetime | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    method: PaymentMethod | None = None
    reference_number: str | None = Field(default=None, max_length=120)
    notes: str | None = None


class PaymentAllocationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purchase_id: UUID
    amount: Decimal = Field(gt=0)
    notes: str | None = None


class PaymentAllocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    payment_id: UUID
    purchase_id: UUID
    amount: Decimal
    notes: str | None


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    number: str
    supplier_id: UUID
    supplier_name: str
    paid_at: datetime
    amount: Decimal
    method: PaymentMethod
    status: DocumentStatus
    reference_number: str | None
    notes: str | None
    allocated_amount: Decimal
    unallocated_amount: Decimal
    allocations: list[PaymentAllocationRead]
    created_at: datetime
    posted_at: datetime | None


class PaymentPage(BaseModel):
    items: list[PaymentRead]
    total: int
    offset: int
    limit: int


class PurchaseBalance(BaseModel):
    purchase_total: Decimal
    paid_amount: Decimal
    returned_amount: Decimal
    outstanding_amount: Decimal


class SupplierDebt(BaseModel):
    total_purchases: Decimal
    total_paid: Decimal
    total_returns: Decimal
    outstanding_debt: Decimal
