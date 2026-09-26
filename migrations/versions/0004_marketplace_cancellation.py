"""Append-only customer/marketplace cancellation evidence and reconciliation."""
from alembic import op
import sqlalchemy as sa
from packages.infrastructure.schema_v4 import PHASE11B_TABLES, APPEND_ONLY_TABLES

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    for table in PHASE11B_TABLES:
        table.create(bind, checkfirst=False)
    for table in APPEND_ONLY_TABLES:
        if bind.dialect.name == "postgresql":
            op.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION saup_append_only()")
        elif bind.dialect.name == "sqlite":
            for action in ("UPDATE", "DELETE"):
                op.execute(f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_RECORD'); END")


def downgrade():
    bind = op.get_bind()
    # These rows are the only local proof of an external refund/cancellation and
    # an Order may already be CANCELLED because of them. Never drop them.
    for table in PHASE11B_TABLES:
        if bind.execute(sa.select(sa.func.count()).select_from(table)).scalar():
            raise RuntimeError("PHASE11B_DATA_PRESENT_DOWNGRADE_BLOCKED")
    # A held later line is protected only by Phase 11B application code.
    count = bind.execute(sa.text("SELECT count(*) FROM reviews WHERE category IN "
        "('MARKETPLACE_CANCELLATION_RESIDUAL_SETTLEMENT','MARKETPLACE_LINE_AFTER_CANCELLATION_EVIDENCE')")).scalar()
    if count:
        raise RuntimeError("PHASE11B_REVIEW_PRESENT_DOWNGRADE_BLOCKED")
    for table in reversed(PHASE11B_TABLES):
        table.drop(bind, checkfirst=False)
