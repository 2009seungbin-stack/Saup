"""Phase 11A: no real money, no fake cancellation completion, no history edits."""
import importlib
import json
from sqlalchemy import select, func, text
from sqlalchemy.exc import DatabaseError
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
import pytest
from test_supplier_operations import (excel_env, accepted_order, record, confirm, payment, make_order,
    batch, send, ack, tracking, OP, ADMIN, VIEWER)
from packages.application.review_resolution import ReviewResolutionService, CORRECTION, FINANCIAL, CUSTOMER
from packages.application.common import lock_treasury
from packages.application.finance import post, balance
from packages.domain.errors import DomainError
from packages.infrastructure.models import (Review, ReviewResolution, SupplierEvidenceRevision,
    SupplierEvidenceConfirmationBinding, SupplierCancellationRecovery, SupplierPaymentEvidence,
    SupplierPaymentConfirmation, SupplierCancellation, Payment, Order, SupplierOrder,
    Reservation, Journal, Posting, AuditEvent, SupplierProduct, Supplier, Job, MarketplaceListing)


@pytest.fixture
def resolution_env(excel_env):
    excel_env['resolution'] = ReviewResolutionService(excel_env['commerce'])
    return excel_env


def request(e, proof, **changes):
    return e['resolution'].request_correction(proof['id'], {'idempotency_key':'correction-request-1',
        'expected_revision_id':None, 'reason':'WRONG_ATTACHMENT', **changes}, OP)


def correction(e, rid, **changes):
    return e['resolution'].correct_evidence(rid, {'idempotency_key':'correct-1', 'expected_revision_id':None,
        'reference':'bank-receipt-001', 'evidence_hash':'b'*64, 'verified_same_payment':True, **changes}, ADMIN)


def cancel_paid(e, so):
    e['ops'].cancel_order(so, OP)
    e['ops'].confirm_cancellation(so, {'reference':'supplier-cancel-1','supplier_confirmed_cancelled':True}, ADMIN)
    with e['factory']() as s:
        return s.scalar(select(Review.id).where(Review.entity_id==so, Review.category==FINANCIAL))


def recovery_payload(e, p, **changes):
    d=e['ops'].payment_details(p.id, OP)
    return {k:d[k] for k in ('supplier_id','amount','bank_amount','deposit_amount','destination_fingerprint')} | {
        'payment_id':p.id, 'idempotency_key':'recover-1', 'reference':'supplier-refund-receipt-1',
        'evidence_hash':'c'*64, 'confirmed_funds_received':True, **changes}


def recover(e, rid, p, **changes):
    return e['resolution'].confirm_recovery(rid, recovery_payload(e,p,**changes), ADMIN)


def test_correction_blocks_confirmation_preserves_original_and_binds_revision(resolution_env,order_input):
    e=resolution_env;so,b,p=accepted_order(e,order_input);proof=record(e,p)
    req=request(e,proof);assert req==request(e,proof)
    with pytest.raises(DomainError,match='PAYMENT_EVIDENCE_CORRECTION_REQUIRED'):confirm(e,p,proof)
    d=e['ops'].payment_details(p.id,OP);assert d['evidence_status']=='CORRECTION_REQUIRED'
    result=correction(e,req['review_id']);assert result==correction(e,req['review_id'])
    d=e['ops'].payment_details(p.id,OP)
    assert d['evidence']['evidence_hash']=='b'*64 and d['status']=='EVIDENCE_PENDING'
    assert d['evidence_status']=='RECORDED' and d['evidence_revision_id']==result['revision_id']
    with pytest.raises(DomainError,match='STALE_EVIDENCE_REVISION'):confirm(e,p,proof)
    confirmed=confirm(e,p,proof,evidence_revision_id=result['revision_id'])
    assert confirmed==confirm(e,p,proof,evidence_revision_id=result['revision_id'])
    with e['factory']() as s:
        assert s.get(SupplierPaymentEvidence,proof['id']).evidence_hash=='a'*64
        assert s.scalar(select(SupplierEvidenceConfirmationBinding)).revision_id==result['revision_id']
        assert s.get(Review,req['review_id']).status=='RESOLVED'
        assert s.get(SupplierOrder,so).status=='SHIPMENT_PENDING'
        assert s.scalar(select(func.count()).select_from(Payment))==1
        assert s.scalar(select(func.count()).select_from(SupplierPaymentConfirmation))==1
        events=set(s.scalars(select(AuditEvent.event)))
        assert {'PAYMENT_EVIDENCE_CORRECTION_REQUESTED','PAYMENT_EVIDENCE_CORRECTED','REVIEW_RESOLVED','SUPPLIER_PAYMENT_CONFIRMED'} <= events


