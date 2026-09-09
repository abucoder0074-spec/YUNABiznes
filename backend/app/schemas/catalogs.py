"""Request and response schemas for reference data."""

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CatalogBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UnitCreate(CatalogBase):
    name: str = Field(min_length=1, max_length=80)
    symbol: str = Field(min_length=1, max_length=20)


class UnitUpdate(CatalogBase):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    symbol: str | None = Field(default=None, min_length=1, max_length=20)
    is_active: bool | None = None


class UnitRead(CatalogBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    symbol: str
    is_active: bool


class ProductCreate(CatalogBase):
    name: str = Field(min_length=1, max_length=255)
    code: str | None = Field(default=None, min_length=1, max_length=80)
    unit_id: UUID
    minimum_stock: Decimal | None = Field(default=None, ge=0)
    safety_stock: Decimal | None = Field(default=None, ge=0)
    target_stock: Decimal | None = Field(default=None, ge=0)
    lead_time_days: Decimal | None = Field(default=None, ge=0)
    notes: str | None = None


class ProductUpdate(CatalogBase):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    code: str | None = Field(default=None, min_length=1, max_length=80)
    unit_id: UUID | None = None
    minimum_stock: Decimal | None = Field(default=None, ge=0)
    safety_stock: Decimal | None = Field(default=None, ge=0)
    target_stock: Decimal | None = Field(default=None, ge=0)
    lead_time_days: Decimal | None = Field(default=None, ge=0)
    notes: str | None = None
    is_active: bool | None = None


class ProductRead(CatalogBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    code: str | None
    unit_id: UUID
    unit: UnitRead
    minimum_stock: Decimal | None
    safety_stock: Decimal | None
    target_stock: Decimal | None
    lead_time_days: Decimal | None
    notes: str | None
    is_active: bool


class WarehouseCreate(CatalogBase):
    name: str = Field(min_length=1, max_length=255)
    code: str | None = Field(default=None, min_length=1, max_length=80)
    location: str | None = Field(default=None, max_length=500)
    notes: str | None = None


class WarehouseUpdate(CatalogBase):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    code: str | None = Field(default=None, min_length=1, max_length=80)
    location: str | None = Field(default=None, max_length=500)
    notes: str | None = None
    is_active: bool | None = None


class WarehouseRead(CatalogBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    code: str | None
    location: str | None
    notes: str | None
    is_active: bool


class SupplierCreate(CatalogBase):
    name: str = Field(min_length=1, max_length=255)
    code: str | None = Field(default=None, min_length=1, max_length=80)
    tax_id: str | None = Field(default=None, min_length=1, max_length=80)
    phone: str | None = Field(default=None, max_length=80)
    email: str | None = Field(default=None, max_length=255)
    address: str | None = None
    notes: str | None = None


class SupplierUpdate(CatalogBase):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    code: str | None = Field(default=None, min_length=1, max_length=80)
    tax_id: str | None = Field(default=None, min_length=1, max_length=80)
    phone: str | None = Field(default=None, max_length=80)
    email: str | None = Field(default=None, max_length=255)
    address: str | None = None
    notes: str | None = None
    is_active: bool | None = None


class SupplierRead(CatalogBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    code: str | None
    tax_id: str | None
    phone: str | None
    email: str | None
    address: str | None
    notes: str | None
    is_active: bool


class SupplierDetail(SupplierRead):
    purchase_count: int
    payment_count: int
    return_count: int
    total_payable: Decimal
    total_paid: Decimal
    outstanding_debt: Decimal


class Page[T](BaseModel):
    items: list[T]
    total: int
    offset: int
    limit: int
