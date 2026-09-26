import importlib
from sqlalchemy import select, func, text
from sqlalchemy.exc import DatabaseError
from alembic.migration import MigrationContext
from alembic.operations import Operations as MigrationOps
import pytest
from packages.application.operations import Operations
from packages.application.after_sales import AfterSales, EVIDENCE
from packages.infrastructure.models import (Claim, Refund, Order, Settlement, SettlementRevision, OperationalReceipt,
    MarketplaceCancellationStatement, CancellationStatementRevision, Journal, Posting)
from packages.domain.errors import DomainError
from packages.infrastructure.security import fingerprint
from scripts.closure_scenario import evidence
from test_closure import blank
from test_workflows import delivered
from test_supplier_operations import ADMIN, OP, VIEWER, excel_env
from test_review_resolution import resolution_env
from test_marketplace_cancellation import recovered, refund, statement, statement_payload, completion_payload


def refundable(env, raw):
    oid=delivered(env,raw);ops=Operations(env['commerce'])
    cid=ops.claim(oid,{'external_id':'ops-claim','category':'ROTTEN','amount':5000,'evidence':list(EVIDENCE)},OP)['claim_id']
    ops.response(cid,evidence('response',amount=3000,accepted=True),OP)
    rid=ops.request_refund(cid,{'amount':2000,'key':'ops-partial'},ADMIN)['refund_id']
    cmd=evidence('manual-refund',order_id=oid,claim_id=cid,marketplace=raw['marketplace'],amount=2000,confirmed_customer_refunded=True)
    return ops,oid,cid,rid,cmd


@pytest.mark.parametrize('change,code',[
    ({'amount':2001},'REFUND_IDENTITY_MISMATCH'),({'order_id':'wrong'},'REFUND_IDENTITY_MISMATCH'),
    ({'claim_id':'wrong'},'REFUND_IDENTITY_MISMATCH'),({'marketplace':'temu'},'REFUND_IDENTITY_MISMATCH')])
def test_manual_refund_exact_identity(env,order_input,change,code):
    ops,oid,cid,rid,cmd=refundable(env,order_input)
    with pytest.raises(DomainError,match=code):ops.confirm_refund(rid,cmd|change,ADMIN)
    with env['factory']() as s:assert s.get(Refund,rid).status=='EVIDENCE_PENDING' and s.get(Claim,cid).customer_refund==0


def test_manual_refund_conflicts_ceiling_unknown_and_rbac(env,order_input):
    ops,oid,cid,rid,cmd=refundable(env,order_input)
    for actor in [VIEWER,OP]:
        with pytest.raises(DomainError,match='FORBIDDEN'):ops.confirm_refund(rid,cmd,actor)
    with pytest.raises(DomainError,match='REFUND_EXCEEDS'):ops.request_refund(cid,{'amount':3001,'key':'over-claim'},ADMIN)
    with env['factory'].begin() as s:s.get(Refund,rid).status='UNKNOWN'
    with pytest.raises(DomainError,match='REFUND_NOT_AWAITING'):ops.confirm_refund(rid,cmd,ADMIN)
    env['commerce'].registry.mocks['coupang'].fail_next['refund']='timeout_after'
    AfterSales(env['commerce']).execute_refund(rid)
    with env['factory']() as s:assert s.get(Refund,rid).status=='UNKNOWN'


def test_manual_refund_replay_history_and_cross_claim_sale_ceiling(env,order_input):
    ops,oid,cid,rid,cmd=refundable(env,order_input)
    first=ops.confirm_refund(rid,cmd,ADMIN);assert first==ops.confirm_refund(rid,cmd,ADMIN)
    with pytest.raises(DomainError,match='CONFIRMATION_CONFLICT'):ops.confirm_refund(rid,cmd|{'reference':'other'},ADMIN)
    c2=ops.claim(oid,{'external_id':'claim-second','category':'WRONG_ITEM','amount':order_input['gross_sale'],'evidence':[]},OP)['claim_id']
    ops.response(c2,evidence('second-response',amount=0,accepted=True),OP)
    with pytest.raises(DomainError,match='REFUND_EXCEEDS'):ops.request_refund(c2,{'amount':order_input['gross_sale'],'key':'over-sale'},ADMIN)
    with env['factory']() as s:
        assert s.get(Refund,rid).provider_reference is None
        assert s.get(Claim,cid).status=='PARTIALLY_REFUNDED'
        assert s.scalar(select(func.count()).select_from(Journal).where(Journal.kind=='CUSTOMER_REFUND'))==1