def test_revision_chain_and_stale_request(resolution_env,order_input):
    e=resolution_env;_,_,p=accepted_order(e,order_input);proof=record(e,p)
    first=correction(e,request(e,proof)['review_id'])
    with pytest.raises(DomainError,match='STALE_EVIDENCE_REVISION'):request(e,proof,idempotency_key='request-new')
    req=request(e,proof,idempotency_key='request-2',expected_revision_id=first['revision_id'])
    second=correction(e,req['review_id'],idempotency_key='correct-2',expected_revision_id=first['revision_id'],evidence_hash='d'*64)
    with pytest.raises(DomainError,match='STALE_EVIDENCE_REVISION'):confirm(e,p,proof,evidence_revision_id=first['revision_id'])
    confirm(e,p,proof,evidence_revision_id=second['revision_id'])
    with e['factory']() as s:
        r=s.get(SupplierEvidenceRevision,second['revision_id']);assert r.revision==2 and r.supersedes_id==first['revision_id']


@pytest.mark.parametrize('change,code',[
    ({'evidence_hash':'a'*64},'EVIDENCE_CORRECTION_HAS_NO_CHANGE'),
    ({'reference':'different'},'EVIDENCE_CORRECTION_REASON_MISMATCH'),
    ({'expected_revision_id':'unknown'},'STALE_EVIDENCE_REVISION'),
])
def test_bad_correction_leaves_hold_and_no_revision(resolution_env,order_input,change,code):
    e=resolution_env;_,_,p=accepted_order(e,order_input);proof=record(e,p);req=request(e,proof)
    with pytest.raises(DomainError,match=code):correction(e,req['review_id'],**change)
    with e['factory']() as s:
        assert not s.scalar(select(SupplierEvidenceRevision))
        assert s.get(Review,req['review_id']).status=='OPEN'
        assert s.scalar(select(AuditEvent).where(AuditEvent.event=='REVIEW_COMMAND_BLOCKED'))


@pytest.mark.parametrize('field,value',[('amount',1),('supplier_id','other'),('destination_fingerprint','f'*64),('bank_amount',1)])
def test_economics_cannot_be_changed_by_correction(resolution_env,order_input,field,value):
    e=resolution_env;_,_,p=accepted_order(e,order_input);proof=record(e,p);rid=request(e,proof)['review_id']
    with pytest.raises(ValidationError):correction(e,rid,**{field:value})


def test_corrected_reference_is_reserved_against_other_payments(resolution_env,order_input):
    e=resolution_env;so,b,p=accepted_order(e,order_input);proof=record(e,p)
    req=request(e,proof,reason='WRONG_REFERENCE')
    correction(e,req['review_id'],reference='correct-ref',evidence_hash='a'*64)
    other=make_order(e,order_input,name='second');b2=batch(e,[other],key='second');send(e,b2);ack(e,b2)
    with pytest.raises(DomainError,match='REFERENCE_IN_USE'):record(e,payment(e,other),reference='correct-ref')
    assert e['ops'].payment_details(p.id,OP)['evidence']['reference']=='correct-ref'


