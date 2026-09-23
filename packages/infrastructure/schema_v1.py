"""Frozen initial schema snapshot. Future releases add migrations, never edit this file."""
from datetime import datetime, timezone
from uuid import uuid4
import sqlalchemy as sa

metadata = sa.MetaData()

def now():
    return datetime.now(timezone.utc)

def uid():
    return str(uuid4())

def c(name, typ, **kw):
    return sa.Column(name, typ, **kw)

def ref(name, table, **kw):
    return sa.Column(name, sa.String(36), sa.ForeignKey(f"{table}.id"), **kw)

def table(name, *columns):
    return sa.Table(name, metadata,
        c("id", sa.String(36), primary_key=True, default=uid),
        c("created_at", sa.DateTime(timezone=True), nullable=False, default=now), *columns)

users = table("users", c("username", sa.String(80), nullable=False, unique=True),
    c("password_hash", sa.Text, nullable=False), c("role", sa.String(20), nullable=False),
    c("active", sa.Boolean, nullable=False, default=True),
    sa.CheckConstraint("role IN ('admin','operator','viewer')", name="ck_user_role"))
sessions = table("auth_sessions", ref("user_id", "users", nullable=False),
    c("token_hash", sa.String(64), nullable=False, unique=True),
    c("csrf_hash", sa.String(64), nullable=False), c("expires_at", sa.DateTime(timezone=True), nullable=False))
audit = table("audit_events", c("actor", sa.String(80), nullable=False),
    c("event", sa.String(80), nullable=False), c("entity_id", sa.String(160), nullable=False),
    c("old_value", sa.JSON, nullable=False, default=dict), c("new_value", sa.JSON, nullable=False, default=dict),
    c("reason", sa.String(160), nullable=False), c("source", sa.String(40), nullable=False),
    c("correlation_id", sa.String(36), nullable=False, index=True))
reviews = table("reviews", c("dedupe_key", sa.String(240), nullable=False, unique=True),
    c("category", sa.String(80), nullable=False), c("entity_id", sa.String(160), nullable=False),
    c("details", sa.JSON, nullable=False, default=dict), c("status", sa.String(24), nullable=False, default="OPEN"))
jobs = table("jobs", c("business_key", sa.String(240), nullable=False, unique=True),
    c("kind", sa.String(50), nullable=False), c("payload", sa.JSON, nullable=False),
    c("status", sa.String(24), nullable=False, default="PENDING"), c("attempts", sa.Integer, nullable=False, default=0),
    c("next_run_at", sa.DateTime(timezone=True), nullable=False, default=now),
    c("lease_until", sa.DateTime(timezone=True)), c("lease_token", sa.String(36)), c("last_error", sa.String(160)),
    sa.Index("ix_jobs_due", "status", "next_run_at"))
heartbeats = table("heartbeats", c("worker", sa.String(80), nullable=False, unique=True),
    c("last_seen", sa.DateTime(timezone=True), nullable=False, default=now))
commands = table("commands", c("scope", sa.String(80), nullable=False), c("key", sa.String(160), nullable=False),
    c("payload_hash", sa.String(64), nullable=False), c("result", sa.JSON, nullable=False),
    sa.UniqueConstraint("scope", "key", name="uq_command_scope_key"))
suppliers = table("suppliers", c("name", sa.String(120), nullable=False, unique=True),
    c("mode", sa.String(20), nullable=False, default="excel"),
    c("destination_fingerprint", sa.String(64)), c("destination_approved", sa.Boolean, nullable=False, default=False),
    c("destination_proposed_by", sa.String(80)), c("destination_approved_by", sa.String(80)),
    c("cutoff", sa.String(5), nullable=False, default="14:00"), c("claim_days", sa.Integer, nullable=False, default=3),
    c("active", sa.Boolean, nullable=False, default=True))
products = table("products", c("sku", sa.String(80), nullable=False, unique=True),
    c("title", sa.String(200), nullable=False), c("category", sa.String(100), nullable=False),
    c("origin", sa.String(100), nullable=False), c("tax_type", sa.String(24), nullable=False),
    c("weight_grams", sa.Integer, nullable=False), c("grade", sa.String(80), nullable=False),
    c("unit", sa.String(40), nullable=False), c("season_state", sa.String(20), nullable=False, default="OPEN"),
    c("batch_data", sa.JSON, nullable=False, default=dict), sa.CheckConstraint("weight_grams > 0", name="ck_weight"))
variants = table("product_variants", ref("product_id", "products", nullable=False),
    c("sku", sa.String(80), nullable=False, unique=True), c("attributes", sa.JSON, nullable=False, default=dict))
