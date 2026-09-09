"""Request and response schemas for supplier returns."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import DocumentStatus


class ReturnItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purchase_item_id: UUID
    product_id: UUID
    unit_id: UUID
    quantity: Decimal = Field(gt=0)
    notes: str | None = None


class ReturnCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: str = Field(min_length=1, max_length=80)
    supplier_id: UUID
    warehouse_id: UUID
    notes: str | None = None
    items: list[ReturnItemCreate] = Field(min_length=1)


class ReturnUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_id: UUID | None = None
    warehouse_id: UUID | None = None
    notes: str | None = None
    items: list[ReturnItemCreate] | None = Field(default=None, min_length=1)


class ReturnItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    purchase_item_id: UUID
    purchase_id: UUID
    purchase_number: str
    product_id: UUID
    product_name: str
    unit_id: UUID
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal
    notes: str | None


class ReturnRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    number: str
    status: DocumentStatus
    supplier_id: UUID
    supplier_name: str
    warehouse_id: UUID
    warehouse_name: str
    notes: str | None
    items: list[ReturnItemRead]
    return_total: Decimal
    created_at: datetime
    posted_at: datetime | None


class ReturnPage(BaseModel):
    items: list[ReturnRead]
    total: int
    offset: int
    limit: int
