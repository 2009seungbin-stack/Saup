"""Real infrastructure gates. Skipped only without explicitly supplied test services.
Never point TEST_POSTGRES_URL or TEST_REDIS_URL at production services.
"""
import os
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
import importlib
from threading import Barrier
import pytest
from sqlalchemy import create_engine, text, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import DatabaseError
from alembic.migration import MigrationContext
from alembic.operations import Operations
from cryptography.fernet import Fernet
from packages.infrastructure.settings import Settings
from packages.infrastructure.models import Order, SupplierOrder, Payment, ExternalRecord
from packages.infrastructure.security import RateLimiter
from packages.application.seed import seed
from packages.application.commerce import Commerce
from apps.worker.main import Worker
from packages.domain.errors import DomainError

@pytest.mark.postgres
def test_postgres_concurrent_order_and_payment_gate():
    url=os.environ.get('TEST_POSTGRES_URL')
    if not url:pytest.skip('TEST_POSTGRES_URL not configured; PostgreSQL concurrency and deferred triggers not verified')
    import psycopg  # Configured service must never silently skip a missing driver.
    schema='saup_test_'+uuid4().hex
    admin=create_engine(url,hide_parameters=True)
    with admin.begin() as connection:connection.execute(text(f'CREATE SCHEMA {schema}'))
    engine=create_engine(url,connect_args={'options':f'-csearch_path={schema}'},hide_parameters=True)
    factory=sessionmaker(engine,expire_on_commit=False)
    try:
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                importlib.import_module('migrations.versions.0001_initial').upgrade()
                importlib.import_module('migrations.versions.0002_supplier_operations').upgrade()
        settings=Settings(_env_file=None,app_mode='test',database_url=url,admin_password='integration-test-password',
            pii_encryption_key=Fernet.generate_key().decode())
        ids=seed(settings,factory,demo=True);commerce=Commerce(settings,factory);Worker(commerce).drain()
        data={'marketplace':'coupang','external_id':'concurrent-order','external_line_id':'1','listing_id':ids['listing_ids'][0],
            'quantity':1,'gross_sale':25000,'address':{'recipient':'합성 고객','phone':'010-0000-0000','postal_code':'01234',
            'address1':'가상시 테스트로 123','address2':''}}
        def together(fn):
            barrier=Barrier(2)
            def task():barrier.wait();return fn()
            with ThreadPoolExecutor(max_workers=2) as pool:return list(pool.map(lambda _:task(),range(2)))
        results=together(lambda:commerce.ingest(data));assert results[0]['id']==results[1]['id'];oid=results[0]['id']
        together(lambda:commerce.process_order(oid))
        with factory() as s:so=s.scalar(select(SupplierOrder));soid=so.id
        together(lambda:commerce.submit_supplier(soid))
        with factory() as s:p=s.scalar(select(Payment));pid=p.id
        together(lambda:commerce.execute_payment(pid))
        commerce.reconcile_payment(pid)
        with factory() as s:
            assert s.scalar(select(func.count()).select_from(Order))==1
            assert s.scalar(select(func.count()).select_from(Payment))==1
            assert s.get(Payment,pid).status=='SUCCEEDED'
            assert s.scalar(select(func.count()).select_from(ExternalRecord).where(ExternalRecord.namespace=='payment:pay_supplier'))==1
        with pytest.raises(DatabaseError,match='APPEND_ONLY'):
            with engine.begin() as connection:connection.execute(text("UPDATE audit_events SET reason='tampered'"))
        with pytest.raises(DatabaseError,match='UNBALANCED_JOURNAL'):
            with engine.begin() as connection:
                connection.execute(text("INSERT INTO journals(id,created_at,business_key,payload_hash,kind,correlation_id) VALUES (:id,now(),'empty',:hash,'TEST',:id)"),
                    {'id':str(uuid4()),'hash':'a'*64})
    finally:
        engine.dispose()
        with admin.begin() as connection:connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        admin.dispose()

@pytest.mark.redis
def test_distributed_rate_limit_gate():
    url=os.environ.get('TEST_REDIS_URL')
    if not url:pytest.skip('TEST_REDIS_URL not configured; Redis distributed limiter not verified')
    import redis  # Configured service must never silently skip a missing driver.
    settings=Settings(_env_file=None,app_mode='test',pii_encryption_key=Fernet.generate_key().decode(),
        rate_limit_backend='redis',redis_url=url)
    first,second=RateLimiter(settings),RateLimiter(settings)
    identity='test-'+uuid4().hex
    first.hit(identity,2,window=3600);second.hit(identity,2,window=3600)
    with pytest.raises(DomainError,match='RATE_LIMITED'):first.hit(identity,2,window=3600)
    # Test keys expire automatically; never FLUSHDB a shared Redis service.

@pytest.mark.redis
def test_redis_connection_failure_is_fail_closed():
    url=os.environ.get('TEST_REDIS_URL')
    if not url:pytest.skip('TEST_REDIS_URL missing; Redis outage gate NOT verified')
    import redis
    # Prove the configured real service is reachable before testing an unavailable endpoint.
    assert redis.Redis.from_url(url,socket_connect_timeout=2,socket_timeout=2).ping()
    settings=Settings(_env_file=None,app_mode='test',pii_encryption_key=Fernet.generate_key().decode(),
        rate_limit_backend='redis',redis_url='redis://127.0.0.1:1/15')
    with pytest.raises(DomainError,match='RATE_LIMIT_BACKEND_UNAVAILABLE'):
        RateLimiter(settings).hit('synthetic-outage-'+uuid4().hex,10)