supplier_products = table("supplier_products", ref("supplier_id", "suppliers", nullable=False),
    ref("product_id", "products", nullable=False), c("supplier_sku", sa.String(80), nullable=False),
    c("cost", sa.BigInteger, nullable=False), c("shipping", sa.BigInteger, nullable=False),
    c("stock", sa.Integer), c("stock_status", sa.String(20), nullable=False),
    c("last_inventory_at", sa.DateTime(timezone=True), nullable=False, default=now),
    sa.UniqueConstraint("supplier_id", "supplier_sku", name="uq_supplier_sku"),
    sa.CheckConstraint("cost >= 0 AND shipping >= 0 AND (stock IS NULL OR stock >= 0)", name="ck_supplier_money"))
price_history = table("supplier_price_history", ref("supplier_product_id", "supplier_products", nullable=False),
    c("old_cost", sa.BigInteger), c("new_cost", sa.BigInteger, nullable=False), c("source_hash", sa.String(64), nullable=False))
listings = table("listings", ref("supplier_product_id", "supplier_products", nullable=False),
    c("marketplace", sa.String(24), nullable=False), c("external_id", sa.String(100)),
    c("price", sa.BigInteger, nullable=False), c("fee_rate", sa.Numeric(10,6), nullable=False),
    c("claim_allowance", sa.BigInteger, nullable=False, default=0), c("promotion_cost", sa.BigInteger, nullable=False, default=0),
    c("desired_state", sa.String(24), nullable=False, default="PAUSED"), c("remote_state", sa.String(24), nullable=False, default="UNKNOWN"),
    c("sync_revision", sa.Integer, nullable=False, default=0), c("last_synced_at", sa.DateTime(timezone=True)),
    sa.UniqueConstraint("marketplace", "supplier_product_id", name="uq_listing_product_channel"),
    sa.CheckConstraint("price > 0 AND fee_rate >= 0 AND fee_rate < 1", name="ck_listing_price"))
orders = table("orders", c("marketplace", sa.String(24), nullable=False), c("external_id", sa.String(100), nullable=False),
    c("external_line_id", sa.String(100), nullable=False), ref("listing_id", "listings", nullable=False),
    c("quantity", sa.Integer, nullable=False), c("gross_sale", sa.BigInteger, nullable=False),
    c("discount", sa.BigInteger, nullable=False, default=0), c("fee", sa.BigInteger, nullable=False, default=0),
    c("promotion_cost", sa.BigInteger, nullable=False, default=0), c("cost_snapshot", sa.BigInteger, nullable=False, default=0),
    c("state", sa.String(32), nullable=False, default="RECEIVED"), c("cancel_requested", sa.Boolean, nullable=False, default=False),
    c("pii_ciphertext", sa.Text, nullable=False), c("input_hash", sa.String(64), nullable=False),
    c("correlation_id", sa.String(36), nullable=False, default=uid), c("hold_until", sa.DateTime(timezone=True), nullable=False, default=now),
    c("delivered_at", sa.DateTime(timezone=True)), c("human_interventions", sa.Integer, nullable=False, default=0),
    sa.UniqueConstraint("marketplace", "external_id", "external_line_id", name="uq_order_external_line"),
    sa.CheckConstraint("quantity > 0 AND gross_sale > 0 AND discount >= 0 AND discount <= gross_sale", name="ck_order_values"))
supplier_orders = table("supplier_orders", ref("order_id", "orders", nullable=False, unique=True),
    c("business_key", sa.String(240), nullable=False, unique=True), c("external_id", sa.String(120)),
    c("status", sa.String(24), nullable=False), c("amount", sa.BigInteger, nullable=False))
accounts = table("accounts", c("code", sa.String(120), nullable=False, unique=True), c("balance", sa.BigInteger, nullable=False, default=0))
journals = table("journals", c("business_key", sa.String(240), nullable=False, unique=True),
    c("payload_hash", sa.String(64), nullable=False), c("kind", sa.String(40), nullable=False),
    c("order_id", sa.String(36)), c("correlation_id", sa.String(36), nullable=False))
postings = table("postings", ref("journal_id", "journals", nullable=False), ref("account_id", "accounts", nullable=False),
    c("delta", sa.BigInteger, nullable=False), sa.CheckConstraint("delta <> 0", name="ck_nonzero_posting"))