@pytest.mark.parametrize('state',['SUCCEEDED','UNKNOWN','SENDING','CANCELLED'])
def test_exposed_or_final_payment_cannot_be_corrected(resolution_env,order_input,state):
    e=resolution_env;so,_,p=accepted_order(e,order_input);proof=record(e,p)
    if state=='SUCCEEDED':confirm(e,p,proof)
    else:
        with e['factory'].begin() as s:s.get(Payment,p.id).status=state
    with pytest.raises(DomainError):request(e,proof)
    with e['factory']() as s:assert not s.scalar(select(Review).where(Review.category==CORRECTION))


def test_correction_keeps_payment_limit_gate(resolution_env,order_input):
    e=resolution_env;_,_,p=accepted_order(e,order_input);proof=record(e,p)
    r=correction(e,request(e,proof)['review_id']);e['settings'].daily_payment_limit=1
    with pytest.raises(DomainError,match='DAILY_PAYMENT_LIMIT'):confirm(e,p,proof,evidence_revision_id=r['revision_id'])
    assert e['ops'].payment_details(p.id,OP)['status']=='EVIDENCE_PENDING'


def test_paid_cancellation_recovery_is_balanced_idempotent_and_not_customer_refund(resolution_env,order_input):
    e=resolution_env;so,b,p=accepted_order(e,order_input);confirm(e,p,record(e,p));rid=cancel_paid(e,so)
    with e['factory']() as s:
        before=balance(s,'BANK');stock=s.get(SupplierProduct,s.get(MarketplaceListing,order_input['listing_id']).supplier_product_id).stock
    result=recover(e,rid,p);assert result==recover(e,rid,p)
    with pytest.raises(DomainError,match='IDEMPOTENCY_CONFLICT'):recover(e,rid,p,reference='changed')
    with e['factory']() as s:
        assert balance(s,'BANK')==before+p.amount
        assert s.get(Payment,p.id).status=='SUCCEEDED'
        assert s.get(Order,p.order_id).state=='CANCEL_REQUESTED'
        assert s.get(SupplierOrder,so).status=='CANCELLED'
        assert s.scalar(select(Reservation)).status=='SPENT'
        assert s.get(SupplierProduct,s.get(MarketplaceListing,order_input['listing_id']).supplier_product_id).stock==stock
        assert s.get(Review,rid).status=='RESOLVED'
        assert s.get(Review,result['customer_review_id']).category==CUSTOMER
        assert s.scalar(select(func.count()).select_from(SupplierCancellationRecovery))==1
        assert s.scalar(select(func.count()).select_from(Journal).where(Journal.kind=='SUPPLIER_RECOVERY'))==1
        assert not s.scalar(select(Job).where(Job.kind=='refund.execute'))
        for j in s.scalars(select(Journal)):
            assert s.scalar(select(func.sum(Posting.delta)).where(Posting.journal_id==j.id))==0
    with pytest.raises(DomainError):e['ops'].resolve_batch(b['id'],ADMIN)


@pytest.mark.parametrize('deposit',[5000,20000])
def test_recovery_preserves_original_allocation_and_supplier_isolation(resolution_env,order_input,deposit):
    e=resolution_env;sid=e['ids']['supplier_id']
    with e['factory'].begin() as s:
        lock_treasury(s);other=Supplier(name='other',mode='excel');s.add(other);s.flush();otherid=other.id
        post(s,'deposit-own','TEST',{f'DEPOSIT:{sid}':deposit,'BANK':-deposit})
        post(s,'deposit-other','TEST',{f'DEPOSIT:{otherid}':60000,'BANK':-60000})
        bank_before=balance(s,'BANK')
    so,_,p=accepted_order(e,order_input);confirm(e,p,record(e,p));rid=cancel_paid(e,so);recover(e,rid,p)
    with e['factory']() as s:
        assert balance(s,'BANK')==bank_before and balance(s,f'DEPOSIT:{sid}')==deposit
        assert balance(s,f'DEPOSIT:{otherid}')==60000


