"""Request and response schemas for purchase documents."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import DocumentStatus
from app.schemas.catalogs import UnitRead


class PurchaseItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    unit_id: UUID
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    notes: str | None = None


class PurchaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: str = Field(min_length=1, max_length=80)
    supplier_id: UUID
    warehouse_id: UUID
    currency: str = Field(default="UZS", min_length=3, max_length=3)
    notes: str | None = None
    items: list[PurchaseItemCreate] = Field(min_length=1)


class PurchaseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_id: UUID | None = None
    warehouse_id: UUID | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    notes: str | None = None
    items: list[PurchaseItemCreate] | None = Field(default=None, min_length=1)


class PurchaseItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    product_name: str
    unit_id: UUID
    unit: UnitRead
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal
    notes: str | None


class PurchaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    number: str
    status: DocumentStatus
    supplier_id: UUID
    supplier_name: str
    warehouse_id: UUID
    warehouse_name: str
    currency: str
    notes: str | None
    items: list[PurchaseItemRead]
    purchase_total: Decimal
    created_at: datetime
    posted_at: datetime | None


class PurchasePage(BaseModel):
    items: list[PurchaseRead]
    total: int
    offset: int
    limit: int
