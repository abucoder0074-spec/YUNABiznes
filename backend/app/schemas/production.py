"""Request and response schemas for production issue documents."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import DocumentStatus


class ProductionIssueItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    unit_id: UUID
    quantity: Decimal = Field(gt=0)
    notes: str | None = None


class ProductionIssueCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: str = Field(min_length=1, max_length=80)
    warehouse_id: UUID
    issued_at: datetime | None = None
    notes: str | None = None
    items: list[ProductionIssueItemCreate] = Field(min_length=1)


class ProductionIssueUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: UUID | None = None
    issued_at: datetime | None = None
    notes: str | None = None
    items: list[ProductionIssueItemCreate] | None = Field(default=None, min_length=1)


class ProductionIssueItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    product_name: str
    unit_id: UUID
    quantity: Decimal
    notes: str | None


class ProductionIssueRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    number: str
    status: DocumentStatus
    warehouse_id: UUID
    warehouse_name: str
    issued_at: datetime
    notes: str | None
    items: list[ProductionIssueItemRead]
    item_count: int
    created_at: datetime
    updated_at: datetime
    posted_at: datetime | None


class ProductionIssuePage(BaseModel):
    items: list[ProductionIssueRead]
    total: int
    offset: int
    limit: int
