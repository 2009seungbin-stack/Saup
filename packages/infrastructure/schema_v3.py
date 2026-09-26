"""Phase 11A additive schema. Frozen v1/v2 snapshots are never mutated."""
import sqlalchemy as sa
from . import schema_v2 as v2

metadata = sa.MetaData()
for _name, _value in vars(v2).items():
    if isinstance(_value, sa.Table):
        globals()[_name] = _value.to_metadata(metadata)
c, ref, now, uid = v2.c, v2.ref, v2.now, v2.uid


def table(name, *columns):
    return sa.Table(name, metadata,
        c("id", sa.String(36), primary_key=True, default=uid),
        c("created_at", sa.DateTime(timezone=True), nullable=False, default=now), *columns)


evidence_revisions = table("supplier_payment_evidence_revisions",
    ref("evidence_id", "supplier_payment_evidence", nullable=False),
    ref("review_id", "reviews", nullable=False, unique=True),
    ref("supersedes_id", "supplier_payment_evidence_revisions", unique=True),
    c("revision", sa.Integer, nullable=False),
    c("reference", sa.String(160), nullable=False), c("evidence_hash", sa.String(64), nullable=False),
    c("reason", sa.String(40), nullable=False), c("payload_hash", sa.String(64), nullable=False),
    c("actor", sa.String(80), nullable=False), c("recorded_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("evidence_id", "revision", name="uq_evidence_revision"),
    sa.CheckConstraint("revision > 0", name="ck_evidence_revision_positive"))

evidence_confirmation_bindings = table("supplier_evidence_confirmation_bindings",
    ref("confirmation_id", "supplier_payment_confirmations", nullable=False, unique=True),
    ref("revision_id", "supplier_payment_evidence_revisions", nullable=False, unique=True))

cancellation_recoveries = table("supplier_cancellation_recoveries",
    ref("cancellation_id", "supplier_cancellations", nullable=False, unique=True),
    ref("payment_id", "payments", nullable=False, unique=True),
    ref("supplier_id", "suppliers", nullable=False), ref("journal_id", "journals", nullable=False, unique=True),
    c("amount", sa.BigInteger, nullable=False), c("bank_amount", sa.BigInteger, nullable=False),
    c("deposit_amount", sa.BigInteger, nullable=False), c("destination_fingerprint", sa.String(64), nullable=False),
    c("reference", sa.String(160), nullable=False), c("evidence_hash", sa.String(64), nullable=False, unique=True),
    c("payload_hash", sa.String(64), nullable=False), c("actor", sa.String(80), nullable=False),
    c("confirmed_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("supplier_id", "reference", name="uq_cancellation_recovery_receipt"),
    sa.CheckConstraint("amount > 0 AND bank_amount >= 0 AND deposit_amount >= 0 AND amount = bank_amount + deposit_amount",
                       name="ck_cancellation_recovery_amount"))

review_resolutions = table("review_resolutions",
    ref("review_id", "reviews", nullable=False), c("business_key", sa.String(240), nullable=False, unique=True),
    c("action", sa.String(80), nullable=False), c("payload_hash", sa.String(64), nullable=False),
    c("actor", sa.String(80), nullable=False), c("resolved_at", sa.DateTime(timezone=True), nullable=False),
    c("result", sa.JSON, nullable=False))

PHASE11_TABLES = (evidence_revisions, evidence_confirmation_bindings, cancellation_recoveries, review_resolutions)
APPEND_ONLY_TABLES = tuple(t.name for t in PHASE11_TABLES)
