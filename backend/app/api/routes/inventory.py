"""Stock count and read-only inventory balance endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.operations import (
    InventoryBalanceRead,
    StockAdjustmentCreate,
    StockAdjustmentPage,
    StockAdjustmentRead,
    StockAdjustmentUpdate,
)
from app.services import adjustments, reporting

router = APIRouter(prefix="/api/v1", tags=["inventory"])


@router.get("/inventory/balances", response_model=list[InventoryBalanceRead])
async def inventory_balances(
    warehouse_id: UUID | None = None,
    product_id: UUID | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    return await reporting.inventory_balances(
        session, warehouse_id=warehouse_id, product_id=product_id
    )


@router.post("/stock-adjustments", response_model=StockAdjustmentRead, status_code=status.HTTP_201_CREATED)
async def create_stock_adjustment(
    data: StockAdjustmentCreate, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    return adjustments.adjustment_response(await adjustments.create_adjustment(session, data.model_dump()))


@router.get("/stock-adjustments", response_model=StockAdjustmentPage)
async def list_stock_adjustments(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    search: str | None = Query(default=None, min_length=1, max_length=100),
    session: AsyncSession = Depends(get_session),
) -> StockAdjustmentPage:
    rows, total = await adjustments.list_adjustments(session, offset=offset, limit=limit, search=search)
    return StockAdjustmentPage(
        items=[adjustments.adjustment_response(row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.patch("/stock-adjustments/{adjustment_id}", response_model=StockAdjustmentRead)
async def update_stock_adjustment(
    adjustment_id: UUID,
    data: StockAdjustmentUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    return adjustments.adjustment_response(
        await adjustments.update_adjustment(session, adjustment_id, data.model_dump(exclude_unset=True))
    )


@router.post("/stock-adjustments/{adjustment_id}/post", response_model=StockAdjustmentRead)
async def post_stock_adjustment(
    adjustment_id: UUID, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    return adjustments.adjustment_response(await adjustments.post_adjustment(session, adjustment_id))
