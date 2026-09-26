"""Phase 11B additive schema. Frozen v1/v2/v3 snapshots are never mutated.

Three append-only evidence tables record an EXTERNAL marketplace cancellation:
the customer refund the marketplace already completed, the marketplace's final
cancellation statement, and the invariant-checked reconciliation. None of them
represents money sent by this system.
"""
import sqlalchemy as sa
from . import schema_v3 as v3

metadata = sa.MetaData()
for _name, _value in list(vars(v3).items()):
    # Skip v3's leaked loop variable; the same Table is also bound to its public name.
    if isinstance(_value, sa.Table) and not _name.startswith("_"):
        globals()[_name] = _value.to_metadata(metadata)
c, ref, now, uid = v3.c, v3.ref, v3.now, v3.uid


def table(name, *columns):
    return sa.Table(name, metadata,
        c("id", sa.String(36), primary_key=True, default=uid),
        c("created_at", sa.DateTime(timezone=True), nullable=False, default=now), *columns)


def identity():
    # A copy of the marketplace line identity at recording time; compared again on completion.
    return (c("marketplace", sa.String(24), nullable=False), c("external_order_id", sa.String(100), nullable=False),
            c("external_line_id", sa.String(100), nullable=False))


marketplace_refund_evidence = table("marketplace_refund_evidence",
    ref("review_id", "reviews", nullable=False, unique=True), ref("order_id", "orders", nullable=False, unique=True),
    ref("supplier_recovery_id", "supplier_cancellation_recoveries", nullable=False, unique=True), *identity(),
    c("amount", sa.BigInteger, nullable=False), c("reference", sa.String(160), nullable=False),
    c("evidence_hash", sa.String(64), nullable=False, unique=True), c("snapshot_hash", sa.String(64), nullable=False),
    c("payload_hash", sa.String(64), nullable=False), c("actor", sa.String(80), nullable=False),
    c("recorded_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("marketplace", "reference", name="uq_marketplace_refund_reference"),
    sa.CheckConstraint("amount > 0", name="ck_marketplace_refund_positive"))

marketplace_cancellation_statements = table("marketplace_cancellation_statements",
    ref("review_id", "reviews", nullable=False, unique=True), ref("order_id", "orders", nullable=False, unique=True),
    ref("refund_evidence_id", "marketplace_refund_evidence", nullable=False, unique=True), *identity(),
    c("customer_refund_amount", sa.BigInteger, nullable=False), c("seller_payout_amount", sa.BigInteger, nullable=False),
    c("seller_debit_amount", sa.BigInteger, nullable=False), c("retained_fee_amount", sa.BigInteger, nullable=False),
    c("outstanding_balance", sa.BigInteger, nullable=False), c("classification", sa.String(40), nullable=False),
    c("reference", sa.String(160), nullable=False), c("evidence_hash", sa.String(64), nullable=False, unique=True),
    c("snapshot_hash", sa.String(64), nullable=False), c("payload_hash", sa.String(64), nullable=False),
    c("actor", sa.String(80), nullable=False), c("recorded_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("marketplace", "reference", name="uq_marketplace_statement_reference"),
    sa.CheckConstraint("customer_refund_amount > 0 AND seller_payout_amount >= 0 AND seller_debit_amount >= 0 "
                       "AND retained_fee_amount >= 0 AND outstanding_balance >= 0", name="ck_marketplace_statement_amounts"),
    sa.CheckConstraint("classification IN ('ZERO_SELLER_SETTLEMENT','UNSUPPORTED_RESIDUAL_SETTLEMENT')",
                       name="ck_marketplace_statement_classification"))

marketplace_cancellation_reconciliations = table("marketplace_cancellation_reconciliations",
    ref("review_id", "reviews", nullable=False, unique=True), ref("order_id", "orders", nullable=False, unique=True),
    ref("refund_evidence_id", "marketplace_refund_evidence", nullable=False, unique=True),
    ref("statement_id", "marketplace_cancellation_statements", nullable=False, unique=True),
    ref("supplier_recovery_id", "supplier_cancellation_recoveries", nullable=False, unique=True),
    ref("payment_id", "payments", nullable=False, unique=True),
    c("customer_refund_amount", sa.BigInteger, nullable=False), c("order_state_before", sa.String(32), nullable=False),
    c("order_state_after", sa.String(32), nullable=False), c("snapshot_hash", sa.String(64), nullable=False),
    c("payload_hash", sa.String(64), nullable=False), c("actor", sa.String(80), nullable=False),
    c("completed_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("order_state_before = 'CANCEL_REQUESTED' AND order_state_after = 'CANCELLED'",
                       name="ck_marketplace_reconciliation_transition"))

PHASE11B_TABLES = (marketplace_refund_evidence, marketplace_cancellation_statements, marketplace_cancellation_reconciliations)
APPEND_ONLY_TABLES = tuple(t.name for t in PHASE11B_TABLES)
