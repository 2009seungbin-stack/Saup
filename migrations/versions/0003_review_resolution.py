"""Append-only evidence correction and bounded supplier cancellation recovery."""
from alembic import op
import sqlalchemy as sa
from packages.infrastructure.schema_v3 import PHASE11_TABLES, APPEND_ONLY_TABLES

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    for table in PHASE11_TABLES:
        table.create(bind, checkfirst=False)
    for table in APPEND_ONLY_TABLES:
        if bind.dialect.name == "postgresql":
            op.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION saup_append_only()")
        elif bind.dialect.name == "sqlite":
            for action in ("UPDATE", "DELETE"):
                op.execute(f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_RECORD'); END")


def downgrade():
    bind = op.get_bind()
    for table in PHASE11_TABLES:
        if bind.execute(sa.select(sa.func.count()).select_from(table)).scalar():
            raise RuntimeError("PHASE11_DATA_PRESENT_DOWNGRADE_BLOCKED")
    # A correction request alone is a safety hold; an older application would
    # ignore it. Do not downgrade even when no correction was applied yet.
    count = bind.execute(sa.text("SELECT count(*) FROM reviews WHERE category IN "
        "('SUPPLIER_PAYMENT_EVIDENCE_CORRECTION','MARKETPLACE_CANCELLATION_RECONCILIATION_REQUIRED')")).scalar()
    if count:
        raise RuntimeError("PHASE11_REVIEW_PRESENT_DOWNGRADE_BLOCKED")
    for table in reversed(PHASE11_TABLES):
        table.drop(bind, checkfirst=False)