@pytest.mark.parametrize('change',[
    {'amount':1},{'supplier_id':'wrong'},{'payment_id':'wrong'},{'destination_fingerprint':'f'*64},
    {'bank_amount':0},{'reference':'bank-receipt-001'},{'evidence_hash':'a'*64},
])
def test_mismatched_or_reused_refund_evidence_never_credits_cash(resolution_env,order_input,change):
    e=resolution_env;so,_,p=accepted_order(e,order_input);confirm(e,p,record(e,p));rid=cancel_paid(e,so)
    with e['factory']() as s:before=balance(s,'BANK')
    with pytest.raises(DomainError):recover(e,rid,p,**change)
    with e['factory']() as s:
        assert balance(s,'BANK')==before and not s.scalar(select(SupplierCancellationRecovery))
        assert s.get(Review,rid).status=='OPEN'


def test_unknown_or_unconfirmed_payment_is_not_recoverable(resolution_env,order_input):
    e=resolution_env;so,_,p=accepted_order(e,order_input);record(e,p);rid=cancel_paid(e,so)
    for state in ('EVIDENCE_PENDING','SENDING','UNKNOWN'):
        with e['factory'].begin() as s:s.get(Payment,p.id).status=state
        with pytest.raises(DomainError,match='RECOVERY_REQUIRES_CONFIRMED_PAID_PAYMENT'):recover(e,rid,p)
    with e['factory']() as s:assert not s.scalar(select(SupplierCancellationRecovery))


def test_post_shipment_recovery_is_blocked(resolution_env,order_input):
    e=resolution_env;so,_,p=accepted_order(e,order_input);confirm(e,p,record(e,p))
    with e['factory'].begin() as s:e['commerce'].add_shipment(s,tracking(e,so))
    rid=cancel_paid(e,so)
    with pytest.raises(DomainError,match='POST_SHIPMENT_RECOVERY'):recover(e,rid,p)


def test_missing_original_journal_cannot_create_refund(resolution_env,order_input):
    e=resolution_env;so,_,p=accepted_order(e,order_input);record(e,p)
    # Corrupt only synthetic fixture to emulate an unsupported legacy paid flag.
    with e['factory'].begin() as s:
        s.get(Payment,p.id).status='SUCCEEDED';s.scalar(select(Reservation)).status='SPENT'
    rid=cancel_paid(e,so)
    with pytest.raises(DomainError,match='ORIGINAL_PAYMENT_JOURNAL'):recover(e,rid,p)


def test_resolution_failure_rolls_back_posted_recovery(resolution_env,order_input,monkeypatch):
    e=resolution_env;so,_,p=accepted_order(e,order_input);confirm(e,p,record(e,p));rid=cancel_paid(e,so)
    with e['factory']() as s:before=balance(s,'BANK')
    def fail(*a,**kw):raise DomainError('SYNTHETIC_FAILURE_AFTER_POST')
    monkeypatch.setattr(e['resolution'],'_resolved',fail)
    with pytest.raises(DomainError,match='SYNTHETIC_FAILURE'):recover(e,rid,p)
    with e['factory']() as s:
        assert balance(s,'BANK')==before and not s.scalar(select(SupplierCancellationRecovery))
        assert not s.scalar(select(Journal).where(Journal.kind=='SUPPLIER_RECOVERY'))
        assert s.get(Review,rid).status=='OPEN'
        assert s.scalar(select(SupplierCancellation)).status=='FINANCIAL_REVIEW'


def test_recovery_receipt_namespace_shared_with_claims(resolution_env,order_input):
    e=resolution_env;so,_,p=accepted_order(e,order_input);confirm(e,p,record(e,p));rid=cancel_paid(e,so)
    sid=e['ids']['supplier_id']
    with e['factory'].begin() as s:
        lock_treasury(s);post(s,f'supplier-recovery:{sid}:already-used','SUPPLIER_RECOVERY',
            {f'DEPOSIT:{sid}':1,'SUPPLIER_RECOVERY':-1},order_id='other-order')
    with pytest.raises(DomainError,match='RECEIPT_IN_USE'):recover(e,rid,p,reference='already-used')


