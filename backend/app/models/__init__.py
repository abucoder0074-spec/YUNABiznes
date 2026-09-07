"""Import all model classes so Alembic discovers the complete metadata."""

from app.models import immutability as _immutability  # noqa: F401
from app.models.audit import AuditLog, Setting
from app.models.catalogs import Product, Supplier, Unit, Warehouse
from app.models.identity import Role, User, UserRole
from app.models.inventory import (
    InventoryTransaction,
    ProductionIssue,
    ProductionIssueItem,
    Return,
    ReturnItem,
)
from app.models.purchasing import Payment, PaymentAllocation, Purchase, PurchaseItem, SupplierLedger

__all__ = [
    "AuditLog",
    "InventoryTransaction",
    "Payment",
    "PaymentAllocation",
    "Product",
    "ProductionIssue",
    "ProductionIssueItem",
    "Purchase",
    "PurchaseItem",
    "Return",
    "ReturnItem",
    "Role",
    "Setting",
    "Supplier",
    "SupplierLedger",
    "Unit",
    "User",
    "UserRole",
    "Warehouse",
]
