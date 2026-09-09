"""Purchase document API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.purchases import (
    PurchaseCreate,
    PurchasePage,
    PurchaseRead,
    PurchaseUpdate,
)
from app.services import purchases

router = APIRouter(prefix="/api/v1/purchases", tags=["purchases"])


@router.post("", response_model=PurchaseRead, status_code=status.HTTP_201_CREATED)
async def create_purchase(
    data: PurchaseCreate, session: AsyncSession = Depends(get_session)
) -> PurchaseRead:
    purchase = await purchases.create_purchase(session, data.model_dump())
    return purchases.purchase_response(purchase)


@router.get("", response_model=PurchasePage)
async def list_purchases(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    search: str | None = Query(default=None, min_length=1, max_length=100),
    session: AsyncSession = Depends(get_session),
) -> PurchasePage:
    rows, total = await purchases.list_purchases(
        session, offset=offset, limit=limit, search=search
    )
    return PurchasePage(
        items=[purchases.purchase_response(row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{purchase_id}", response_model=PurchaseRead)
async def get_purchase(
    purchase_id: UUID, session: AsyncSession = Depends(get_session)
) -> PurchaseRead:
    return purchases.purchase_response(await purchases._load_purchase(session, purchase_id))


@router.patch("/{purchase_id}", response_model=PurchaseRead)
async def update_purchase(
    purchase_id: UUID,
    data: PurchaseUpdate,
    session: AsyncSession = Depends(get_session),
) -> PurchaseRead:
    purchase = await purchases.update_purchase(
        session, purchase_id, data.model_dump(exclude_unset=True)
    )
    return purchases.purchase_response(purchase)


@router.post("/{purchase_id}/post", response_model=PurchaseRead)
async def post_purchase(
    purchase_id: UUID, session: AsyncSession = Depends(get_session)
) -> PurchaseRead:
    purchase = await purchases.post_purchase_document(session, purchase_id)
    return purchases.purchase_response(purchase)