def test_migrated_tables_and_history_are_append_only(resolution_env,order_input):
    from packages.infrastructure.schema_v3 import PHASE11_TABLES
    e=resolution_env
    with e['engine'].begin() as c:
        for t in reversed(PHASE11_TABLES):t.drop(c)
        with Operations.context(MigrationContext.configure(c)):
            importlib.import_module('migrations.versions.0003_review_resolution').upgrade()
    so,_,p=accepted_order(e,order_input);proof=record(e,p);r=correction(e,request(e,proof)['review_id'])
    confirm(e,p,proof,evidence_revision_id=r['revision_id']);recover(e,cancel_paid(e,so),p)
    for table in PHASE11_TABLES:
        for command in ('UPDATE '+table.name+' SET id=id','DELETE FROM '+table.name):
            with pytest.raises(DatabaseError,match='APPEND_ONLY'):
                with e['engine'].begin() as c:c.execute(text(command))
    with pytest.raises(ValueError,match='APPEND_ONLY'):
        with e['factory'].begin() as s:s.get(SupplierEvidenceRevision,r['revision_id']).reference='overwrite'
    with pytest.raises(RuntimeError,match='PHASE11_DATA_PRESENT'):
        with e['engine'].begin() as c:
            with Operations.context(MigrationContext.configure(c)):
                importlib.import_module('migrations.versions.0003_review_resolution').downgrade()


def test_pending_correction_alone_blocks_downgrade(resolution_env,order_input):
    e=resolution_env;_,_,p=accepted_order(e,order_input);request(e,record(e,p))
    with pytest.raises(RuntimeError,match='PHASE11_REVIEW_PRESENT'):
        with e['engine'].begin() as c:
            with Operations.context(MigrationContext.configure(c)):
                importlib.import_module('migrations.versions.0003_review_resolution').downgrade()


def test_empty_migration_roundtrip_and_frozen_snapshots(tmp_path):
    from packages.infrastructure import schema_v1,schema_v2,schema_v3
    from packages.infrastructure.db import database
    assert [len(x.metadata.tables) for x in (schema_v1,schema_v2,schema_v3)]==[28,36,40]
    engine,_=database(f"sqlite:///{tmp_path/'roundtrip.db'}")
    modules=[importlib.import_module('migrations.versions.'+x) for x in ('0001_initial','0002_supplier_operations','0003_review_resolution')]
    with engine.begin() as c:
        with Operations.context(MigrationContext.configure(c)):
            for m in modules:m.upgrade()
            for m in reversed(modules):m.downgrade()
    engine.dispose()


@pytest.mark.parametrize('value',[False,1,'true',None])
def test_attestation_must_be_literal_boolean_true(value):
    from packages.domain.review_resolution import EvidenceCorrection,CancellationRecoveryConfirm
    with pytest.raises(ValidationError):
        EvidenceCorrection.model_validate({'idempotency_key':'test','reference':'test','evidence_hash':'a'*64,'verified_same_payment':value})
    with pytest.raises(ValidationError):
        CancellationRecoveryConfirm.model_validate({'idempotency_key':'test','supplier_id':'supplier','payment_id':'payment',
            'amount':1,'bank_amount':1,'deposit_amount':0,'destination_fingerprint':'a'*64,'reference':'test','evidence_hash':'b'*64,
            'confirmed_funds_received':value})


def test_same_receipt_hash_with_new_reference_cannot_credit_twice(resolution_env,order_input):
    e=resolution_env
    for i in range(2):
        so=make_order(e,order_input,name=f'incoming-{i}');b=batch(e,[so],key=f'incoming-batch-{i}');send(e,b);ack(e,b)
        p=payment(e,so);proof=record(e,p,reference=f'outgoing-{i}');confirm(e,p,proof,reference=f'outgoing-{i}')
        rid=cancel_paid(e,so)
        if i==0:recover(e,rid,p)
        else:
            with pytest.raises(DomainError,match='SUPPLIER_RECOVERY_EVIDENCE_IN_USE'):
                recover(e,rid,p,idempotency_key='different-command',reference='different-receipt-ref')
    with e['factory']() as s:assert s.scalar(select(func.count()).select_from(SupplierCancellationRecovery))==1
