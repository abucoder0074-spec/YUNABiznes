"""Dashboard, consumption, replenishment, and Excel report endpoints."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.operations import (
    ConsumptionRead,
    DashboardRead,
    ReplenishmentRecommendationRead,
)
from app.services import reporting

router = APIRouter(prefix="/api/v1", tags=["operations"])


@router.get("/analytics/consumption", response_model=list[ConsumptionRead])
async def consumption_analytics(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    warehouse_id: str | None = None,
    product_id: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    return await reporting.consumption(
        session,
        date_from=date_from,
        date_to=date_to,
        warehouse_id=warehouse_id,
        product_id=product_id,
    )


@router.get("/replenishment-recommendations", response_model=list[ReplenishmentRecommendationRead])
async def purchase_recommendations(
    period_days: int = Query(default=30, ge=1, le=365),
    warehouse_id: str | None = None,
    product_id: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    return await reporting.replenishment_recommendations(
        session, period_days=period_days, warehouse_id=warehouse_id, product_id=product_id
    )


@router.get("/dashboard", response_model=DashboardRead)
async def operational_dashboard(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    return await reporting.dashboard(session)


@router.get("/reports/{report_name}.xlsx")
async def export_excel_report(
    report_name: str,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    session: AsyncSession = Depends(get_session),
) -> Response:
    filename, body = await reporting.excel_report(
        session, report_name=report_name, date_from=date_from, date_to=date_to
    )
    return Response(
        content=body,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )
