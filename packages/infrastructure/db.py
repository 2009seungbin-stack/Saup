from datetime import timezone
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from .models import (OperationalReceipt, SettlementRevision, CancellationStatementRevision,
    AuditEvent, SupplierPriceHistory, Journal, Posting, SupplierOrderIntent,
    SupplierBatchAcknowledgement, SupplierPaymentEvidence, SupplierPaymentConfirmation, OperationalIntervention,
    SupplierEvidenceRevision, SupplierEvidenceConfirmationBinding, SupplierCancellationRecovery, ReviewResolution,
    MarketplaceRefundEvidence, MarketplaceCancellationStatement, MarketplaceCancellationReconciliation)


def database(url: str):
    options = {"pool_pre_ping": True, "hide_parameters": True}
    if url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            options["poolclass"] = StaticPool
    engine = create_engine(url, **options)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
    return engine, sessionmaker(engine, expire_on_commit=False)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def immutable(*_):
    raise ValueError("APPEND_ONLY_RECORD")


for cls in (OperationalReceipt, SettlementRevision, CancellationStatementRevision,
            AuditEvent, SupplierPriceHistory, Journal, Posting, SupplierOrderIntent,
            SupplierBatchAcknowledgement, SupplierPaymentEvidence, SupplierPaymentConfirmation, OperationalIntervention,
    SupplierEvidenceRevision, SupplierEvidenceConfirmationBinding, SupplierCancellationRecovery, ReviewResolution,
    MarketplaceRefundEvidence, MarketplaceCancellationStatement, MarketplaceCancellationReconciliation):
    event.listen(cls, "before_update", immutable)
    event.listen(cls, "before_delete", immutable)
