"""Real PostgreSQL races for closure evidence; SQLite never substitutes."""
import importlib
import os
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, select, func, text
from sqlalchemy.orm import sessionmaker
from alembic.migration import MigrationContext
from alembic.operations import Operations as MigrationOps
from cryptography.fernet import Fernet
from packages.infrastructure.models import OperationalReceipt, Journal, Refund, Claim, Shipment, SettlementRevision
from packages.infrastructure.settings import Settings
from packages.application.seed import seed
from packages.application.commerce import Commerce
from packages.application.operations import Operations
from packages.infrastructure.security import fingerprint
from scripts.closure_scenario import evidence
from test_supplier_postgres import pg_excel_env, race, sample
from test_supplier_operations import accepted_order, record, confirm, tracking, ADMIN, OP


@pytest.mark.postgres
def test_opening_cash_evidence_race():
    url=os.environ.get('TEST_POSTGRES_URL')
    if not url:pytest.skip('TEST_POSTGRES_URL missing; real PostgreSQL gate NOT verified')
    schema='saup_closure_'+uuid4().hex;admin=create_engine(url)
    with admin.begin() as c:c.execute(text(f'CREATE SCHEMA {schema}'))
    engine=create_engine(url,connect_args={'options':f'-csearch_path={schema}'},hide_parameters=True)
    factory=sessionmaker(engine,expire_on_commit=False)
    try:
        with engine.begin() as c:
            with MigrationOps.context(MigrationContext.configure(c)):
                for name in ['0001_initial','0002_supplier_operations','0003_review_resolution','0004_marketplace_cancellation','0005_functional_closure']:
                    importlib.import_module('migrations.versions.'+name).upgrade()
        settings=Settings(_env_file=None,app_mode='test',database_url=url,pii_encryption_key=Fernet.generate_key().decode(),admin_password='synthetic-long-password')
        seed(settings,factory,demo=False);ops=Operations(Commerce(settings,factory));cmd=evidence('opening-race',amount=1000000)
        results=race(lambda:ops.funds(cmd,ADMIN));assert results[0]==results[1] and results[0][0]=='ok'
        with factory() as s:assert s.scalar(select(func.count()).select_from(Journal))==1
    finally:
        engine.dispose()
        with admin.begin() as c:c.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        admin.dispose()


def shipped(e):
    so,b,p=accepted_order(e,sample(e));proof=record(e,p);confirm(e,p,proof)
    with e['factory'].begin() as s:
        sh=e['commerce'].add_shipment(s,tracking(e,so));sid=sh.id;oid=sh.order_id;hashed=fingerprint([sh.courier,sh.tracking])
    return Operations(e['commerce']),oid,sid,hashed


@pytest.mark.postgres
def test_external_shipment_confirmation_race(pg_excel_env):
    e=pg_excel_env;ops,oid,sid,hashed=shipped(e)
    from packages.infrastructure.models import Order
    with e['factory']() as s:o=s.get(Order,oid)
    cmd=evidence('shipment-race',marketplace=o.marketplace,external_order_id=o.external_id,external_line_id=o.external_line_id,tracking_hash=hashed)
    results=race(lambda:ops.confirm_shipment(sid,cmd,OP));assert results[0]==results[1] and results[0][0]=='ok'
    assert sorted(k for k,v in race(lambda:ops.confirm_shipment(sid,cmd,OP),lambda:ops.confirm_shipment(sid,cmd|{'reference':'conflict'},OP)))==['conflict','ok']
    with e['factory']() as s:assert s.scalar(select(func.count()).select_from(OperationalReceipt))==1


def claim_ready(e):
    ops,oid,_,_=shipped(e);e['commerce'].delivered(oid)
    cid=ops.claim(oid,{'external_id':'pg-claim','category':'WRONG_ITEM','amount':5000,'evidence':[]},OP)['claim_id']
    ops.response(cid,evidence('pg-response',accepted=True,amount=2000),OP)
    rid=ops.request_refund(cid,{'amount':2000,'key':'pg-refund'},ADMIN)['refund_id']
    cmd=evidence('pg-refund-receipt',order_id=oid,claim_id=cid,amount=2000,marketplace='coupang',confirmed_customer_refunded=True)
    return ops,oid,cid,rid,cmd


@pytest.mark.postgres
def test_same_manual_refund_receipt_race(pg_excel_env):
    e=pg_excel_env;ops,oid,cid,rid,cmd=claim_ready(e)
    results=race(lambda:ops.confirm_refund(rid,cmd,ADMIN));assert results[0]==results[1] and results[0][0]=='ok'
    with e['factory']() as s:
        assert s.get(Claim,cid).customer_refund==2000 and s.get(Refund,rid).status=='SUCCEEDED'
        assert s.scalar(select(func.count()).select_from(Journal).where(Journal.kind=='CUSTOMER_REFUND'))==1


def settlement_ready(e):
    ops,oid,_,_=shipped(e);e['commerce'].delivered(oid)
    from packages.infrastructure.models import Order
    with e['factory']() as s:o=s.get(Order,oid);amount=o.gross_sale-o.fee
    sid=ops.settlement(oid,evidence('pg-statement',actual=amount,external_id='pg-statement',adjustment=0),OP)['settlement_id']
    return ops,sid,amount


@pytest.mark.postgres
def test_settlement_receipt_race(pg_excel_env):
    e=pg_excel_env;ops,sid,amount=settlement_ready(e);cmd=evidence('pg-cash',amount=amount,expected_revision=0)
    results=race(lambda:ops.settlement_cash(sid,cmd,ADMIN));assert results[0]==results[1] and results[0][0]=='ok'
    with e['factory']() as s:assert s.scalar(select(func.count()).select_from(Journal).where(Journal.kind=='BANK_SETTLEMENT'))==1


@pytest.mark.postgres
def test_settlement_correction_race(pg_excel_env):
    e=pg_excel_env;ops,sid,amount=settlement_ready(e)
    cmd=evidence('pg-correction',external_id='corrected',actual=amount,adjustment=0,expected_revision=0,reason='WRONG_REFERENCE')
    results=race(lambda:ops.correct_settlement(sid,cmd,ADMIN),lambda:ops.correct_settlement(sid,cmd|evidence('other-correction'),ADMIN))
    assert sorted(k for k,v in results)==['conflict','ok']
    assert next(v for k,v in results if k=='conflict')=='STALE_SETTLEMENT_REVISION'
    with e['factory']() as s:assert s.scalar(select(func.count()).select_from(SettlementRevision))==1
