"""Add payment posting timestamp.

Revision ID: 20260908_0003
Revises: 20260908_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260908_0003"
down_revision: str | None = "20260908_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("payments", "posted_at")
