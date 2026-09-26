"""Read-only durable equality proof for the isolated blank-install acceptance."""
import json
from sqlalchemy import select, func, text
from packages.infrastructure import models as m
from packages.infrastructure.db import database
from packages.infrastructure.settings import Settings
from packages.infrastructure.security import fingerprint
from scripts.acceptance_fixture import guard

MODELS = (m.Order,m.SupplierOrder,m.SupplierOrderBatch,m.SupplierOrderBatchItem,m.Payment,m.Reservation,
    m.SupplierPaymentEvidence,m.SupplierPaymentConfirmation,m.OperationalReceipt,m.Claim,m.Refund,m.Settlement,
    m.SettlementRevision,m.Shipment,m.Journal,m.Posting,m.Account,m.Review,m.ReviewResolution,m.OperationalIntervention,
    m.SupplierCancellation,m.SupplierCancellationRecovery,m.MarketplaceRefundEvidence,m.MarketplaceCancellationStatement,
    m.CancellationStatementRevision,m.MarketplaceCancellationReconciliation,m.Command,m.ImportBatch)


def snapshot(factory):
    with factory() as s:
        assert s.scalar(text('SELECT version_num FROM alembic_version'))=='0005'
        assert all(x.mode=='excel' for x in s.scalars(select(m.Supplier)))
        orders={x.external_id:x.state for x in s.scalars(select(m.Order))}
        assert orders=={'closure-normal':'CLOSED','closure-claim':'CLOSED','closure-cancel':'CANCELLED'}
        assert s.scalar(select(func.count()).select_from(m.Refund))==2
        assert s.scalar(select(func.count()).select_from(m.Settlement))==2
        assert s.scalar(select(func.count()).select_from(m.CancellationStatementRevision))==1
        assert all(n==0 for n in s.scalars(select(func.sum(m.Posting.delta)).group_by(m.Posting.journal_id)))
        assert not s.scalar(select(m.Job.id).where(m.Job.status.in_(['PENDING','RUNNING'])))
        assert not s.scalar(select(m.ExternalRecord.id).where(m.ExternalRecord.namespace.not_like('notification%')))
        result={'schema_revision':'0005','orders':orders,'tables':{},'normal_restart_not_backup_restore':True}
        for cls in MODELS:
            rows=[{col.name:getattr(x,col.name) for col in cls.__table__.columns} for x in s.scalars(select(cls).order_by(cls.id))]
            result['tables'][cls.__table__.name]={'count':len(rows),'sha256':fingerprint(rows)}
        return result


if __name__=='__main__':
    settings=Settings();guard(settings);engine,factory=database(settings.database_url)
    try:print(json.dumps(snapshot(factory),sort_keys=True,indent=2))
    finally:engine.dispose()
