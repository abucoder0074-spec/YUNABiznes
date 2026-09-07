"""ORM safeguards for append-only accounting and inventory records."""

from sqlalchemy import event

from app.models.audit import AuditLog
from app.models.inventory import InventoryTransaction
from app.models.purchasing import SupplierLedger


def _reject_mutation(_: object, __: object, ___: object) -> None:
    raise ValueError("Accounting, inventory, and audit events are append-only and cannot be changed.")


for _event_target in (InventoryTransaction, SupplierLedger, AuditLog):
    event.listen(_event_target, "before_update", _reject_mutation)
    event.listen(_event_target, "before_delete", _reject_mutation)
