"""Production issue workflow regression tests."""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import DocumentStatus, InventoryTransactionType
from app.models.audit import AuditLog
from app.models.inventory import InventoryTransaction
from app.repositories.inventory import available_quantity
from app.services.catalogs import (
    create_product,
    create_supplier,
    create_unit,
    create_warehouse,
)
from app.services.production import (
    ProductionIssueError,
    create_production_issue,
    list_production_issues,
    post_production_issue_document_service,
    update_production_issue,
)
from app.services.purchases import create_purchase, post_purchase_document


async def setup_production_catalog(session: AsyncSession) -> dict[str, object]:
    unit = await create_unit(session, {"name": f"kg-{uuid4().hex[:6]}", "symbol": f"k{uuid4().hex[:3]}"})
    other_unit = await create_unit(
        session, {"name": f"piece-{uuid4().hex[:6]}", "symbol": f"p{uuid4().hex[:3]}"}
    )
    product = await create_product(
        session, {"name": f"Raw-{uuid4().hex[:6]}", "code": f"R-{uuid4().hex[:8]}", "unit_id": unit.id}
    )
    second_product = await create_product(
        session,
        {"name": f"Raw2-{uuid4().hex[:6]}", "code": f"R2-{uuid4().hex[:8]}", "unit_id": unit.id},
    )
    supplier = await create_supplier(session, {"name": f"Supplier-{uuid4().hex[:6]}"})
    warehouse = await create_warehouse(session, {"name": f"Warehouse-{uuid4().hex[:6]}"})
    return locals()


async def add_stock(session: AsyncSession, catalog: dict[str, object], quantity: str = "10"):
    purchase = await create_purchase(
        session,
        {
            "number": f"PUR-{uuid4().hex[:8]}",
            "supplier_id": catalog["supplier"].id,
            "warehouse_id": catalog["warehouse"].id,
            "items": [
                {
                    "product_id": catalog["product"].id,
                    "unit_id": catalog["unit"].id,
                    "quantity": Decimal(quantity),
                    "unit_price": Decimal("2"),
                }
            ],
        },
    )
    return await post_purchase_document(session, purchase.id)


def issue_data(catalog: dict[str, object], *, quantity: str = "3", items=None) -> dict:
    return {
        "number": f"ISS-{uuid4().hex[:8]}",
        "warehouse_id": catalog["warehouse"].id,
        "items": items
        or [
            {
                "product_id": catalog["product"].id,
                "unit_id": catalog["unit"].id,
                "quantity": Decimal(quantity),
            }
        ],
    }


async def test_create_list_update_draft_issue(db_session: AsyncSession) -> None:
    catalog = await setup_production_catalog(db_session)
    issue = await create_production_issue(db_session, issue_data(catalog))
    assert issue.status is DocumentStatus.DRAFT
    assert await db_session.scalar(select(func.count()).select_from(InventoryTransaction)) == 0
    await update_production_issue(db_session, issue.id, {"notes": "batch one"})
    rows, total = await list_production_issues(
        db_session, offset=0, limit=10, search=issue.number
    )
    assert total == 1
    assert rows[0].notes == "batch one"


async def test_post_deducts_stock_and_creates_audit(db_session: AsyncSession) -> None:
    catalog = await setup_production_catalog(db_session)
    await add_stock(db_session, catalog)
    issue = await create_production_issue(db_session, issue_data(catalog, quantity="3"))
    posted = await post_production_issue_document_service(db_session, issue.id)
    assert posted.status is DocumentStatus.POSTED
    movement = await db_session.scalar(
        select(InventoryTransaction).where(InventoryTransaction.source_document_id == issue.id)
    )
    assert movement is not None
    assert movement.transaction_type is InventoryTransactionType.PRODUCTION_OUT
    assert movement.source_document_type == "PRODUCTION_ISSUE"
    assert await available_quantity(
        db_session, product_id=catalog["product"].id, warehouse_id=catalog["warehouse"].id
    ) == Decimal("7.0000")
    assert await db_session.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.entity_id == issue.id)
    ) == 2


async def test_multiple_items_duplicate_and_invalid_catalog_rejected(
    db_session: AsyncSession,
) -> None:
    catalog = await setup_production_catalog(db_session)
    await add_stock(db_session, catalog)
    with pytest.raises(ProductionIssueError, match="duplicate"):
        await create_production_issue(
            db_session,
            issue_data(
                catalog,
                items=[
                    {
                        "product_id": catalog["product"].id,
                        "unit_id": catalog["unit"].id,
                        "quantity": Decimal("1"),
                    },
                    {
                        "product_id": catalog["product"].id,
                        "unit_id": catalog["unit"].id,
                        "quantity": Decimal("1"),
                    },
                ],
            ),
        )
    catalog["product"].is_active = False
    with pytest.raises(ProductionIssueError, match="inactive"):
        await create_production_issue(db_session, issue_data(catalog))


async def test_insufficient_stock_leaves_draft_without_movement(db_session: AsyncSession) -> None:
    catalog = await setup_production_catalog(db_session)
    await add_stock(db_session, catalog, quantity="2")
    issue = await create_production_issue(db_session, issue_data(catalog, quantity="3"))
    with pytest.raises(ProductionIssueError, match="Insufficient stock"):
        async with db_session.begin_nested():
            await post_production_issue_document_service(db_session, issue.id)
    await db_session.refresh(issue)
    assert issue.status is DocumentStatus.DRAFT
    assert await db_session.scalar(
        select(func.count())
        .select_from(InventoryTransaction)
        .where(InventoryTransaction.source_document_id == issue.id)
    ) == 0


async def test_double_post_and_posted_mutation_rejected(db_session: AsyncSession) -> None:
    catalog = await setup_production_catalog(db_session)
    await add_stock(db_session, catalog)
    issue = await create_production_issue(db_session, issue_data(catalog, quantity="1"))
    await post_production_issue_document_service(db_session, issue.id)
    with pytest.raises(ProductionIssueError, match="Only draft"):
        await post_production_issue_document_service(db_session, issue.id)
    with pytest.raises(ProductionIssueError, match="Only draft"):
        await update_production_issue(db_session, issue.id, {"notes": "tamper"})
    item = issue.items[0]
    item.quantity = Decimal("2")
    with pytest.raises(ValueError, match="Items"):
        await db_session.flush()


async def test_purchase_issue_return_stock_calculation(db_session: AsyncSession) -> None:
    catalog = await setup_production_catalog(db_session)
    purchase = await add_stock(db_session, catalog, quantity="10")
    issue = await create_production_issue(db_session, issue_data(catalog, quantity="4"))
    await post_production_issue_document_service(db_session, issue.id)
    assert await available_quantity(
        db_session, product_id=catalog["product"].id, warehouse_id=catalog["warehouse"].id
    ) == Decimal("6.0000")
    assert purchase.status is DocumentStatus.POSTED
