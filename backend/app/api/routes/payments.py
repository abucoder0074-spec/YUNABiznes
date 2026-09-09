"""Payment and supplier debt API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.payments import (
    PaymentAllocationCreate,
    PaymentAllocationRead,
    PaymentCreate,
    PaymentPage,
    PaymentRead,
    PaymentUpdate,
    PurchaseBalance,
    SupplierDebt,
)
from app.services import payments

router = APIRouter(prefix="/api/v1", tags=["payments"])


@router.post("/payments", response_model=PaymentRead, status_code=status.HTTP_201_CREATED)
async def create_payment(
    data: PaymentCreate, session: AsyncSession = Depends(get_session)
) -> PaymentRead:
    return payments.payment_response(await payments.create_payment(session, data.model_dump()))


@router.get("/payments", response_model=PaymentPage)
async def list_payments(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    search: str | None = Query(default=None, min_length=1, max_length=100),
    session: AsyncSession = Depends(get_session),
) -> PaymentPage:
    rows, total = await payments.list_payments(
        session, offset=offset, limit=limit, search=search
    )
    return PaymentPage(
        items=[payments.payment_response(row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/payments/{payment_id}", response_model=PaymentRead)
async def get_payment(
    payment_id: UUID, session: AsyncSession = Depends(get_session)
) -> PaymentRead:
    return payments.payment_response(await payments._load_payment(session, payment_id))


@router.patch("/payments/{payment_id}", response_model=PaymentRead)
async def update_payment(
    payment_id: UUID,
    data: PaymentUpdate,
    session: AsyncSession = Depends(get_session),
) -> PaymentRead:
    payment = await payments.update_payment(
        session, payment_id, data.model_dump(exclude_unset=True)
    )
    return payments.payment_response(payment)


@router.post("/payments/{payment_id}/post", response_model=PaymentRead)
async def post_payment(
    payment_id: UUID, session: AsyncSession = Depends(get_session)
) -> PaymentRead:
    return payments.payment_response(
        await payments.post_payment_document(session, payment_id)
    )


@router.post("/payments/{payment_id}/allocations", response_model=PaymentRead)
async def add_payment_allocation(
    payment_id: UUID,
    data: PaymentAllocationCreate,
    session: AsyncSession = Depends(get_session),
) -> PaymentRead:
    return payments.payment_response(
        await payments.add_allocation(session, payment_id, data.model_dump())
    )


@router.get("/payments/{payment_id}/allocations", response_model=list[PaymentAllocationRead])
async def get_payment_allocations(
    payment_id: UUID, session: AsyncSession = Depends(get_session)
) -> list[PaymentAllocationRead]:
    return await payments.payment_allocations(session, payment_id)


@router.get("/suppliers/{supplier_id}/debt", response_model=SupplierDebt)
async def get_supplier_debt(
    supplier_id: UUID, session: AsyncSession = Depends(get_session)
) -> SupplierDebt:
    return await payments.supplier_debt(session, supplier_id)


@router.get("/purchases/{purchase_id}/balance", response_model=PurchaseBalance)
async def get_purchase_balance(
    purchase_id: UUID, session: AsyncSession = Depends(get_session)
) -> PurchaseBalance:
    return await payments.purchase_balance(session, purchase_id)
