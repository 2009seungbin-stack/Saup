"""Phase 10 runtime schema. v1 is copied, never mutated by importing this module.

Migration 0002 owns the evolution. Keep this snapshot stable once a later migration
is introduced, just as schema_v1 remains the immutable input to migration 0001.
"""
import sqlalchemy as sa
from . import schema_v1 as v1

metadata = sa.MetaData()
for _name, _value in vars(v1).items():
    if isinstance(_value, sa.Table):
        globals()[_name] = _value.to_metadata(metadata)

c, ref, now, uid = v1.c, v1.ref, v1.now, v1.uid

def table(name, *columns):
    return sa.Table(name, metadata,
        c("id", sa.String(36), primary_key=True, default=uid),
        c("created_at", sa.DateTime(timezone=True), nullable=False, default=now), *columns)

for _column in (
    c("resolution_code", sa.String(80)), c("resolved_by", sa.String(80)),
    c("resolved_at", sa.DateTime(timezone=True)),
):
    reviews.append_column(_column)

supplier_intents = table("supplier_order_intents",
    ref("supplier_order_id", "supplier_orders", nullable=False, unique=True),
    ref("supplier_id", "suppliers", nullable=False),
    c("amount", sa.BigInteger, nullable=False),
    c("snapshot", sa.JSON, nullable=False),
    c("snapshot_hash", sa.String(64), nullable=False),
    sa.UniqueConstraint("supplier_order_id", "supplier_id", name="uq_intent_order_supplier"),
    sa.CheckConstraint("amount > 0", name="ck_intent_amount"))

supplier_batches = table("supplier_order_batches",
    ref("supplier_id", "suppliers", nullable=False), ref("profile_id", "excel_profiles", nullable=False),
    c("profile_version", sa.Integer, nullable=False), c("profile_snapshot", sa.JSON, nullable=False),
    c("payment_path", sa.String(24), nullable=False),
    c("status", sa.String(24), nullable=False), c("order_count", sa.Integer, nullable=False),
    c("file_hash", sa.String(64), nullable=False), c("file_name", sa.String(100), nullable=False),
    c("file_ciphertext", sa.Text, nullable=False),
    c("generated_at", sa.DateTime(timezone=True), nullable=False), c("generated_by", sa.String(80), nullable=False),
    c("exported_at", sa.DateTime(timezone=True)), c("exported_by", sa.String(80)),
    c("sent_at", sa.DateTime(timezone=True)), c("sent_by", sa.String(80)),
    c("send_channel", sa.String(20)), c("send_reference", sa.String(160)), c("send_hash", sa.String(64)),
    c("acknowledged_at", sa.DateTime(timezone=True)), c("acknowledged_by", sa.String(80)),
    c("ack_reference", sa.String(160)),
    sa.UniqueConstraint("id", "supplier_id", name="uq_batch_supplier"),
    sa.CheckConstraint("order_count > 0 AND order_count <= 500", name="ck_batch_size"),
    sa.CheckConstraint("payment_path IN ('MANUAL_EVIDENCE','DEMO_PROVIDER')", name="ck_batch_payment_path"))

supplier_batch_items = table("supplier_order_batch_items",
    c("batch_id", sa.String(36), nullable=False), c("supplier_order_id", sa.String(36), nullable=False),
    c("supplier_id", sa.String(36), nullable=False),
    c("position", sa.Integer, nullable=False), c("active", sa.Boolean, nullable=False, default=True),
    c("row_ciphertext", sa.Text, nullable=False), c("snapshot_hash", sa.String(64), nullable=False),
    c("ack_status", sa.String(24), nullable=False, default="PENDING"),
    c("accepted_amount", sa.BigInteger), c("rejection_reason", sa.String(40)),
    sa.ForeignKeyConstraint(["batch_id", "supplier_id"], ["supplier_order_batches.id", "supplier_order_batches.supplier_id"]),
    sa.ForeignKeyConstraint(["supplier_order_id", "supplier_id"], ["supplier_order_intents.supplier_order_id", "supplier_order_intents.supplier_id"]),
    sa.UniqueConstraint("batch_id", "supplier_order_id", name="uq_batch_order"),
    sa.UniqueConstraint("batch_id", "position", name="uq_batch_position"),
    sa.Index("uq_active_supplier_batch_order", "supplier_order_id", unique=True,
             postgresql_where=sa.text("active"), sqlite_where=sa.text("active = 1")),
    sa.CheckConstraint("accepted_amount IS NULL OR accepted_amount > 0", name="ck_ack_amount"))

