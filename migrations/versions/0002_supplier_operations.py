"""Explicit, evidentiary Excel supplier lifecycle; preserve migration 0001 verbatim."""
from alembic import op
import sqlalchemy as sa
from packages.infrastructure.schema_v2 import PHASE10_TABLES, APPEND_ONLY_TABLES
from packages.infrastructure.schema_v1 import uid, now

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    for name, kind in (("resolution_code", sa.String(80)), ("resolved_by", sa.String(80)),
                       ("resolved_at", sa.DateTime(timezone=True))):
        op.add_column("reviews", sa.Column(name, kind, nullable=True))
    for table in PHASE10_TABLES:
        table.create(bind, checkfirst=False)
    for table in APPEND_ONLY_TABLES:
        if bind.dialect.name == "postgresql":
            op.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION saup_append_only()")
        elif bind.dialect.name == "sqlite":
            for action in ("UPDATE", "DELETE"):
                op.execute(f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_RECORD'); END")
    # Historic FILE_READY meant export-eligible, NOT known-unsent. Do not invent
    # a frozen intent or release a possibly externally accepted legacy order.
    rows = bind.execute(sa.text("""SELECT so.id, so.order_id FROM supplier_orders so
        JOIN orders o ON o.id=so.order_id JOIN listings l ON l.id=o.listing_id
        JOIN supplier_products sp ON sp.id=l.supplier_product_id JOIN suppliers su ON su.id=sp.supplier_id
        WHERE su.mode='excel' AND so.status NOT IN ('CANCELLED','REJECTED')""")).fetchall()
    from packages.infrastructure.schema_v2 import reviews, audit
    for so_id, order_id in rows:
        bind.execute(sa.text("UPDATE supplier_orders SET status='MANUAL_REVIEW' WHERE id=:id"), {"id": so_id})
        bind.execute(reviews.insert().values(id=uid(), category="LEGACY_SUPPLIER_STATE_UNVERIFIED", entity_id=so_id,
            dedupe_key=f"LEGACY_SUPPLIER_STATE_UNVERIFIED:{so_id}", details={"order_id": order_id}, status="OPEN"))
        bind.execute(audit.insert().values(id=uid(), actor="migration:0002", event="SUPPLIER_LEGACY_REVIEW_REQUIRED",
            entity_id=so_id, old_value={}, new_value={"order_id": order_id}, reason="UNKNOWN_EXTERNAL_STATE",
            source="migration", correlation_id=uid()))


def downgrade():
    bind = op.get_bind()
    # Production downgrade is destructive and cannot reconstruct evidentiary history.
    for table in reversed(PHASE10_TABLES):
        if bind.execute(sa.select(sa.func.count()).select_from(table)).scalar():
            raise RuntimeError("PHASE10_DATA_PRESENT_DOWNGRADE_BLOCKED")
    for table in reversed(PHASE10_TABLES):
        table.drop(bind, checkfirst=False)
    for name in ("resolved_at", "resolved_by", "resolution_code"):
        op.drop_column("reviews", name)
