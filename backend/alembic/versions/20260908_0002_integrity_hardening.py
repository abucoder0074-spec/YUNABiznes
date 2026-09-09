"""Add PostgreSQL protections for posted documents and accounting invariants.

Revision ID: 20260908_0002
Revises: 20260907_0001
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260908_0002"
down_revision: str | None = "20260907_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_immutable_event() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Immutable accounting or inventory events cannot be changed';
        END;
        $$;

        CREATE OR REPLACE FUNCTION reject_posted_document() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' OR OLD.status = 'POSTED' THEN
                RAISE EXCEPTION 'Posted documents are immutable; use a reversal or correction';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE OR REPLACE FUNCTION reject_posted_purchase_item() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM purchases
                WHERE id = COALESCE(NEW.purchase_id, OLD.purchase_id) AND status = 'POSTED'
            ) THEN
                RAISE EXCEPTION 'Items of posted purchases are immutable';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE OR REPLACE FUNCTION reject_posted_return_item() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM returns
                WHERE id = COALESCE(NEW.return_id, OLD.return_id) AND status = 'POSTED'
            ) THEN
                RAISE EXCEPTION 'Items of posted returns are immutable';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE OR REPLACE FUNCTION reject_posted_issue_item() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM production_issues
                WHERE id = COALESCE(NEW.production_issue_id, OLD.production_issue_id) AND status = 'POSTED'
            ) THEN
                RAISE EXCEPTION 'Items of posted production issues are immutable';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE OR REPLACE FUNCTION validate_payment_allocation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            payment_supplier uuid;
            payment_status text;
            purchase_supplier uuid;
            purchase_status text;
            payment_total numeric;
            purchase_total numeric;
            returned_total numeric;
            allocated_payment numeric;
            allocated_purchase numeric;
        BEGIN
            SELECT supplier_id, status::text INTO payment_supplier, payment_status
            FROM payments WHERE id = NEW.payment_id FOR UPDATE;
            IF payment_supplier IS NULL THEN
                RAISE EXCEPTION 'Payment does not exist';
            END IF;
            IF payment_status = 'POSTED' THEN
                RAISE EXCEPTION 'Allocations of posted payments are immutable';
            END IF;
            SELECT amount INTO payment_total FROM payments WHERE id = NEW.payment_id;
            SELECT COALESCE(SUM(amount), 0) INTO allocated_payment
            FROM payment_allocations WHERE payment_id = NEW.payment_id;
            IF allocated_payment > payment_total THEN
                RAISE EXCEPTION 'Payment allocations exceed payment amount';
            END IF;
            IF NEW.purchase_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT supplier_id, status::text INTO purchase_supplier, purchase_status
            FROM purchases WHERE id = NEW.purchase_id FOR UPDATE;
            IF purchase_supplier IS NULL OR purchase_status <> 'POSTED' THEN
                RAISE EXCEPTION 'Allocations require an existing posted purchase';
            END IF;
            IF purchase_supplier <> payment_supplier THEN
                RAISE EXCEPTION 'Payment and purchase suppliers must match';
            END IF;

            SELECT COALESCE(SUM(total), 0) INTO purchase_total
            FROM purchase_items WHERE purchase_id = NEW.purchase_id;
            SELECT COALESCE(SUM(ri.total), 0) INTO returned_total
            FROM return_items ri
            JOIN returns r ON r.id = ri.return_id
            JOIN purchase_items pi ON pi.id = ri.purchase_item_id
            WHERE pi.purchase_id = NEW.purchase_id AND r.status = 'POSTED';
            SELECT COALESCE(SUM(amount), 0) INTO allocated_purchase
            FROM payment_allocations WHERE purchase_id = NEW.purchase_id;

            IF allocated_purchase > purchase_total - returned_total THEN
                RAISE EXCEPTION 'Payment allocations exceed purchase outstanding amount';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE OR REPLACE FUNCTION reject_posted_payment_allocation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF EXISTS (SELECT 1 FROM payments WHERE id = OLD.payment_id AND status = 'POSTED') THEN
                RAISE EXCEPTION 'Allocations of posted payments are immutable';
            END IF;
            RETURN OLD;
        END;
        $$;

        CREATE OR REPLACE FUNCTION validate_supplier_ledger_reference() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE referenced_supplier uuid;
        BEGIN
            IF NEW.purchase_id IS NOT NULL THEN
                SELECT supplier_id INTO referenced_supplier FROM purchases WHERE id = NEW.purchase_id;
            ELSIF NEW.payment_id IS NOT NULL THEN
                SELECT supplier_id INTO referenced_supplier FROM payments WHERE id = NEW.payment_id;
            ELSIF NEW.return_id IS NOT NULL THEN
                SELECT supplier_id INTO referenced_supplier FROM returns WHERE id = NEW.return_id;
            END IF;
            IF referenced_supplier IS NOT NULL AND NEW.supplier_id <> referenced_supplier THEN
                RAISE EXCEPTION 'Ledger supplier does not match its source document';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )

    for table in ("inventory_transactions", "supplier_ledger", "audit_logs"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable_trigger "
            f"BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_immutable_event()"
        )
    for table in ("purchases", "payments", "returns", "production_issues"):
        op.execute(
            f"CREATE TRIGGER {table}_posted_immutable_trigger "
            f"BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_posted_document()"
        )
    for table, function in (
        ("purchase_items", "reject_posted_purchase_item"),
        ("return_items", "reject_posted_return_item"),
        ("production_issue_items", "reject_posted_issue_item"),
    ):
        op.execute(
            f"CREATE TRIGGER {table}_posted_immutable_trigger "
            f"BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {function}()"
        )
    op.execute(
        """
        CREATE TRIGGER payment_allocations_validate_trigger
        AFTER INSERT OR UPDATE ON payment_allocations
        FOR EACH ROW EXECUTE FUNCTION validate_payment_allocation();
        CREATE TRIGGER payment_allocations_posted_immutable_trigger
        BEFORE DELETE ON payment_allocations
        FOR EACH ROW EXECUTE FUNCTION reject_posted_payment_allocation();
        CREATE TRIGGER supplier_ledger_reference_trigger
        BEFORE INSERT OR UPDATE ON supplier_ledger
        FOR EACH ROW EXECUTE FUNCTION validate_supplier_ledger_reference();
        """
    )


def downgrade() -> None:
    for table in (
        "inventory_transactions",
        "supplier_ledger",
        "audit_logs",
        "purchases",
        "payments",
        "returns",
        "production_issues",
        "purchase_items",
        "return_items",
        "production_issue_items",
        "payment_allocations",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable_trigger ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_posted_immutable_trigger ON {table}")
    op.execute("DROP TRIGGER IF EXISTS payment_allocations_validate_trigger ON payment_allocations")
    op.execute("DROP TRIGGER IF EXISTS supplier_ledger_reference_trigger ON supplier_ledger")
    op.execute(
        "DROP FUNCTION IF EXISTS validate_supplier_ledger_reference(), "
        "validate_payment_allocation(), reject_posted_issue_item(), "
        "reject_posted_return_item(), reject_posted_purchase_item(), "
        "reject_posted_payment_allocation(), reject_posted_document(), "
        "reject_immutable_event()"
    )
