"""Actual PostgreSQL locking/atomicity cases; never substitute SQLite results."""
import pytest
from sqlalchemy import select, func
from test_supplier_postgres import pg_excel_env, race, sample
from test_order_intake import file_for, import_file, verify_payload
from test_supplier_operations import OP
from packages.application.order_intake import OrderIntake, IMPORT_SCOPE, VERIFY_SCOPE
from packages.infrastructure.models import Order, SupplierOrder, Reservation, Payment, Command, Job


@pytest.mark.postgres
def test_pg_competing_file_commits_and_source_verification(pg_excel_env):
    e=pg_excel_env;svc=OrderIntake(e['commerce']);data=file_for(sample(e))
    p=svc.preview(data,'coupang',OP)
    cmd={'marketplace':'coupang','preview_token':p['preview_token'],'source_reference':'pg-source','confirmed_authorized_source':True}
    results=race(lambda:svc.commit(data,cmd,OP))
    assert all(k=='ok' for k,_ in results)
    oid=results[0][1]['items'][0]['id'];assert oid==results[1][1]['items'][0]['id']
    confirmation=verify_payload(svc,oid)
    results=race(lambda:svc.verify_and_validate(oid,confirmation,OP))
    assert results[0]==results[1]
    with e['factory']() as s:
        for cls in (Order,SupplierOrder,Reservation):assert s.scalar(select(func.count()).select_from(cls))==1
        assert not s.scalar(select(Payment))
        for scope in (IMPORT_SCOPE,VERIFY_SCOPE):
            assert s.scalar(select(func.count()).select_from(Command).where(Command.scope==scope))==1
        assert not s.scalar(select(Job).where(Job.kind.in_(['order.process','payment.execute'])))


@pytest.mark.postgres
def test_pg_conflicting_source_metadata_has_one_winner(pg_excel_env):
    e=pg_excel_env;svc=OrderIntake(e['commerce']);data=file_for(sample(e));p=svc.preview(data,'coupang',OP)
    cmd={'marketplace':'coupang','preview_token':p['preview_token'],'source_reference':'first','confirmed_authorized_source':True}
    result=race(lambda:svc.commit(data,cmd,OP),lambda:svc.commit(data,cmd|{'source_reference':'second'},OP))
    assert sorted(k for k,_ in result)==['conflict','ok']
    assert next(v for k,v in result if k=='conflict')=='IDEMPOTENCY_CONFLICT'
    with e['factory']() as s:assert s.scalar(select(func.count()).select_from(Order))==1


@pytest.mark.postgres
def test_pg_cancel_competes_with_validation_without_payment(pg_excel_env):
    e=pg_excel_env;svc=OrderIntake(e['commerce']);r,_=import_file(svc,file_for(sample(e)));oid=r['items'][0]['id']
    cmd=verify_payload(svc,oid)
    result=race(lambda:svc.verify_and_validate(oid,cmd,OP),lambda:e['commerce'].cancel(oid,actor='operator'))
    assert any(k=='ok' for k,_ in result)
    with e['factory']() as s:
        order=s.get(Order,oid);assert order.cancel_requested and order.state=='CANCELLED'
        assert not s.scalar(select(Payment))
        reservation=s.scalar(select(Reservation));assert reservation is None or reservation.status=='RELEASED'
        so=s.scalar(select(SupplierOrder));assert so is None or so.status=='CANCELLED'
