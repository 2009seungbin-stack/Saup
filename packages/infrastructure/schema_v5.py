"""Small additive closure history; v1-v4 remain frozen."""
import sqlalchemy as sa
from . import schema_v4 as v4

metadata = sa.MetaData()
for _name, _value in list(vars(v4).items()):
    if isinstance(_value, sa.Table) and not _name.startswith('_'):
        globals()[_name] = _value.to_metadata(metadata)
c, ref, now, uid = v4.c, v4.ref, v4.now, v4.uid


def table(name, *columns):
    return sa.Table(name, metadata, c('id', sa.String(36), primary_key=True, default=uid),
        c('created_at', sa.DateTime(timezone=True), nullable=False, default=now), *columns)


# Only dedicated typed application commands can write these receipts. No generic
# evidence/force-state endpoint exists. Payloads never contain credentials or PII.
operational_receipts = table('operational_receipts',
    c('kind', sa.String(40), nullable=False), c('target_id', sa.String(160), nullable=False),
    c('namespace', sa.String(160), nullable=False), c('reference', sa.String(160), nullable=False),
    c('evidence_hash', sa.String(64), nullable=False, unique=True),
    c('payload_hash', sa.String(64), nullable=False), c('payload', sa.JSON, nullable=False),
    c('actor', sa.String(80), nullable=False),
    sa.UniqueConstraint('kind', 'target_id', name='uq_operational_receipt_target'),
    sa.UniqueConstraint('namespace', 'reference', name='uq_operational_receipt_reference'))

settlement_revisions = table('settlement_revisions',
    ref('settlement_id', 'settlements', nullable=False), c('revision', sa.Integer, nullable=False),
    c('before', sa.JSON, nullable=False), c('after', sa.JSON, nullable=False),
    c('reason', sa.String(40), nullable=False), c('reference', sa.String(160), nullable=False),
    c('evidence_hash', sa.String(64), nullable=False, unique=True),
    c('actor', sa.String(80), nullable=False),
    sa.UniqueConstraint('settlement_id', 'revision', name='uq_settlement_revision'),
    sa.CheckConstraint('revision > 0', name='ck_settlement_revision'))

cancellation_statement_revisions = table('cancellation_statement_revisions',
    ref('statement_id', 'marketplace_cancellation_statements', nullable=False),
    ref('review_id', 'reviews', nullable=False), ref('order_id', 'orders', nullable=False),
    c('revision', sa.Integer, nullable=False), c('values', sa.JSON, nullable=False),
    c('reason', sa.String(40), nullable=False), c('reference', sa.String(160), nullable=False),
    c('evidence_hash', sa.String(64), nullable=False, unique=True), c('actor', sa.String(80), nullable=False),
    sa.UniqueConstraint('statement_id', 'revision', name='uq_cancellation_statement_revision'),
    sa.CheckConstraint('revision > 0', name='ck_cancellation_statement_revision'))

CLOSURE_TABLES = (operational_receipts, settlement_revisions, cancellation_statement_revisions)
APPEND_ONLY_TABLES = tuple(t.name for t in CLOSURE_TABLES)
