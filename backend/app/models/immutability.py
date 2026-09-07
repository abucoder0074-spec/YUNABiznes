"""ORM safeguards for append-only accounting and posted documents."""

from sqlalchemy import event, inspect
from sqlalchemy.orm.attributes import NO_VALUE

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


def _reject_posted_update(_: object, __: object, target: object) -> None:
    state = inspect(target)
    status = state.attrs.status
    if status.history.has_changes():
        return
    if status.value == "POSTED":
        raise ValueError("Posted documents are immutable; use a reversal or correction.")


def _reject_posted_delete(_: object, __: object, target: object) -> None:
    if getattr(target, "status", None) == "POSTED":
        raise ValueError("Posted documents are immutable; use a reversal or correction.")


for _event_target in (InventoryTransaction, SupplierLedger, AuditLog):
    event.listen(_event_target, "before_update", _reject_mutation)
    event.listen(_event_target, "before_delete", _reject_mutation)

for _event_target in (Purchase, Payment, Return, ProductionIssue):
    event.listen(_event_target, "before_update", _reject_posted_update)
    event.listen(_event_target, "before_delete", _reject_posted_delete)

def _reject_posted_child_mutation(_: object, __: object, target: object) -> None:
    state = inspect(target)
    for relationship_name in ("purchase", "production_issue", "return_document"):
        relationship = state.attrs.get(relationship_name)
        if relationship is not None and relationship.loaded_value is not NO_VALUE:
            parent = relationship.loaded_value
            if getattr(parent, "status", None) is DocumentStatus.POSTED:
                raise ValueError("Items of posted documents are immutable.")
            return


for _event_target in (PurchaseItem, ProductionIssueItem, ReturnItem):
    event.listen(_event_target, "before_update", _reject_posted_child_mutation)
    event.listen(_event_target, "before_delete", _reject_posted_child_mutation)


def _reject_allocation_mutation(_: object, __: object, target: PaymentAllocation) -> None:
    payment = inspect(target).attrs.payment.loaded_value
    if payment is not NO_VALUE and payment is not None and payment.status is DocumentStatus.POSTED:
        raise ValueError("Allocations of posted payments are immutable.")


event.listen(PaymentAllocation, "before_update", _reject_allocation_mutation)
event.listen(PaymentAllocation, "before_delete", _reject_allocation_mutation)
