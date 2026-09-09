"""Supplier return document API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.returns import ReturnCreate, ReturnPage, ReturnRead, ReturnUpdate
from app.services import returns

router = APIRouter(prefix="/api/v1/returns", tags=["returns"])


@router.post("", response_model=ReturnRead, status_code=status.HTTP_201_CREATED)
async def create_return(
    data: ReturnCreate, session: AsyncSession = Depends(get_session)
) -> ReturnRead:
    return returns.return_response(await returns.create_return(session, data.model_dump()))


@router.get("", response_model=ReturnPage)
async def list_returns(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    search: str | None = Query(default=None, min_length=1, max_length=100),
    session: AsyncSession = Depends(get_session),
) -> ReturnPage:
    rows, total = await returns.list_returns(
        session, offset=offset, limit=limit, search=search
    )
    return ReturnPage(
        items=[returns.return_response(row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{return_id}", response_model=ReturnRead)
async def get_return(
    return_id: UUID, session: AsyncSession = Depends(get_session)
) -> ReturnRead:
    return returns.return_response(await returns._load_return(session, return_id))


@router.patch("/{return_id}", response_model=ReturnRead)
async def update_return(
    return_id: UUID,
    data: ReturnUpdate,
    session: AsyncSession = Depends(get_session),
) -> ReturnRead:
    return returns.return_response(
        await returns.update_return(session, return_id, data.model_dump(exclude_unset=True))
    )


@router.post("/{return_id}/post", response_model=ReturnRead)
async def post_return(
    return_id: UUID, session: AsyncSession = Depends(get_session)
) -> ReturnRead:
    return returns.return_response(await returns.post_return_document(session, return_id))
