"""Real PostgreSQL races/immutability, never represented by SQLite results."""
import pytest
from sqlalchemy import select, func, text
from sqlalchemy.exc import DatabaseError
from test_supplier_postgres import pg_excel_env, race, sample
from test_supplier_operations import accepted_order,record,confirm,make_order,batch,send,ack,payment
from test_review_resolution import request,correction,cancel_paid,recover,recovery_payload
from packages.application.review_resolution import ReviewResolutionService
from packages.infrastructure.models import (Payment, Review, SupplierEvidenceRevision, SupplierCancellationRecovery,
    SupplierEvidenceConfirmationBinding, ReviewResolution, Journal, Posting)
from packages.infrastructure.schema_v3 import PHASE11_TABLES


def setup(e):
    e['resolution']=ReviewResolutionService(e['commerce'])
    return e


@pytest.mark.postgres
def test_postgres_duplicate_correction_confirmation_and_recovery(pg_excel_env):
    e=setup(pg_excel_env);so,_,p=accepted_order(e,sample(e));proof=record(e,p)
    results=race(lambda:request(e,proof));assert results[0]==results[1];rid=results[0][1]['review_id']
    results=race(lambda:correction(e,rid));assert results[0]==results[1];revision=results[0][1]['revision_id']
    results=race(lambda:confirm(e,p,proof,evidence_revision_id=revision));assert results[0]==results[1]
    rid=cancel_paid(e,so);results=race(lambda:recover(e,rid,p));assert results[0]==results[1]
    with e['factory']() as s:
        for cls in (SupplierEvidenceRevision,SupplierEvidenceConfirmationBinding,SupplierCancellationRecovery):
            assert s.scalar(select(func.count()).select_from(cls))==1
        assert s.scalar(select(func.count()).select_from(ReviewResolution))==2
        assert s.scalar(select(func.count()).select_from(Journal).where(Journal.kind=='SUPPLIER_RECOVERY'))==1
        for j in s.scalars(select(Journal)):
            assert s.scalar(select(func.sum(Posting.delta)).where(Posting.journal_id==j.id))==0
    for table in PHASE11_TABLES:
        for action in (f'UPDATE {table.name} SET id=id',f'DELETE FROM {table.name}'):
            with pytest.raises(DatabaseError,match='APPEND_ONLY'):
                with e['engine'].begin() as c:c.execute(text(action))


@pytest.mark.postgres
def test_postgres_correction_request_competes_with_confirmation(pg_excel_env):
    e=setup(pg_excel_env);so,_,p=accepted_order(e,sample(e));proof=record(e,p)
    results=race(lambda:request(e,proof),lambda:confirm(e,p,proof))
    assert sorted(k for k,_ in results)==['conflict','ok']
    with e['factory']() as s:
        status=s.get(Payment,p.id).status
        pending=list(s.scalars(select(Review).where(Review.category=='SUPPLIER_PAYMENT_EVIDENCE_CORRECTION')))
        assert (status=='SUCCEEDED' and not pending) or (status=='EVIDENCE_PENDING' and len(pending)==1)


@pytest.mark.postgres
def test_postgres_same_recovery_receipt_cannot_credit_two_orders(pg_excel_env):
    e=setup(pg_excel_env);transactions=[]
    for i in range(2):
        so=make_order(e,sample(e),name=f'recovery-{i}');b=batch(e,[so],key=f'batch-{i}');send(e,b);ack(e,b)
        p=payment(e,so);proof=record(e,p,reference=f'outgoing-{i}');confirm(e,p,proof,reference=f'outgoing-{i}')
        transactions.append((cancel_paid(e,so),p))
    def apply(i):
        rid,p=transactions[i]
        return recover(e,rid,p,idempotency_key=f'recovery-{i}',reference='shared-incoming-receipt')
    results=race(lambda:apply(0),lambda:apply(1))
    assert sorted(k for k,_ in results)==['conflict','ok']
    assert next(v for k,v in results if k=='conflict')=='SUPPLIER_RECOVERY_RECEIPT_IN_USE'
    with e['factory']() as s:
        assert s.scalar(select(func.count()).select_from(SupplierCancellationRecovery))==1
        assert s.scalar(select(func.count()).select_from(Journal).where(Journal.kind=='SUPPLIER_RECOVERY'))==1
