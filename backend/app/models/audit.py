"""Audit trail and application settings models."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.identity import User


class AuditLog(UUIDPrimaryKeyMixin, Base):
    """Append-only record of a consequential business-data modification."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_actor_time", "actor_user_id", "occurred_at"),
    )

    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    action: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    old_values: Mapped[dict[str, object] | None] = mapped_column(JSON)
    new_values: Mapped[dict[str, object] | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text)

    actor: Mapped[User | None] = relationship(back_populates="audit_logs")


class Setting(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(120), unique=True)
    value: Mapped[dict[str, object]] = mapped_column(JSON)
    description: Mapped[str | None] = mapped_column(Text)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))

    updated_by: Mapped[User | None] = relationship(back_populates="settings_updated")
