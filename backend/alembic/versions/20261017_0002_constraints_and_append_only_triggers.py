"""Align the schema with the models and enforce append-only tables inside PostgreSQL.

Migration 20260907_0001 missed three constraints that the models declare, and the ORM-only
append-only guard can be bypassed by bulk SQL. This revision adds both protections.

Revision ID: 20261017_0002
Revises: 20260907_0001
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261017_0002"
down_revision: str | None = "20260907_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPEND_ONLY_TABLES = ("inventory_transactions", "supplier_ledger", "audit_logs")

LEDGER_REFERENCE_CHECK = (
    "(entry_type = 'PURCHASE_DEBIT' AND purchase_id IS NOT NULL "
    "AND payment_id IS NULL AND return_id IS NULL) OR "
    "(entry_type = 'PAYMENT_CREDIT' AND payment_id IS NOT NULL "
    "AND purchase_id IS NULL AND return_id IS NULL) OR "
    "(entry_type = 'RETURN_CREDIT' AND return_id IS NOT NULL "
    "AND purchase_id IS NULL AND payment_id IS NULL) OR "
    "(entry_type IN ('ADJUSTMENT_DEBIT', 'ADJUSTMENT_CREDIT') "
    "AND purchase_id IS NULL AND payment_id IS NULL AND return_id IS NULL)"
)


def upgrade() -> None:
    op.create_check_constraint(
        "ck_inventory_adjustments_require_reason",
        "inventory_transactions",
        "transaction_type NOT IN ('ADJUSTMENT_IN', 'ADJUSTMENT_OUT') "
        "OR (reason IS NOT NULL AND length(trim(reason)) > 0)",
    )
    op.create_check_constraint(
        "ck_supplier_ledger_entry_reference", "supplier_ledger", LEDGER_REFERENCE_CHECK
    )
    op.create_index(
        "uq_payment_allocations_general_payment",
        "payment_allocations",
        ["payment_id"],
        unique=True,
        postgresql_where=sa.text("purchase_id IS NULL"),
    )

    op.execute(
        """
        CREATE FUNCTION forbid_append_only_change() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only; % is not allowed', TG_TABLE_NAME, TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in APPEND_ONLY_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_append_only_change()"
        )
        op.execute(
            f"CREATE TRIGGER trg_{table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION forbid_append_only_change()"
        )


def downgrade() -> None:
    for table in APPEND_ONLY_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_truncate ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS forbid_append_only_change()")
    op.drop_index("uq_payment_allocations_general_payment", table_name="payment_allocations")
    op.drop_constraint("ck_supplier_ledger_entry_reference", "supplier_ledger", type_="check")
    op.drop_constraint(
        "ck_inventory_adjustments_require_reason", "inventory_transactions", type_="check"
    )
