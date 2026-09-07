"""Users and role assignments."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.audit import AuditLog, Setting
    from app.models.inventory import InventoryTransaction, ProductionIssue, Return
    from app.models.purchasing import Payment, Purchase, SupplierLedger


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    role_links: Mapped[list[UserRole]] = relationship(back_populates="user")
    purchases_created: Mapped[list[Purchase]] = relationship(back_populates="created_by")
    payments_created: Mapped[list[Payment]] = relationship(back_populates="created_by")
    inventory_transactions: Mapped[list[InventoryTransaction]] = relationship(back_populates="performed_by")
    production_issues: Mapped[list[ProductionIssue]] = relationship(back_populates="issued_by")
    returns_authorized: Mapped[list[Return]] = relationship(back_populates="authorized_by")
    ledger_entries: Mapped[list[SupplierLedger]] = relationship(back_populates="created_by")
    audit_logs: Mapped[list[AuditLog]] = relationship(back_populates="actor")
    settings_updated: Mapped[list[Setting]] = relationship(back_populates="updated_by")


class Role(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(80), unique=True)
    description: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    user_links: Mapped[list[UserRole]] = relationship(back_populates="role")


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_user_roles_user_role"),)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    role_id: Mapped[UUID] = mapped_column(ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True)

    user: Mapped[User] = relationship(back_populates="role_links")
    role: Mapped[Role] = relationship(back_populates="user_links")
