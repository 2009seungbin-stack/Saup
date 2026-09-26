"""Real PostgreSQL transactions/constraints, never substituted by SQLite."""
import importlib
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from uuid import uuid4
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import DatabaseError
from packages.infrastructure.settings import Settings
from packages.infrastructure.models import (Supplier, SupplierProduct, MarketplaceListing, SupplierOrder,
    SupplierOrderBatchItem, SupplierBatchAcknowledgement, Payment, SupplierPaymentEvidence,
    SupplierPaymentConfirmation, Posting, Journal, Job, Shipment, AuditEvent)
from packages.application.seed import seed
from packages.application.commerce import Commerce
from packages.domain.errors import DomainError
from apps.worker.main import Worker
from test_supplier_operations import make_order, batch, send, ack, payment, record, confirm, tracking, OP


@pytest.fixture
def pg_excel_env():
    url=os.environ.get('TEST_POSTGRES_URL')
    if not url:pytest.skip('TEST_POSTGRES_URL missing; real PostgreSQL gate NOT verified')
    # Configured service + missing driver is a FAILURE, not a hidden skip.
    import psycopg  # noqa: F401
    schema='saup_phase10_'+uuid4().hex
    admin=create_engine(url,hide_parameters=True)
    with admin.begin() as c:c.execute(text(f'CREATE SCHEMA {schema}'))
    engine=create_engine(url,connect_args={'options':f'-csearch_path={schema}'},hide_parameters=True)
    factory=sessionmaker(engine,expire_on_commit=False)
    try:
        with engine.begin() as c:
            with Operations.context(MigrationContext.configure(c)):
                importlib.import_module('migrations.versions.0001_initial').upgrade()
                importlib.import_module('migrations.versions.0002_supplier_operations').upgrade()
                importlib.import_module('migrations.versions.0003_review_resolution').upgrade()
                importlib.import_module('migrations.versions.0004_marketplace_cancellation').upgrade()
        settings=Settings(_env_file=None,app_mode='test',database_url=url,
            pii_encryption_key=Fernet.generate_key().decode(),admin_password='synthetic-integration-password')
        ids=seed(settings,factory,demo=True);commerce=Commerce(settings,factory)
        worker=Worker(commerce);worker.drain()
        commerce.clock=lambda:datetime.now(timezone.utc).replace(hour=3,minute=0,second=0,microsecond=0)
        with factory.begin() as s:
            s.get(Supplier,ids['supplier_id']).mode='excel'
            for sp in s.scalars(select(SupplierProduct)):sp.last_inventory_at=commerce.clock()
        yield {'settings':settings,'engine':engine,'factory':factory,'ids':ids,
            'commerce':commerce,'ops':commerce.supplier_operations,'worker':worker}
    finally:
        engine.dispose()
        with admin.begin() as c:c.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        admin.dispose()


def race(first,second=None):
    barrier=Barrier(2)
    def run(fn):
        barrier.wait(timeout=15)
        try:return ('ok',fn())
        except DomainError as exc:return ('conflict',exc.code)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(run,first),pool.submit(run,second or first)]
        return [f.result(timeout=45) for f in futures]


def sample(e):
    return {'marketplace':'coupang','external_id':'synthetic-concurrent-supplier','external_line_id':'1',
        'listing_id':e['ids']['listing_ids'][0], 'quantity':1,'gross_sale':25000,
        'address':{'recipient':'합성 고객','phone':'010-0000-0000','postal_code':'01234',
            'address1':'가상시 테스트로 123','address2':''}}


@pytest.mark.postgres
def test_competing_ack_payment_evidence_confirmation_and_shipment(pg_excel_env):
    e=pg_excel_env;so=make_order(e,sample(e));b=batch(e,[so]);send(e,b)
    results=race(lambda:ack(e,b));assert all(k=='ok' for k,_ in results)
    p=payment(e,so);assert p.status=='EVIDENCE_PENDING'
    results=race(lambda:record(e,p));assert results[0]==results[1];proof=results[0][1]
    results=race(lambda:confirm(e,p,proof));assert results[0]==results[1]
    def add_tracking():
        with e['factory'].begin() as s:return e['commerce'].add_shipment(s,tracking(e,so)).id
    results=race(add_tracking);assert results[0]==results[1]
    with e['factory']() as s:
        for cls in (SupplierOrderBatchItem,SupplierBatchAcknowledgement,Payment,SupplierPaymentEvidence,SupplierPaymentConfirmation,Shipment):
            assert s.scalar(select(func.count()).select_from(cls))==1
        assert s.get(Payment,p.id).status=='SUCCEEDED'
        assert s.scalar(select(func.count()).select_from(Job).where(Job.kind=='marketplace.shipment'))==1
        journals=list(s.scalars(select(Journal).where(Journal.kind=='SUPPLIER_PAYMENT')));assert len(journals)==1
        assert s.scalar(select(func.sum(Posting.delta)).where(Posting.journal_id==journals[0].id))==0
    for table in ('supplier_order_intents','supplier_batch_acknowledgements','supplier_payment_evidence','supplier_payment_confirmations','operational_interventions'):
        with pytest.raises(DatabaseError,match='APPEND_ONLY'):
            with e['engine'].begin() as c:c.execute(text(f'UPDATE {table} SET id=id'))


@pytest.mark.postgres
def test_competing_conflicting_ack_has_one_deterministic_winner(pg_excel_env):
    e=pg_excel_env;so=make_order(e,sample(e));b=batch(e,[so]);send(e,b)
    results=race(lambda:ack(e,b),lambda:ack(e,b,accepted=[],rejected=[{'supplier_order_id':so,'reason':'ORDER_NOT_ACCEPTED'}]))
    assert sorted(k for k,_ in results)==['conflict','ok']
    assert next(v for k,v in results if k=='conflict')=='SUPPLIER_ACK_CONFLICT'
    with e['factory']() as s:
        assert s.scalar(select(func.count()).select_from(SupplierBatchAcknowledgement))==1
        decision=s.scalar(select(SupplierOrderBatchItem)).ack_status
        assert s.scalar(select(func.count()).select_from(Payment))==(1 if decision=='ACCEPTED' else 0)