reservations = table("reservations", ref("order_id", "orders", nullable=False, unique=True), ref("supplier_id", "suppliers", nullable=False),
    c("bank_amount", sa.BigInteger, nullable=False), c("deposit_amount", sa.BigInteger, nullable=False),
    c("status", sa.String(20), nullable=False, default="HELD"), c("inventory_snapshot_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("bank_amount >= 0 AND deposit_amount >= 0", name="ck_reservation_amount"))
payments = table("payments", ref("order_id", "orders", nullable=False, unique=True), ref("supplier_order_id", "supplier_orders", nullable=False, unique=True),
    c("business_key", sa.String(240), nullable=False, unique=True), c("amount", sa.BigInteger, nullable=False),
    c("destination_fingerprint", sa.String(64), nullable=False), c("status", sa.String(24), nullable=False),
    c("approved_by", sa.String(80)), c("approved_at", sa.DateTime(timezone=True)), c("provider_reference", sa.String(120)),
    c("dispatched_at", sa.DateTime(timezone=True)),
    sa.CheckConstraint("amount > 0", name="ck_payment_positive"))
shipments = table("shipments", ref("order_id", "orders", nullable=False, unique=True),
    c("courier", sa.String(60), nullable=False), c("tracking", sa.String(100), nullable=False),
    c("marketplace_synced", sa.Boolean, nullable=False, default=False),
    sa.UniqueConstraint("courier", "tracking", name="uq_shipment_tracking"))
claims = table("claims", ref("order_id", "orders", nullable=False), c("external_id", sa.String(120), nullable=False, unique=True),
    c("category", sa.String(40), nullable=False), c("status", sa.String(32), nullable=False),
    c("evidence", sa.JSON, nullable=False, default=list), c("deadline", sa.DateTime(timezone=True), nullable=False),
    c("requested_amount", sa.BigInteger, nullable=False), c("supplier_response", sa.String(24)),
    c("supplier_accepted_amount", sa.BigInteger, nullable=False, default=0),
    c("supplier_recovery", sa.BigInteger, nullable=False, default=0), c("customer_refund", sa.BigInteger, nullable=False, default=0),
    sa.CheckConstraint("requested_amount > 0 AND supplier_recovery >= 0 AND customer_refund >= 0", name="ck_claim_values"))
refunds = table("refunds", ref("claim_id", "claims", nullable=False), ref("order_id", "orders", nullable=False),
    c("business_key", sa.String(240), nullable=False, unique=True), c("amount", sa.BigInteger, nullable=False),
    c("status", sa.String(24), nullable=False), c("provider_reference", sa.String(120)),
    sa.CheckConstraint("amount > 0", name="ck_refund_positive"))
settlements = table("settlements", ref("order_id", "orders", nullable=False, unique=True),
    c("external_id", sa.String(120), nullable=False, unique=True), c("expected", sa.BigInteger, nullable=False),
    c("actual", sa.BigInteger, nullable=False), c("difference", sa.BigInteger, nullable=False),
    c("adjustment", sa.BigInteger, nullable=False), c("input_hash", sa.String(64), nullable=False),
    c("confirmed_cash", sa.Boolean, nullable=False, default=False))
profiles = table("excel_profiles", ref("supplier_id", "suppliers", nullable=False), c("name", sa.String(100), nullable=False, unique=True),
    c("version", sa.Integer, nullable=False, default=1), c("mapping", sa.JSON, nullable=False))
imports = table("import_batches", ref("profile_id", "excel_profiles", nullable=False), c("kind", sa.String(20), nullable=False),
    c("file_hash", sa.String(64), nullable=False), c("profile_version", sa.Integer, nullable=False),
    c("profile_snapshot", sa.JSON, nullable=False), c("ciphertext", sa.Text, nullable=False), c("status", sa.String(24), nullable=False),
    c("accepted", sa.Integer, nullable=False, default=0), c("rejected", sa.Integer, nullable=False, default=0),
    sa.UniqueConstraint("profile_id", "profile_version", "kind", "file_hash", name="uq_import_content"))
external_records = table("external_records", c("namespace", sa.String(80), nullable=False), c("business_key", sa.String(240), nullable=False),
    c("payload_hash", sa.String(64), nullable=False), c("result", sa.JSON, nullable=False),
    sa.UniqueConstraint("namespace", "business_key", name="uq_external_effect"))
experiments = table("experiments", ref("product_id", "products", nullable=False), c("state", sa.String(24), nullable=False, default="PROBE"),
    c("metrics", sa.JSON, nullable=False), c("window_start", sa.DateTime(timezone=True), nullable=False),
    c("window_end", sa.DateTime(timezone=True), nullable=False), c("method", sa.String(120), nullable=False))
