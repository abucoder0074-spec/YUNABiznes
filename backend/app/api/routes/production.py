"""Production issue document API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.production import (
    ProductionIssueCreate,
    ProductionIssuePage,
    ProductionIssueRead,
    ProductionIssueUpdate,
)
from app.services import production

router = APIRouter(prefix="/api/v1/production-issues", tags=["production"])


@router.post("", response_model=ProductionIssueRead, status_code=status.HTTP_201_CREATED)
async def create_production_issue(
    data: ProductionIssueCreate, session: AsyncSession = Depends(get_session)
) -> ProductionIssueRead:
    issue = await production.create_production_issue(session, data.model_dump())
    return production.production_issue_response(issue)


@router.get("", response_model=ProductionIssuePage)
async def list_production_issues(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    search: str | None = Query(default=None, min_length=1, max_length=100),
    session: AsyncSession = Depends(get_session),
) -> ProductionIssuePage:
    rows, total = await production.list_production_issues(
        session, offset=offset, limit=limit, search=search
    )
    return ProductionIssuePage(
        items=[production.production_issue_response(row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{issue_id}", response_model=ProductionIssueRead)
async def get_production_issue(
    issue_id: UUID, session: AsyncSession = Depends(get_session)
) -> ProductionIssueRead:
    return production.production_issue_response(await production._load(session, issue_id))


@router.patch("/{issue_id}", response_model=ProductionIssueRead)
async def update_production_issue(
    issue_id: UUID,
    data: ProductionIssueUpdate,
    session: AsyncSession = Depends(get_session),
) -> ProductionIssueRead:
    return production.production_issue_response(
        await production.update_production_issue(
            session, issue_id, data.model_dump(exclude_unset=True)
        )
    )


@router.post("/{issue_id}/post", response_model=ProductionIssueRead)
async def post_production_issue(
    issue_id: UUID, session: AsyncSession = Depends(get_session)
) -> ProductionIssueRead:
    return production.production_issue_response(
        await production.post_production_issue_document_service(session, issue_id)
    )
