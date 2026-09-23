from datetime import timedelta
from decimal import Decimal
import pytest
from sqlalchemy import select, text, func
from sqlalchemy.exc import IntegrityError, DatabaseError
from alembic.config import Config
from alembic import command
from pydantic import ValidationError
from packages.infrastructure.models import (Base, Job, Payment, SupplierOrder, MarketplaceListing, SupplierProduct, Order, Supplier,
    AuditEvent, Account, Review, Journal, Posting, ExternalRecord)
from packages.infrastructure.settings import Settings
from packages.infrastructure.db import database
from packages.infrastructure.schema_v1 import now
from packages.integrations.adapters import CoupangMarketplaceAdapter, TemuMarketplaceAdapter, AliExpressMarketplaceAdapter
from packages.domain.errors import DomainError, IntegrationError
from packages.application.common import enqueue, audit
from packages.application.finance import post, daily_commitments
from packages.application.catalog import inventory_guard

@pytest.mark.parametrize('adapter',[CoupangMarketplaceAdapter,TemuMarketplaceAdapter,AliExpressMarketplaceAdapter])
def test_production_adapters_never_fake_success(adapter):
    x=adapter();assert not x.capabilities.operations
    with pytest.raises(IntegrationError,match='BLOCKED'):x.invoke('list_orders',{},'one')

def test_real_money_flag_alone_never_enables_payment(env):
    data=env['settings'].model_dump();data['real_payments_enabled']=True
    with pytest.raises(ValidationError,match='BLOCKED_BY_PROVIDER_ACCESS'):Settings(_env_file=None,**data)

def test_prod_requires_secure_dependencies(env):
    data=env['settings'].model_dump();data['app_mode']='production'
    with pytest.raises(ValidationError,match='PostgreSQL'):Settings(_env_file=None,**data)

def test_stale_inventory_pauses(env):
    with env['factory'].begin() as s:
        sp=s.scalar(select(SupplierProduct));sp.last_inventory_at=now()-timedelta(days=1)
        assert inventory_guard(s,env['settings'])>=1
        assert s.scalar(select(MarketplaceListing).where(MarketplaceListing.supplier_product_id==sp.id)).desired_state=='PAUSED'

def test_journal_idempotency_and_conflict(env):
    with env['factory'].begin() as s:
        a=post(s,'j-test','TEST',{'BANK':10,'EQUITY':-10})
        assert post(s,'j-test','TEST',{'BANK':10,'EQUITY':-10}).id==a.id
        with pytest.raises(DomainError):post(s,'j-test','TEST',{'BANK':20,'EQUITY':-20})
        with pytest.raises(DomainError):post(s,'bad','TEST',{'BANK':20,'EQUITY':-10})

def test_persistent_provider_key_conflict(env):
    p=env['commerce'].registry.mock_payment
    first=p.pay_supplier({'amount':10},'stable-key');assert first==p.pay_supplier({'amount':10},'stable-key')
    with pytest.raises(DomainError,match='CONFLICT'):p.pay_supplier({'amount':11},'stable-key')

def test_outbox_retry_backoff_then_dead_letter(env):
    calls=[]
    def fail():calls.append(1);raise IntegrationError('INTEGRATION_TIMEOUT',retryable=True)
    env['worker'].handlers['test.fail']=fail
    with env['factory'].begin() as s:j=enqueue(s,'test.fail','fault',{});jid=j.id
    for attempt in range(env['settings'].max_job_attempts):
        env['worker'].tick()
        with env['factory'].begin() as s:
            j=s.get(Job,jid)
            if attempt<env['settings'].max_job_attempts-1:
                assert j.status=='PENDING' and j.next_run_at.replace(tzinfo=now().tzinfo)>now()
                j.next_run_at=now()-timedelta(seconds=1)
            else:assert j.status=='DEAD'
    assert len(calls)==env['settings'].max_job_attempts

