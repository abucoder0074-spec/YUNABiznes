"""Create the v0.1 inventory, purchasing, ledger, and audit schema.

Revision ID: 20260907_0001
Revises:
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260907_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.Column[object]:
    return sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False)


def _timestamps() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )


def upgrade() -> None:
    document_status = sa.Enum(
        "DRAFT", "POSTED", "VOID", name="document_status", native_enum=False, create_constraint=True
    )
    payment_method = sa.Enum(
        "CASH", "BANK_TRANSFER", "CARD", "OTHER", name="payment_method", native_enum=False, create_constraint=True
    )
    inventory_type = sa.Enum(
        "PURCHASE_IN", "PRODUCTION_OUT", "SUPPLIER_RETURN_OUT", "PURCHASE_RETURN_IN",
        "ADJUSTMENT_IN", "ADJUSTMENT_OUT", "TRANSFER_OUT", "TRANSFER_IN",
        name="inventory_transaction_type", native_enum=False, create_constraint=True,
    )
    ledger_type = sa.Enum(
        "PURCHASE_DEBIT", "PAYMENT_CREDIT", "RETURN_CREDIT", "ADJUSTMENT_DEBIT", "ADJUSTMENT_CREDIT",
        name="supplier_ledger_entry_type", native_enum=False, create_constraint=True,
    )
    money = sa.Numeric(18, 2)
    quantity = sa.Numeric(18, 4)

    op.create_table(
        "users",
        _id(),
        sa.Column("username", sa.String(80), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=True, unique=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        *_timestamps(),
    )
    op.create_index("ix_users_username", "users", ["username"])
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "roles",
        _id(),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("description", sa.String(500)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        *_timestamps(),
    )
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("role_id", sa.Uuid(as_uuid=True), sa.ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True),
        sa.UniqueConstraint("user_id", "role_id", name="uq_user_roles_user_role"),
    )

    op.create_table(
        "units",
        _id(),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("symbol", sa.String(20), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        *_timestamps(),
    )
    op.create_table(
        "warehouses",
        _id(),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("code", sa.String(80), unique=True),
        sa.Column("location", sa.String(500)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notes", sa.Text()),
        *_timestamps(),
    )
    op.create_table(
        "suppliers",
        _id(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("code", sa.String(80), unique=True),
        sa.Column("tax_id", sa.String(80), unique=True),
        sa.Column("phone", sa.String(80)),
        sa.Column("email", sa.String(255)),
        sa.Column("address", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notes", sa.Text()),
        *_timestamps(),
    )
    op.create_index("ix_suppliers_name", "suppliers", ["name"])
    op.create_table(
        "products",
        _id(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("code", sa.String(80), unique=True),
        sa.Column("unit_id", sa.Uuid(as_uuid=True), sa.ForeignKey("units.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("minimum_stock", quantity),
        sa.Column("safety_stock", quantity),
        sa.Column("notes", sa.Text()),
        *_timestamps(),
        sa.CheckConstraint("minimum_stock IS NULL OR minimum_stock >= 0", name="ck_products_minimum_stock"),
        sa.CheckConstraint("safety_stock IS NULL OR safety_stock >= 0", name="ck_products_safety_stock"),
    )
    op.create_index("ix_products_name", "products", ["name"])
    op.create_index("ix_products_unit_id", "products", ["unit_id"])

    op.create_table(
        "purchases",
        _id(),
        sa.Column("number", sa.String(80), nullable=False, unique=True),
        sa.Column("supplier_id", sa.Uuid(as_uuid=True), sa.ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(as_uuid=True), sa.ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("purchased_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("status", document_status, nullable=False, server_default=sa.text("'DRAFT'")),
        sa.Column("currency", sa.String(3), nullable=False, server_default=sa.text("'UZS'")),
        sa.Column("notes", sa.Text()),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        *_timestamps(),
    )
    op.create_index("ix_purchases_supplier_id", "purchases", ["supplier_id"])
    op.create_index("ix_purchases_warehouse_id", "purchases", ["warehouse_id"])
    op.create_index("ix_purchases_purchased_at", "purchases", ["purchased_at"])
    op.create_index("ix_purchases_supplier_date", "purchases", ["supplier_id", "purchased_at"])
    op.create_table(
        "purchase_items",
        _id(),
        sa.Column("purchase_id", sa.Uuid(as_uuid=True), sa.ForeignKey("purchases.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("product_id", sa.Uuid(as_uuid=True), sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("unit_id", sa.Uuid(as_uuid=True), sa.ForeignKey("units.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("quantity", quantity, nullable=False),
        sa.Column("unit_price", money, nullable=False),
        sa.Column("total", money, sa.Computed("quantity * unit_price", persisted=True)),
        sa.Column("notes", sa.Text()),
        *_timestamps(),
        sa.CheckConstraint("quantity > 0", name="ck_purchase_items_quantity_positive"),
        sa.CheckConstraint("unit_price >= 0", name="ck_purchase_items_unit_price_nonnegative"),
    )
    op.create_index("ix_purchase_items_purchase_id", "purchase_items", ["purchase_id"])
    op.create_index("ix_purchase_items_product", "purchase_items", ["product_id"])

    op.create_table(
        "payments",
        _id(),
        sa.Column("number", sa.String(80), nullable=False, unique=True),
        sa.Column("supplier_id", sa.Uuid(as_uuid=True), sa.ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("amount", money, nullable=False),
        sa.Column("method", payment_method, nullable=False),
        sa.Column("status", document_status, nullable=False, server_default=sa.text("'DRAFT'")),
        sa.Column("reference_number", sa.String(120)),
        sa.Column("notes", sa.Text()),
        sa.Column("created_by_user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        *_timestamps(),
        sa.CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
    )
    op.create_index("ix_payments_supplier_id", "payments", ["supplier_id"])
    op.create_index("ix_payments_paid_at", "payments", ["paid_at"])
    op.create_index("ix_payments_supplier_date", "payments", ["supplier_id", "paid_at"])
    op.create_table(
        "payment_allocations",
        _id(),
        sa.Column("payment_id", sa.Uuid(as_uuid=True), sa.ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("purchase_id", sa.Uuid(as_uuid=True), sa.ForeignKey("purchases.id", ondelete="RESTRICT")),
        sa.Column("amount", money, nullable=False),
        sa.Column("notes", sa.Text()),
        *_timestamps(),
        sa.CheckConstraint("amount > 0", name="ck_payment_allocations_amount_positive"),
    )
    op.create_index("ix_payment_allocations_payment_id", "payment_allocations", ["payment_id"])
    op.create_index("ix_payment_allocations_purchase", "payment_allocations", ["purchase_id"])

    op.create_table(
        "production_issues",
        _id(),
        sa.Column("number", sa.String(80), nullable=False, unique=True),
        sa.Column("warehouse_id", sa.Uuid(as_uuid=True), sa.ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("status", document_status, nullable=False, server_default=sa.text("'DRAFT'")),
        sa.Column("notes", sa.Text()),
        sa.Column("issued_by_user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index("ix_production_issues_warehouse_id", "production_issues", ["warehouse_id"])
    op.create_index("ix_production_issues_issued_at", "production_issues", ["issued_at"])
    op.create_index("ix_production_issues_warehouse_date", "production_issues", ["warehouse_id", "issued_at"])
    op.create_table(
        "production_issue_items",
        _id(),
        sa.Column("production_issue_id", sa.Uuid(as_uuid=True), sa.ForeignKey("production_issues.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("product_id", sa.Uuid(as_uuid=True), sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("unit_id", sa.Uuid(as_uuid=True), sa.ForeignKey("units.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("quantity", quantity, nullable=False),
        sa.Column("notes", sa.Text()),
        *_timestamps(),
        sa.CheckConstraint("quantity > 0", name="ck_production_issue_items_quantity_positive"),
    )
    op.create_index("ix_production_issue_items_production_issue_id", "production_issue_items", ["production_issue_id"])
    op.create_index("ix_production_issue_items_product", "production_issue_items", ["product_id"])

    op.create_table(
        "returns",
        _id(),
        sa.Column("number", sa.String(80), nullable=False, unique=True),
        sa.Column("supplier_id", sa.Uuid(as_uuid=True), sa.ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(as_uuid=True), sa.ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("status", document_status, nullable=False, server_default=sa.text("'DRAFT'")),
        sa.Column("notes", sa.Text()),
        sa.Column("authorized_by_user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index("ix_returns_supplier_id", "returns", ["supplier_id"])
    op.create_index("ix_returns_warehouse_id", "returns", ["warehouse_id"])
    op.create_index("ix_returns_returned_at", "returns", ["returned_at"])
    op.create_index("ix_returns_supplier_date", "returns", ["supplier_id", "returned_at"])
    op.create_table(
        "return_items",
        _id(),
        sa.Column("return_id", sa.Uuid(as_uuid=True), sa.ForeignKey("returns.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("purchase_item_id", sa.Uuid(as_uuid=True), sa.ForeignKey("purchase_items.id", ondelete="RESTRICT")),
        sa.Column("product_id", sa.Uuid(as_uuid=True), sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("unit_id", sa.Uuid(as_uuid=True), sa.ForeignKey("units.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("quantity", quantity, nullable=False),
        sa.Column("unit_price", money, nullable=False),
        sa.Column("total", money, sa.Computed("quantity * unit_price", persisted=True)),
        sa.Column("notes", sa.Text()),
        *_timestamps(),
        sa.CheckConstraint("quantity > 0", name="ck_return_items_quantity_positive"),
        sa.CheckConstraint("unit_price >= 0", name="ck_return_items_unit_price_nonnegative"),
    )
    op.create_index("ix_return_items_return_id", "return_items", ["return_id"])
    op.create_index("ix_return_items_purchase_item_id", "return_items", ["purchase_item_id"])
    op.create_index("ix_return_items_product", "return_items", ["product_id"])

    op.create_table(
        "inventory_transactions",
        _id(),
        sa.Column("transaction_type", inventory_type, nullable=False),
        sa.Column("product_id", sa.Uuid(as_uuid=True), sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("unit_id", sa.Uuid(as_uuid=True), sa.ForeignKey("units.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(as_uuid=True), sa.ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("quantity", quantity, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("source_document_type", sa.String(80), nullable=False),
        sa.Column("source_document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("performed_by_user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("reason", sa.Text()),
        sa.Column("note", sa.Text()),
        sa.CheckConstraint("quantity > 0", name="ck_inventory_transactions_quantity_positive"),
    )
    op.create_index("ix_inventory_transactions_transaction_type", "inventory_transactions", ["transaction_type"])
    op.create_index("ix_inventory_transactions_product_id", "inventory_transactions", ["product_id"])
    op.create_index("ix_inventory_transactions_warehouse_id", "inventory_transactions", ["warehouse_id"])
    op.create_index("ix_inventory_transactions_occurred_at", "inventory_transactions", ["occurred_at"])
    op.create_index("ix_inventory_balance_lookup", "inventory_transactions", ["warehouse_id", "product_id", "occurred_at"])
    op.create_index("ix_inventory_transactions_source", "inventory_transactions", ["source_document_type", "source_document_id"])

    op.create_table(
        "supplier_ledger",
        _id(),
        sa.Column("supplier_id", sa.Uuid(as_uuid=True), sa.ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("entry_type", ledger_type, nullable=False),
        sa.Column("debit_amount", money, nullable=False, server_default=sa.text("0")),
        sa.Column("credit_amount", money, nullable=False, server_default=sa.text("0")),
        sa.Column("currency", sa.String(3), nullable=False, server_default=sa.text("'UZS'")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("purchase_id", sa.Uuid(as_uuid=True), sa.ForeignKey("purchases.id", ondelete="RESTRICT")),
        sa.Column("payment_id", sa.Uuid(as_uuid=True), sa.ForeignKey("payments.id", ondelete="RESTRICT")),
        sa.Column("return_id", sa.Uuid(as_uuid=True), sa.ForeignKey("returns.id", ondelete="RESTRICT")),
        sa.Column("source_document_type", sa.String(80), nullable=False),
        sa.Column("source_document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("created_by_user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.CheckConstraint("debit_amount >= 0", name="ck_supplier_ledger_debit_nonnegative"),
        sa.CheckConstraint("credit_amount >= 0", name="ck_supplier_ledger_credit_nonnegative"),
        sa.CheckConstraint(
            "(debit_amount > 0 AND credit_amount = 0) OR (credit_amount > 0 AND debit_amount = 0)",
            name="ck_supplier_ledger_one_sided_entry",
        ),
    )
    op.create_index("ix_supplier_ledger_supplier_id", "supplier_ledger", ["supplier_id"])
    op.create_index("ix_supplier_ledger_occurred_at", "supplier_ledger", ["occurred_at"])
    op.create_index("ix_supplier_ledger_supplier_date", "supplier_ledger", ["supplier_id", "occurred_at"])

    op.create_table(
        "audit_logs",
        _id(),
        sa.Column("actor_user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("entity_type", sa.String(80), nullable=False),
        sa.Column("entity_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("old_values", sa.JSON()),
        sa.Column("new_values", sa.JSON()),
        sa.Column("reason", sa.Text()),
    )
    op.create_index("ix_audit_logs_occurred_at", "audit_logs", ["occurred_at"])
    op.create_index("ix_audit_logs_entity", "audit_logs", ["entity_type", "entity_id"])
    op.create_index("ix_audit_logs_actor_time", "audit_logs", ["actor_user_id", "occurred_at"])
    op.create_table(
        "settings",
        _id(),
        sa.Column("key", sa.String(120), nullable=False, unique=True),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("updated_by_user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        *_timestamps(),
    )


def downgrade() -> None:
    op.drop_table("settings")
    op.drop_table("audit_logs")
    op.drop_table("supplier_ledger")
    op.drop_table("inventory_transactions")
    op.drop_table("return_items")
    op.drop_table("returns")
    op.drop_table("production_issue_items")
    op.drop_table("production_issues")
    op.drop_table("payment_allocations")
    op.drop_table("payments")
    op.drop_table("purchase_items")
    op.drop_table("purchases")
    op.drop_table("products")
    op.drop_table("suppliers")
    op.drop_table("warehouses")
    op.drop_table("units")
    op.drop_table("user_roles")
    op.drop_table("roles")
    op.drop_table("users")