supplier_acknowledgements = table("supplier_batch_acknowledgements",
    ref("batch_id", "supplier_order_batches", nullable=False, unique=True),
    c("payload_hash", sa.String(64), nullable=False), c("payload", sa.JSON, nullable=False),
    c("reference", sa.String(160), nullable=False), c("actor", sa.String(80), nullable=False),
    c("recorded_at", sa.DateTime(timezone=True), nullable=False))

supplier_payment_evidence = table("supplier_payment_evidence",
    ref("payment_id", "payments", nullable=False, unique=True), ref("supplier_id", "suppliers", nullable=False),
    c("method", sa.String(32), nullable=False), c("amount", sa.BigInteger, nullable=False),
    c("bank_amount", sa.BigInteger, nullable=False), c("deposit_amount", sa.BigInteger, nullable=False),
    c("destination_fingerprint", sa.String(64), nullable=False),
    c("reference", sa.String(160), nullable=False), c("evidence_hash", sa.String(64), nullable=False),
    c("payload_hash", sa.String(64), nullable=False), c("recorded_by", sa.String(80), nullable=False),
    c("recorded_at", sa.DateTime(timezone=True), nullable=False),
    # Evidence is immutable; a separate immutable confirmation records admin attestation.
    sa.UniqueConstraint("supplier_id", "reference", name="uq_supplier_evidence_reference"),
    sa.CheckConstraint("amount > 0 AND bank_amount >= 0 AND deposit_amount >= 0 AND amount = bank_amount + deposit_amount", name="ck_evidence_amount"))

supplier_payment_confirmations = table("supplier_payment_confirmations",
    ref("evidence_id", "supplier_payment_evidence", nullable=False, unique=True),
    ref("payment_id", "payments", nullable=False, unique=True),
    c("payload_hash", sa.String(64), nullable=False), c("actor", sa.String(80), nullable=False),
    c("confirmed_at", sa.DateTime(timezone=True), nullable=False),
    c("amount", sa.BigInteger, nullable=False), c("destination_fingerprint", sa.String(64), nullable=False),
    c("reference", sa.String(160), nullable=False))

supplier_cancellations = table("supplier_cancellations",
    ref("supplier_order_id", "supplier_orders", nullable=False, unique=True),
    c("status", sa.String(32), nullable=False), c("from_state", sa.String(24), nullable=False),
    c("requested_by", sa.String(80), nullable=False), c("requested_at", sa.DateTime(timezone=True), nullable=False),
    c("confirmation_hash", sa.String(64)), c("confirmed_by", sa.String(80)),
    c("confirmed_at", sa.DateTime(timezone=True)), c("reference", sa.String(160)))

operational_interventions = table("operational_interventions",
    c("business_key", sa.String(240), nullable=False, unique=True),
    c("category", sa.String(64), nullable=False), c("actor", sa.String(80), nullable=False),
    ref("order_id", "orders"), ref("batch_id", "supplier_order_batches"),
    ref("supplier_id", "suppliers"), c("recorded_at", sa.DateTime(timezone=True), nullable=False))

PHASE10_TABLES = (
    supplier_intents, supplier_batches, supplier_batch_items, supplier_acknowledgements,
    supplier_payment_evidence, supplier_payment_confirmations, supplier_cancellations, operational_interventions,
)
APPEND_ONLY_TABLES = (
    "supplier_order_intents", "supplier_batch_acknowledgements", "supplier_payment_evidence",
    "supplier_payment_confirmations", "operational_interventions",
)