def test_financial_replay_disallowed(env):
    with env['factory'].begin() as s:
        job=Job(kind='payment.execute',business_key='unsafe-replay',payload={'payment_id':'none'},status='DEAD');s.add(job);s.flush();jid=job.id
    with pytest.raises(DomainError,match='RECONCILIATION'):env['worker'].replay(jid,'admin')

def test_expired_lease_reclaimed(env):
    with env['factory'].begin() as s:
        job=Job(kind='test.success',business_key='lease',payload={},status='RUNNING',lease_until=now()-timedelta(seconds=1),lease_token='old')
        s.add(job);s.flush();jid=job.id
    env['worker'].handlers['test.success']=lambda:None
    assert env['worker'].tick()
    with env['factory']() as s:
        job=s.get(Job,jid);assert job.status=='DONE' and job.lease_token!='old'

def test_orm_audit_immutable(env):
    with env['factory'].begin() as s:
        row=s.scalar(select(AuditEvent));row.reason='tampered'
        with pytest.raises(ValueError,match='APPEND_ONLY'):s.flush()
        s.rollback()

def test_alembic_sqlite_upgrade_downgrade_and_db_triggers(tmp_path,monkeypatch):
    url=f"sqlite:///{tmp_path/'migrated.db'}";monkeypatch.setenv('DATABASE_URL',url)
    config=Config('alembic.ini');command.upgrade(config,'head')
    engine,factory=database(url)
    with factory.begin() as s:audit(s,'TEST','entity');s.flush()
    with engine.begin() as connection:
        with pytest.raises(DatabaseError,match='APPEND_ONLY'):
            connection.execute(text("UPDATE audit_events SET reason='tamper'"))
    engine.dispose();command.downgrade(config,'base');command.upgrade(config,'head')

def test_global_daily_limit_includes_older_pending_payments(env,order_input):
    oid=env['commerce'].ingest(order_input)['id'];env['commerce'].process_order(oid)
    with env['factory']() as s:so=s.scalar(select(SupplierOrder))
    env['commerce'].submit_supplier(so.id)
    with env['factory'].begin() as s:
        p=s.scalar(select(Payment));p.created_at=now()-timedelta(days=2)
        assert daily_commitments(s)==p.amount

def test_sql_unique_order_and_payment_keys(env,order_input):
    env['commerce'].ingest(order_input);env['worker'].drain()
    with env['factory'].begin() as s:
        p=s.scalar(select(Payment))
        with pytest.raises(IntegrityError):
            with s.begin_nested():
                s.add(Payment(order_id=p.order_id,supplier_order_id=p.supplier_order_id,business_key='different',
                    amount=p.amount,destination_fingerprint=p.destination_fingerprint,status='PENDING'));s.flush()


def test_provider_configuration_does_not_unblock_unimplemented_connector():
    from packages.integrations.config import ProviderConfig
    config=ProviderConfig(provider='aliexpress')
    assert config.readiness()=='BLOCKED_BY_CREDENTIALS'
    config=ProviderConfig(provider='aliexpress',client_id='test-client',client_secret='not-a-live-secret')
    assert 'not-a-live-secret' not in repr(config)
    assert config.readiness()=='BLOCKED_BY_PROVIDER_ACCESS'
    config.account_permissions_verified=True;config.documentation_reference='verified manual test fixture'
    assert config.readiness()=='BLOCKED_BY_CONNECTOR_IMPLEMENTATION'

def test_payload_bound_command_idempotency(env):
    from packages.application.common import execute_command
    calls=[]
    with env['factory'].begin() as s:
        first=execute_command(s,'test','same',{'amount':10},lambda:calls.append(1) or {'result':1})
        second=execute_command(s,'test','same',{'amount':10},lambda:calls.append(2) or {'result':2})
        assert first==second and calls==[1]
        with pytest.raises(DomainError,match='CONFLICT'):execute_command(s,'test','same',{'amount':20},lambda:{})
