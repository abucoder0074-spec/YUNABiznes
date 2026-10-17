"""ORM safeguards for append-only accounting records and posted documents.

Three layers of protection:

* Inventory transactions, supplier ledger entries and audit logs can never be updated or deleted.
* A POSTED document can only move to VOID; no other column may change afterwards.
* Lines (items, allocations) of a document can only be added, changed or removed while the
  parent document is still a DRAFT.

PostgreSQL triggers (see migration 20261017_0002) enforce the append-only rule for bulk SQL too.
"""

from collections.abc import Callable

from sqlalchemy import event, inspect, select

from app.core.enums import DocumentStatus
from app.models.audit import AuditLog
from app.models.inventory import (
    InventoryTransaction,
    ProductionIssue,
    ProductionIssueItem,
    Return,
    ReturnItem,
)
from app.models.purchasing import (
    Payment,
    PaymentAllocation,
    Purchase,
    PurchaseItem,
    SupplierLedger,
)


def _reject_mutation(_: object, __: object, ___: object) -> None:
    raise ValueError("Accounting, inventory, and audit events are append-only and cannot be changed.")


for _event_target in (InventoryTransaction, SupplierLedger, AuditLog):
    event.listen(_event_target, "before_update", _reject_mutation)
    event.listen(_event_target, "before_delete", _reject_mutation)


def _changed_columns(target: object) -> set[str]:
    state = inspect(target)
    return {
        attribute.key
        for attribute in state.mapper.column_attrs
        if state.attrs[attribute.key].history.has_changes()
    }


def _guard_finalized_document(_: object, __: object, target: object) -> None:
    changed = _changed_columns(target)
    if not changed:
        return
    history = inspect(target).attrs.status.history
    previous = history.deleted[0] if history.deleted else target.status
    if previous is DocumentStatus.DRAFT:
        return
    if previous is DocumentStatus.POSTED and changed == {"status"} and target.status is DocumentStatus.VOID:
        return
    raise ValueError("Posted or void documents are immutable; only POSTED -> VOID is allowed.")


def _guard_document_delete(_: object, __: object, target: object) -> None:
    if target.status is not DocumentStatus.DRAFT:
        raise ValueError("Only draft documents can be deleted.")


for _document in (Purchase, Payment, Return, ProductionIssue):
    event.listen(_document, "before_update", _guard_finalized_document)
    event.listen(_document, "before_delete", _guard_document_delete)


def _line_guard(parent_model: type, parent_fk: str) -> Callable[[object, object, object], None]:
    def guard(_: object, connection: object, target: object) -> None:
        parent_id = getattr(target, parent_fk)
        if parent_id is None:
            return
        status = connection.execute(
            select(parent_model.status).where(parent_model.id == parent_id)
        ).scalar_one_or_none()
        if status is not None and status is not DocumentStatus.DRAFT:
            raise ValueError("Lines can only be changed while the parent document is a draft.")

    return guard


for _line, _parent, _fk in (
    (PurchaseItem, Purchase, "purchase_id"),
    (PaymentAllocation, Payment, "payment_id"),
    (ReturnItem, Return, "return_id"),
    (ProductionIssueItem, ProductionIssue, "production_issue_id"),
):
    _guard = _line_guard(_parent, _fk)
    for _name in ("before_insert", "before_update", "before_delete"):
        event.listen(_line, _name, _guard)
