"""Schemas for counted stock, operational analytics, and reporting endpoints."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import DocumentStatus


class StockAdjustmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: str = Field(min_length=1, max_length=80)
    warehouse_id: UUID
    product_id: UUID
    unit_id: UUID
    counted_quantity: Decimal = Field(ge=0)
    reason: str = Field(min_length=1, max_length=2000)
    notes: str | None = None
    counted_at: datetime | None = None


class StockAdjustmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    counted_quantity: Decimal | None = Field(default=None, ge=0)
    reason: str | None = Field(default=None, min_length=1, max_length=2000)
    notes: str | None = None
    counted_at: datetime | None = None


class StockAdjustmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    number: str
    warehouse_id: UUID
    warehouse_name: str
    product_id: UUID
    product_name: str
    unit_id: UUID
    unit_symbol: str
    counted_quantity: Decimal
    system_quantity: Decimal | None
    difference_quantity: Decimal | None
    reason: str
    notes: str | None
    counted_at: datetime
    status: DocumentStatus
    created_at: datetime
    posted_at: datetime | None


class StockAdjustmentPage(BaseModel):
    items: list[StockAdjustmentRead]
    total: int
    offset: int
    limit: int


class InventoryBalanceRead(BaseModel):
    warehouse_id: UUID
    warehouse_name: str
    product_id: UUID
    product_name: str
    unit_id: UUID
    unit_symbol: str
    quantity: Decimal


class ConsumptionRead(BaseModel):
    warehouse_id: UUID
    warehouse_name: str
    product_id: UUID
    product_name: str
    unit_id: UUID
    unit_symbol: str
    consumed_quantity: Decimal
    average_daily_consumption: Decimal


class ReplenishmentRecommendationRead(BaseModel):
    product_id: UUID
    product_name: str
    unit_id: UUID
    unit_symbol: str
    usable_stock: Decimal
    average_daily_usage: Decimal
    lead_time_days: Decimal
    safety_stock: Decimal
    reorder_point: Decimal
    target_stock: Decimal
    recommended_purchase_quantity: Decimal
    reason: str


class DashboardRead(BaseModel):
    current_stock_lines: int
    current_stock_quantity: Decimal
    today_purchases: Decimal
    today_consumption: Decimal
    today_payments: Decimal
    supplier_debt: Decimal
    low_stock: list[ReplenishmentRecommendationRead]
    purchase_recommendations: list[ReplenishmentRecommendationRead]
    recent_purchases: list[dict[str, object]]
    recent_production_issues: list[dict[str, object]]
    recent_payments: list[dict[str, object]]