def settlement_ready(env,raw):
    oid=delivered(env,raw);ops=Operations(env['commerce'])
    with env['factory']() as s:
        o=s.get(Order,oid);expected=o.gross_sale-o.discount-o.fee-o.promotion_cost
    sid=ops.settlement(oid,evidence('statement',external_id='statement',actual=expected-1000,adjustment=0),OP)['settlement_id']
    return ops,oid,sid,expected


def test_settlement_correction_compensation_replay_stale_and_confirmed_block(env,order_input):
    ops,oid,sid,expected=settlement_ready(env,order_input)
    cmd=evidence('correct',external_id='corrected',actual=expected,adjustment=0,expected_revision=0,reason='WRONG_AMOUNT')
    first=ops.correct_settlement(sid,cmd,ADMIN);assert first==ops.correct_settlement(sid,cmd,ADMIN)
    with pytest.raises(DomainError,match='STALE'):ops.correct_settlement(sid,cmd|evidence('stale'),ADMIN)
    with pytest.raises(DomainError,match='STALE'):ops.settlement_cash(sid,evidence('cash',amount=expected,expected_revision=0),ADMIN)
    receipt=evidence('cash',amount=expected,expected_revision=1)
    assert ops.settlement_cash(sid,receipt,ADMIN)==ops.settlement_cash(sid,receipt,ADMIN)
    with pytest.raises(DomainError,match='CONFIRMATION_CONFLICT'):ops.settlement_cash(sid,receipt|{'reference':'different'},ADMIN)
    with pytest.raises(DomainError,match='CONFIRMED_SETTLEMENT'):ops.correct_settlement(sid,cmd|evidence('late')|{'expected_revision':1},ADMIN)
    with env['factory']() as s:
        revision=s.scalar(select(SettlementRevision));assert revision.before['actual']==expected-1000 and revision.after['actual']==expected
        assert s.get(Order,oid).state=='CLOSED'
        assert all(n==0 for n in s.scalars(select(func.sum(Posting.delta)).group_by(Posting.journal_id)))
        revision.reason='WRONG_REFERENCE'
        with pytest.raises(ValueError,match='APPEND_ONLY'):s.commit()


@pytest.mark.parametrize('residual',[0,500])
def test_cancellation_correction_history_and_stale_revision(resolution_env,order_input,residual):
    e=resolution_env;_,_,rid=recovered(e,order_input);refund(e,rid);old=statement(e,rid,retained_fee_amount=100)
    cmd=statement_payload(e,rid,idempotency_key='correct',reference='corrected-cancellation',evidence_hash='1'*64,
        retained_fee_amount=residual,statement_id=old['statement_id'],expected_revision=0,reason='WRONG_AMOUNT')
    svc=e['resolution'].marketplace
    first=svc.correct_statement(rid,cmd,ADMIN);assert first==svc.correct_statement(rid,cmd,ADMIN)
    with pytest.raises(DomainError,match='STALE'):svc.correct_statement(rid,cmd|{'idempotency_key':'stale','reference':'stale'},ADMIN)
    with e['factory']() as s:
        assert s.get(MarketplaceCancellationStatement,old['statement_id']).retained_fee_amount==100
        assert s.scalar(select(CancellationStatementRevision)).values['retained_fee_amount']==residual
    finish=completion_payload(e,rid,expected_statement_revision=1)
    if residual:
        with pytest.raises(DomainError,match='UNSUPPORTED_RESIDUAL'):svc.complete(rid,finish,ADMIN)
    else:
        with pytest.raises(DomainError,match='STALE'):svc.complete(rid,finish|{'expected_statement_revision':0},ADMIN)
        assert svc.complete(rid,finish,ADMIN)['order_state']=='CANCELLED'


def test_v5_migration_append_only_and_populated_downgrade(blank):
    e=blank
    from packages.infrastructure.schema_v5 import CLOSURE_TABLES
    with e['engine'].begin() as c:
        for t in reversed(CLOSURE_TABLES):t.drop(c)
        with MigrationOps.context(MigrationContext.configure(c)):
            module=importlib.import_module('migrations.versions.0005_functional_closure');module.upgrade()
    ops=Operations(e['commerce']);ops.funds(evidence('opening-migration',amount=1000),ADMIN)
    with pytest.raises(DatabaseError,match='APPEND_ONLY'):
        with e['engine'].begin() as c:c.execute(text('UPDATE operational_receipts SET actor=actor'))
    with pytest.raises(RuntimeError,match='CLOSURE_DATA_PRESENT'):
        with e['engine'].begin() as c:
            with MigrationOps.context(MigrationContext.configure(c)):module.downgrade()
