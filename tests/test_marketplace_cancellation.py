"""Phase 11B: record an EXTERNAL marketplace full refund and zero statement; never send money."""
import importlib
from datetime import datetime, timezone
from sqlalchemy import select, func, text
from sqlalchemy.exc import DatabaseError
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
import pytest
from test_supplier_operations import (excel_env, accepted_order, record, confirm, make_order, batch, send, ack,
    payment, OP, ADMIN, VIEWER)
from test_review_resolution import resolution_env, cancel_paid, recover
from packages.application.common import lock_treasury, review
from packages.application.finance import post, balance
from packages.application.marketplace_cancellation import CUSTOMER, RESIDUAL, LATE_LINE
from packages.domain.errors import DomainError
from packages.domain.marketplace_cancellation import (MarketplaceRefundReceipt, MarketplaceCancellationStatementInput,
    MarketplaceCancellationCompletion)
from packages.infrastructure.models import (Review, ReviewResolution, Order, Payment, Reservation, SupplierOrder,
    SupplierCancellation, SupplierCancellationRecovery, SupplierProduct, MarketplaceListing, Shipment, Claim, Refund,
    Settlement, Job, Journal, Posting, Account, AuditEvent, MarketplaceRefundEvidence, MarketplaceCancellationStatement,
    MarketplaceCancellationReconciliation)
from packages.infrastructure.schema_v4 import PHASE11B_TABLES

TABLES = (MarketplaceRefundEvidence, MarketplaceCancellationStatement, MarketplaceCancellationReconciliation)
ZEROS = {'seller_payout_amount': 0, 'seller_debit_amount': 0, 'retained_fee_amount': 0, 'outstanding_balance': 0}


def recovered(e, order_input, name='supplier-001', key='batch-001', outgoing='bank-receipt-001', incoming='supplier-refund-receipt-1', receipt_hash='c'*64):
    """Real 11A path: paid, supplier-cancelled, supplier recovery confirmed. Returns the customer review."""
    so = make_order(e, order_input, name=name); b = batch(e, [so], key=key); send(e, b); ack(e, b)
    p = payment(e, so); proof = record(e, p, reference=outgoing); confirm(e, p, proof, reference=outgoing)
    result = recover(e, cancel_paid(e, so), p, idempotency_key=f'recover-{name}', reference=incoming, evidence_hash=receipt_hash)
    return so, p, result['customer_review_id']


def detail(e, rid):
    return e['resolution'].get_review(rid)


def refund_payload(e, rid, **changes):
    snap = detail(e, rid)['snapshot']
    return {'idempotency_key': 'mp-refund-1', 'snapshot_hash': snap['snapshot_hash'],
        'supplier_recovery_id': snap['supplier_recovery_id'], 'marketplace': snap['marketplace'],
        'external_order_id': snap['external_order_id'], 'external_line_id': snap['external_line_id'],
        'customer_refund_amount': snap['customer_refund_amount'], 'reference': 'mp-refund-ref-1',
        'evidence_hash': 'e'*64, 'confirmed_customer_refunded': True, **changes}


def statement_payload(e, rid, **changes):
    d = detail(e, rid)
    return {'idempotency_key': 'mp-statement-1', 'snapshot_hash': d['snapshot']['snapshot_hash'],
        'refund_evidence_id': d['marketplace_cancellation']['refund_evidence']['id'],
        'customer_refund_amount': d['snapshot']['customer_refund_amount'], **ZEROS,
        'reference': 'mp-statement-ref-1', 'evidence_hash': 'f'*64,
        'confirmed_final_statement': True, 'confirmed_marketplace_cancelled': True, **changes}


def completion_payload(e, rid, **changes):
    d = detail(e, rid); records = d['marketplace_cancellation']
    return {'idempotency_key': 'mp-complete-1', 'snapshot_hash': d['snapshot']['snapshot_hash'],
        'refund_evidence_id': records['refund_evidence']['id'], 'statement_id': records['statement']['id'],
        'confirmed_reconciliation': True, **changes}


def refund(e, rid, **changes):
    return e['resolution'].record_marketplace_refund(rid, refund_payload(e, rid, **changes), ADMIN)


def statement(e, rid, **changes):
    return e['resolution'].record_marketplace_statement(rid, statement_payload(e, rid, **changes), ADMIN)


def complete(e, rid, **changes):
    return e['resolution'].complete_marketplace_cancellation(rid, completion_payload(e, rid, **changes), ADMIN)


def ready(e, order_input, **kw):
    so, p, rid = recovered(e, order_input, **kw); refund(e, rid); statement(e, rid)
    return so, p, rid


def counts(e):
    with e['factory']() as s:
        return {cls.__table__.name: s.scalar(select(func.count()).select_from(cls)) for cls in TABLES}


def balanced(s):
    return not s.execute(select(Posting.journal_id).group_by(Posting.journal_id).having(func.sum(Posting.delta) != 0)).all()


# --- happy path and final state -------------------------------------------------------------

def test_full_external_cancellation_reconciliation_happy_path(resolution_env, order_input):
    e = resolution_env; so, p, rid = recovered(e, order_input)
    first = detail(e, rid)
    assert first['action'] == 'COMPLETE_MARKETPLACE_CANCELLATION_RECONCILIATION'
    assert first['stage'] == 'CUSTOMER_REFUND_EVIDENCE_MISSING' and first['eligible'] and first['money_sent'] is False
    with e['factory']() as s:
        order = s.get(Order, p.order_id); required = order.gross_sale - order.discount
        sp = s.get(SupplierProduct, s.get(MarketplaceListing, order_input['listing_id']).supplier_product_id)
        stock, journals = sp.stock, s.scalar(select(func.count()).select_from(Journal))
        accounts = {a.code: a.balance for a in s.scalars(select(Account))}
        jobs = set(s.scalars(select(Job.id)))
    assert first['snapshot']['customer_refund_amount'] == required and required != p.amount
    r = refund(e, rid); assert r['customer_refund_amount'] == required
    assert detail(e, rid)['stage'] == 'MARKETPLACE_STATEMENT_MISSING'
    st = statement(e, rid); assert st['classification'] == 'ZERO_SELLER_SETTLEMENT' and st['completion_allowed']
    assert detail(e, rid)['stage'] == 'READY_FOR_COMPLETION'
    with e['factory']() as s:
        assert s.get(Order, p.order_id).state == 'CANCEL_REQUESTED'  # evidence alone never closes the order
    done = complete(e, rid)
    assert done['order_state'] == 'CANCELLED' and done['payment_status'] == 'SUCCEEDED'
    final = detail(e, rid); assert final['stage'] == 'RESOLVED' and final['status'] == 'RESOLVED' and not final['eligible']
    with e['factory']() as s:
        order = s.get(Order, p.order_id)
        assert order.state == 'CANCELLED' and order.state not in {'CLOSED', 'SETTLED'}
        assert s.get(SupplierOrder, so).status == 'CANCELLED'
        assert s.get(Payment, p.id).status == 'SUCCEEDED'
        assert s.scalar(select(Reservation).where(Reservation.order_id == order.id)).status == 'SPENT'
        assert s.scalar(select(SupplierCancellation)).status == 'FINANCIALLY_RECONCILED'
        assert s.get(SupplierProduct, s.get(MarketplaceListing, order_input['listing_id']).supplier_product_id).stock == stock
        assert not s.scalar(select(Shipment)) and not s.scalar(select(Refund))
        assert not s.scalar(select(Job).where(Job.kind == 'refund.execute'))
        assert s.scalar(select(func.count()).select_from(Journal)) == journals  # no invented ledger movement
        assert {a.code: a.balance for a in s.scalars(select(Account))} == accounts
        assert balance(s, 'MARKETPLACE_RECEIVABLE') == 0 and balanced(s)
        assert s.get(Review, rid).status == 'RESOLVED' and s.get(Review, rid).resolution_code == 'COMPLETE_MARKETPLACE_CANCELLATION_RECONCILIATION'
        assert s.scalar(select(func.count()).select_from(ReviewResolution).where(ReviewResolution.review_id == rid)) == 1
        # Phase 11B commands enqueue nothing: no refund, payment, shipment or marketplace job.
        assert set(s.scalars(select(Job.id))) == jobs
        events = set(s.scalars(select(AuditEvent.event)))
        assert {'MARKETPLACE_CUSTOMER_REFUND_EVIDENCE_RECORDED', 'MARKETPLACE_CANCELLATION_STATEMENT_RECORDED',
                'MARKETPLACE_CANCELLATION_RECONCILED'} <= events
    assert counts(e) == {t.__table__.name: 1 for t in TABLES}


def test_resolution_history_and_supplier_recovery_untouched(resolution_env, order_input):
    e = resolution_env; so, p, rid = ready(e, order_input)
    with e['factory']() as s:
        before = {c.name: getattr(s.scalar(select(SupplierCancellationRecovery)), c.name) for c in SupplierCancellationRecovery.__table__.columns}
    complete(e, rid)
    with e['factory']() as s:
        after = {c.name: getattr(s.scalar(select(SupplierCancellationRecovery)), c.name) for c in SupplierCancellationRecovery.__table__.columns}
        assert before == after
    history = detail(e, rid)['history']; assert [h['action'] for h in history] == ['COMPLETE_MARKETPLACE_CANCELLATION_RECONCILIATION']


# --- refund receipt -------------------------------------------------------------------------

def test_refund_identical_replay_and_conflict(resolution_env, order_input):
    e = resolution_env; _, _, rid = recovered(e, order_input); payload = refund_payload(e, rid)
    first = e['resolution'].record_marketplace_refund(rid, payload, ADMIN)
    assert first == e['resolution'].record_marketplace_refund(rid, payload, ADMIN)
    # A reopened browser with a new idempotency key but identical evidence returns the same effect.
    assert first == e['resolution'].record_marketplace_refund(rid, payload | {'idempotency_key': 'reopened'}, ADMIN)
    with pytest.raises(DomainError, match='IDEMPOTENCY_CONFLICT'):
        e['resolution'].record_marketplace_refund(rid, payload | {'reference': 'other-ref'}, ADMIN)
    with pytest.raises(DomainError, match='MARKETPLACE_REFUND_EVIDENCE_CONFLICT'):
        e['resolution'].record_marketplace_refund(rid, payload | {'idempotency_key': 'k2', 'reference': 'other-ref'}, ADMIN)
    assert counts(e)['marketplace_refund_evidence'] == 1


@pytest.mark.parametrize('change,code', [
    ({'marketplace': 'naver'}, 'MARKETPLACE_ORDER_IDENTITY_MISMATCH'),
    ({'external_order_id': 'another-order'}, 'MARKETPLACE_ORDER_IDENTITY_MISMATCH'),
    ({'external_line_id': '2'}, 'MARKETPLACE_ORDER_IDENTITY_MISMATCH'),
    ({'customer_refund_amount': 1}, 'FULL_CUSTOMER_REFUND_REQUIRED'),
    ({'snapshot_hash': '0'*64}, 'MARKETPLACE_CANCELLATION_SNAPSHOT_MISMATCH'),
    ({'supplier_recovery_id': 'not-this-recovery'}, 'SUPPLIER_RECOVERY_MISMATCH'),
    ({'reference': 'supplier-refund-receipt-1'}, 'SUPPLIER_EVIDENCE_IS_NOT_CUSTOMER_REFUND'),
    ({'reference': 'bank-receipt-001'}, 'SUPPLIER_EVIDENCE_IS_NOT_CUSTOMER_REFUND'),
    ({'evidence_hash': 'c'*64}, 'MARKETPLACE_EVIDENCE_HASH_IN_USE'),
    ({'evidence_hash': 'a'*64}, 'MARKETPLACE_EVIDENCE_HASH_IN_USE'),
])
def test_refund_rejections_leave_no_record(resolution_env, order_input, change, code):
    e = resolution_env; _, p, rid = recovered(e, order_input)
    with pytest.raises(DomainError, match=code):refund(e, rid, **change)
    assert counts(e)['marketplace_refund_evidence'] == 0
    with e['factory']() as s:
        assert s.get(Review, rid).status == 'OPEN'
        assert s.scalar(select(AuditEvent).where(AuditEvent.event == 'REVIEW_COMMAND_BLOCKED'))


def test_supplier_cost_is_not_customer_refund(resolution_env, order_input):
    e = resolution_env; _, p, rid = recovered(e, order_input)
    with pytest.raises(DomainError, match='FULL_CUSTOMER_REFUND_REQUIRED'):refund(e, rid, customer_refund_amount=p.amount)


@pytest.mark.parametrize('value', [False, 1, 'true', None])
def test_every_attestation_requires_literal_true(value):
    base = {'idempotency_key': 'k', 'snapshot_hash': 'a'*64}
    with pytest.raises(ValidationError):
        MarketplaceRefundReceipt.model_validate(base | {'supplier_recovery_id': 'r', 'marketplace': 'coupang',
            'external_order_id': 'o', 'external_line_id': '1', 'customer_refund_amount': 1, 'reference': 'r',
            'evidence_hash': 'b'*64, 'confirmed_customer_refunded': value})
    statement = base | {'refund_evidence_id': 'r', 'customer_refund_amount': 1, **ZEROS, 'reference': 'r', 'evidence_hash': 'b'*64}
    for key in ('confirmed_final_statement', 'confirmed_marketplace_cancelled'):
        with pytest.raises(ValidationError):
            MarketplaceCancellationStatementInput.model_validate(statement | {'confirmed_final_statement': True,
                'confirmed_marketplace_cancelled': True, key: value})
    with pytest.raises(ValidationError):
        MarketplaceCancellationCompletion.model_validate(base | {'refund_evidence_id': 'r', 'statement_id': 's',
            'confirmed_reconciliation': value})


def test_missing_attestation_rejected(resolution_env, order_input):
    e = resolution_env; _, _, rid = recovered(e, order_input); payload = refund_payload(e, rid)
    payload.pop('confirmed_customer_refunded')
    with pytest.raises(ValidationError):e['resolution'].record_marketplace_refund(rid, payload, ADMIN)


def test_refund_reference_and_hash_cannot_be_reused_across_orders(resolution_env, order_input):
    e = resolution_env
    _, _, one = recovered(e, order_input, name='first-order', key='b1', outgoing='out-1', incoming='in-1', receipt_hash='1'*64)
    _, _, two = recovered(e, order_input, name='second-order', key='b2', outgoing='out-2', incoming='in-2', receipt_hash='2'*64)
    refund(e, one)
    with pytest.raises(DomainError, match='MARKETPLACE_EVIDENCE_REFERENCE_IN_USE'):
        refund(e, two, idempotency_key='second', evidence_hash='9'*64)
    with pytest.raises(DomainError, match='MARKETPLACE_EVIDENCE_HASH_IN_USE'):
        refund(e, two, idempotency_key='second', reference='another-ref')
    refund(e, two, idempotency_key='second', reference='another-ref', evidence_hash='9'*64)
    assert counts(e)['marketplace_refund_evidence'] == 2


def test_non_admin_and_wrong_category_rejected(resolution_env, order_input):
    e = resolution_env; so, p, rid = recovered(e, order_input); payload = refund_payload(e, rid)
    for actor in (OP, VIEWER):
        with pytest.raises(DomainError, match='FORBIDDEN'):e['resolution'].record_marketplace_refund(rid, payload, actor)
    with e['factory']() as s:
        financial = s.scalar(select(Review.id).where(Review.category == 'SUPPLIER_CANCELLATION_FINANCIAL_REVIEW'))
    with pytest.raises(DomainError, match='REVIEW_ALREADY_RESOLVED|REVIEW_ACTION_CATEGORY_MISMATCH'):
        e['resolution'].record_marketplace_refund(financial, payload, ADMIN)


# --- final statement ------------------------------------------------------------------------

def test_statement_identical_replay_and_conflict(resolution_env, order_input):
    e = resolution_env; _, _, rid = recovered(e, order_input); refund(e, rid); payload = statement_payload(e, rid)
    first = e['resolution'].record_marketplace_statement(rid, payload, ADMIN)
    assert first == e['resolution'].record_marketplace_statement(rid, payload, ADMIN)
    assert first == e['resolution'].record_marketplace_statement(rid, payload | {'idempotency_key': 'reopened'}, ADMIN)
    with pytest.raises(DomainError, match='IDEMPOTENCY_CONFLICT'):
        e['resolution'].record_marketplace_statement(rid, payload | {'evidence_hash': '3'*64}, ADMIN)
    with pytest.raises(DomainError, match='MARKETPLACE_STATEMENT_CONFLICT'):
        e['resolution'].record_marketplace_statement(rid, payload | {'idempotency_key': 'k2', 'seller_payout_amount': 5}, ADMIN)
    assert counts(e)['marketplace_cancellation_statements'] == 1


@pytest.mark.parametrize('field', list(ZEROS))
def test_statement_residual_is_recorded_blocked_and_reviewed(resolution_env, order_input, field):
    e = resolution_env; _, p, rid = recovered(e, order_input); refund(e, rid)
    result = statement(e, rid, **{field: 100})
    assert result['classification'] == 'UNSUPPORTED_RESIDUAL_SETTLEMENT' and not result['completion_allowed']
    d = detail(e, rid)
    assert d['stage'] == 'BLOCKED_UNSUPPORTED_RESIDUAL_SETTLEMENT' and d['blocked_reason'] == 'UNSUPPORTED_RESIDUAL_SETTLEMENT'
    assert d['next_action'] is None and d['status'] == 'OPEN'
    with pytest.raises(DomainError, match='UNSUPPORTED_RESIDUAL_SETTLEMENT'):complete(e, rid)
    with e['factory']() as s:
        residual = s.scalar(select(Review).where(Review.category == RESIDUAL))
        assert residual.status == 'OPEN' and residual.details[field] == 100
        assert s.get(Order, p.order_id).state == 'CANCEL_REQUESTED'
        assert not s.scalar(select(MarketplaceCancellationReconciliation))
    assert e['resolution'].get_review(residual.id)['blocked_reason'] == 'NO_AUTOMATED_RESOLUTION_FOR_CATEGORY'


@pytest.mark.parametrize('field', list(ZEROS) + ['customer_refund_amount', 'confirmed_final_statement', 'confirmed_marketplace_cancelled'])
def test_statement_omitted_fields_are_not_defaulted(resolution_env, order_input, field):
    e = resolution_env; _, _, rid = recovered(e, order_input); refund(e, rid); payload = statement_payload(e, rid)
    payload.pop(field)
    with pytest.raises(ValidationError):e['resolution'].record_marketplace_statement(rid, payload, ADMIN)
    assert counts(e)['marketplace_cancellation_statements'] == 0


@pytest.mark.parametrize('change,code', [
    ({'customer_refund_amount': 1}, 'STATEMENT_CUSTOMER_REFUND_MISMATCH'),
    ({'snapshot_hash': '0'*64}, 'MARKETPLACE_CANCELLATION_SNAPSHOT_MISMATCH'),
    ({'refund_evidence_id': 'unknown'}, 'REFUND_EVIDENCE_NOT_FOR_THIS_ORDER'),
    ({'evidence_hash': 'e'*64}, 'MARKETPLACE_EVIDENCE_HASH_IN_USE'),
    ({'seller_payout_amount': -1}, None),
    ({'retained_fee_amount': True}, None),
])
def test_statement_rejections(resolution_env, order_input, change, code):
    e = resolution_env; _, _, rid = recovered(e, order_input); refund(e, rid)
    with pytest.raises(DomainError if code else ValidationError, match=code):statement(e, rid, **change)
    assert counts(e)['marketplace_cancellation_statements'] == 0


def test_statement_requires_refund_evidence_first(resolution_env, order_input):
    e = resolution_env; _, _, rid = recovered(e, order_input)
    snap = detail(e, rid)['snapshot']
    cmd = {'idempotency_key': 'early', 'snapshot_hash': snap['snapshot_hash'], 'refund_evidence_id': 'none-yet',
        'customer_refund_amount': snap['customer_refund_amount'], **ZEROS, 'reference': 'early-statement',
        'evidence_hash': '5'*64, 'confirmed_final_statement': True, 'confirmed_marketplace_cancelled': True}
    with pytest.raises(DomainError, match='REFUND_EVIDENCE_NOT_FOR_THIS_ORDER'):
        e['resolution'].record_marketplace_statement(rid, cmd, ADMIN)


def test_statement_cannot_use_refund_evidence_from_another_order(resolution_env, order_input):
    e = resolution_env
    _, _, one = recovered(e, order_input, name='first-order', key='b1', outgoing='out-1', incoming='in-1', receipt_hash='1'*64)
    _, _, two = recovered(e, order_input, name='second-order', key='b2', outgoing='out-2', incoming='in-2', receipt_hash='2'*64)
    other = refund(e, one)['refund_evidence_id']; refund(e, two, idempotency_key='r2', reference='ref-2', evidence_hash='7'*64)
    with pytest.raises(DomainError, match='REFUND_EVIDENCE_NOT_FOR_THIS_ORDER'):
        statement(e, two, refund_evidence_id=other)


# --- completion -----------------------------------------------------------------------------

def test_cannot_complete_before_refund_or_statement(resolution_env, order_input):
    e = resolution_env; _, p, rid = recovered(e, order_input)
    snap = detail(e, rid)['snapshot']
    cmd = {'idempotency_key': 'early', 'snapshot_hash': snap['snapshot_hash'], 'refund_evidence_id': 'x',
        'statement_id': 'y', 'confirmed_reconciliation': True}
    with pytest.raises(DomainError, match='CUSTOMER_REFUND_EVIDENCE_REQUIRED'):
        e['resolution'].complete_marketplace_cancellation(rid, cmd, ADMIN)
    refund(e, rid)
    with pytest.raises(DomainError, match='MARKETPLACE_STATEMENT_REQUIRED'):
        e['resolution'].complete_marketplace_cancellation(rid, cmd | {'idempotency_key': 'early-2'}, ADMIN)
    with e['factory']() as s:assert s.get(Order, p.order_id).state == 'CANCEL_REQUESTED'


def corrupt(e, p, so, kind):
    """Synthetic fixture corruption emulating late or out-of-band facts; never an application path."""
    with e['factory'].begin() as s:
        order = s.get(Order, p.order_id)
        if kind == 'recovery_incomplete':s.scalar(select(SupplierCancellation)).status = 'FINANCIAL_REVIEW'
        elif kind == 'payment':s.get(Payment, p.id).status = 'UNKNOWN'
        elif kind == 'reservation':s.scalar(select(Reservation).where(Reservation.order_id == order.id)).status = 'RELEASED'
        elif kind == 'shipment':s.add(Shipment(order_id=order.id, courier='CJ', tracking='late-tracking-1'))
        elif kind == 'delivery':order.delivered_at = datetime(2026, 9, 26, tzinfo=timezone.utc)
        elif kind in {'claim', 'refund'}:
            claim = Claim(order_id=order.id, external_id='late-claim', category='OTHER', status='MANUAL_REVIEW',
                deadline=datetime(2026, 9, 30, tzinfo=timezone.utc), requested_amount=1000)
            s.add(claim); s.flush()
            if kind == 'refund':s.add(Refund(claim_id=claim.id, order_id=order.id, business_key='late-refund', amount=1000, status='PENDING'))
        elif kind == 'settlement':
            s.add(Settlement(order_id=order.id, external_id='late-settlement', expected=0, actual=0, difference=0, adjustment=0, input_hash='0'*64))
        elif kind == 'open_review':review(s, 'SUPPLIER_TERMS_CHANGED', so, {'late': True})
        elif kind == 'supplier_order':s.get(SupplierOrder, so).status = 'CANCEL_PENDING'
        elif kind == 'order_state':order.state = 'MANUAL_REVIEW'
        elif kind == 'journal':
            lock_treasury(s);post(s, f'sale:{order.id}', 'SALE_RECOGNIZED', {'MARKETPLACE_RECEIVABLE': 1, 'REVENUE': -1}, order.id)
        elif kind == 'identity':order.external_line_id = 'changed-line'
        elif kind == 'discount':order.discount = 1


@pytest.mark.parametrize('kind,code', [
    ('recovery_incomplete', 'SUPPLIER_FINANCIAL_RECOVERY_INCOMPLETE'),
    ('payment', 'PAYMENT_NOT_SUCCEEDED'),
    ('reservation', 'RESERVATION_NOT_SPENT'),
    ('shipment', 'ORDER_ALREADY_SHIPPED'),
    ('delivery', 'ORDER_ALREADY_DELIVERED'),
    ('claim', 'CLAIM_PRESENT'),
    ('refund', 'CLAIM_PRESENT|OTHER_CUSTOMER_REFUND_PRESENT'),
    ('settlement', 'SETTLEMENT_PRESENT'),
    ('open_review', 'CONFLICTING_UNRESOLVED_REVIEW'),
    ('supplier_order', 'SUPPLIER_ORDER_NOT_CANCELLED'),
    ('order_state', 'ORDER_NOT_CANCEL_REQUESTED'),
    ('journal', 'UNSUPPORTED_ORDER_ACCOUNTING'),
    ('identity', 'MARKETPLACE_CANCELLATION_SNAPSHOT_MISMATCH'),
    ('discount', 'MARKETPLACE_CANCELLATION_SNAPSHOT_MISMATCH'),
])
def test_completion_rechecks_every_invariant_under_lock(resolution_env, order_input, kind, code):
    e = resolution_env; so, p, rid = ready(e, order_input); payload = completion_payload(e, rid)
    corrupt(e, p, so, kind)
    with pytest.raises(DomainError, match=code):
        e['resolution'].complete_marketplace_cancellation(rid, payload, ADMIN)
    with e['factory']() as s:
        assert s.get(Order, p.order_id).state != 'CANCELLED'
        assert s.get(Review, rid).status == 'OPEN' and not s.scalar(select(MarketplaceCancellationReconciliation))
    assert detail(e, rid)['stage'] == 'BLOCKED' and not detail(e, rid)['eligible']


def test_completion_duplicate_idempotent_and_conflicting_rejected(resolution_env, order_input):
    e = resolution_env; _, _, rid = ready(e, order_input); payload = completion_payload(e, rid)
    late = refund_payload(e, rid, idempotency_key='late', reference='late-ref', evidence_hash='4'*64)
    first = e['resolution'].complete_marketplace_cancellation(rid, payload, ADMIN)
    assert first == e['resolution'].complete_marketplace_cancellation(rid, payload, ADMIN)
    assert first == e['resolution'].complete_marketplace_cancellation(rid, payload | {'idempotency_key': 'reopened'}, ADMIN)
    with pytest.raises(DomainError, match='IDEMPOTENCY_CONFLICT'):
        e['resolution'].complete_marketplace_cancellation(rid, payload | {'statement_id': 'other'}, ADMIN)
    with pytest.raises(DomainError, match='MARKETPLACE_RECONCILIATION_CONFLICT'):
        e['resolution'].complete_marketplace_cancellation(rid, payload | {'idempotency_key': 'k2', 'statement_id': 'other'}, ADMIN)
    # Evidence cannot be re-recorded differently after resolution.
    with pytest.raises(DomainError, match='MARKETPLACE_REFUND_EVIDENCE_CONFLICT'):
        e['resolution'].record_marketplace_refund(rid, late, ADMIN)
    assert counts(e) == {t.__table__.name: 1 for t in TABLES}


def test_completion_binds_exact_evidence_ids(resolution_env, order_input):
    e = resolution_env; _, _, rid = ready(e, order_input)
    with pytest.raises(DomainError, match='STALE_RECONCILIATION_EVIDENCE'):complete(e, rid, refund_evidence_id='stale')
    with pytest.raises(DomainError, match='STALE_RECONCILIATION_EVIDENCE'):complete(e, rid, idempotency_key='k2', statement_id='stale')


def test_completion_resolves_cancellation_after_payment_review(resolution_env, order_input):
    e = resolution_env; so, p, rid = ready(e, order_input)
    with e['factory'].begin() as s:after = review(s, 'CANCELLATION_AFTER_PAYMENT', p.order_id).id
    complete(e, rid)
    with e['factory']() as s:assert s.get(Review, after).status == 'RESOLVED'


def test_failure_after_transition_rolls_back_everything(resolution_env, order_input, monkeypatch):
    e = resolution_env; _, p, rid = ready(e, order_input); payload = completion_payload(e, rid)
    def fail(*a, **kw):raise DomainError('SYNTHETIC_FAILURE_AFTER_TRANSITION')
    monkeypatch.setattr(e['resolution'], '_resolved', fail)
    with pytest.raises(DomainError, match='SYNTHETIC_FAILURE'):
        e['resolution'].complete_marketplace_cancellation(rid, payload, ADMIN)
    with e['factory']() as s:
        assert s.get(Order, p.order_id).state == 'CANCEL_REQUESTED'
        assert not s.scalar(select(MarketplaceCancellationReconciliation)) and s.get(Review, rid).status == 'OPEN'


# --- cross-line marketplace identity --------------------------------------------------------

def test_second_line_blocks_reconciliation(resolution_env, order_input):
    e = resolution_env; so, p, rid = recovered(e, order_input)
    with e['factory']() as s:order = s.get(Order, p.order_id); external = order.external_id
    payload = refund_payload(e, rid)
    e['commerce'].ingest(dict(order_input, external_id=external, external_line_id='2'))
    with pytest.raises(DomainError, match='MULTI_LINE_MARKETPLACE_ORDER_UNSUPPORTED'):
        e['resolution'].record_marketplace_refund(rid, payload, ADMIN)
    assert detail(e, rid)['blocked_reason'] == 'MULTI_LINE_MARKETPLACE_ORDER_UNSUPPORTED'


@pytest.mark.parametrize('stage', ['refund', 'completed'])
def test_later_line_after_cancellation_evidence_fails_closed(resolution_env, order_input, stage):
    e = resolution_env; so, p, rid = recovered(e, order_input); refund(e, rid)
    if stage == 'completed':statement(e, rid); complete(e, rid)
    else:pending = statement_payload(e, rid)
    with e['factory']() as s:external = s.get(Order, p.order_id).external_id
    late = e['commerce'].ingest(dict(order_input, external_id=external, external_line_id='2'))
    assert late['state'] == 'MANUAL_REVIEW'
    with e['factory']() as s:
        held = s.scalar(select(Review).where(Review.category == LATE_LINE))
        assert held.entity_id == late['id'] and held.details['cancelled_order_id'] == p.order_id
        assert not s.scalar(select(Job).where(Job.business_key == f"order:{late['id']}"))
    e['worker'].drain()
    with e['factory']() as s:
        assert s.get(Order, late['id']).state == 'MANUAL_REVIEW'
        assert s.scalar(select(func.count()).select_from(SupplierOrder)) == 1
    if stage == 'refund':
        with pytest.raises(DomainError, match='MULTI_LINE_MARKETPLACE_ORDER_UNSUPPORTED'):
            e['resolution'].record_marketplace_statement(rid, pending, ADMIN)
        assert detail(e, rid)['blocked_reason'] == 'MULTI_LINE_MARKETPLACE_ORDER_UNSUPPORTED'
    else:
        with e['factory']() as s:assert s.get(Order, p.order_id).state == 'CANCELLED'  # completed history is not rewritten


# --- append-only, migration -----------------------------------------------------------------

def test_orm_rejects_update_and_delete(resolution_env, order_input):
    e = resolution_env; _, _, rid = ready(e, order_input); complete(e, rid)
    for cls in TABLES:
        with pytest.raises(ValueError, match='APPEND_ONLY'):
            with e['factory'].begin() as s:s.scalar(select(cls)).actor = 'overwrite'
        with pytest.raises(ValueError, match='APPEND_ONLY'):
            with e['factory'].begin() as s:s.delete(s.scalar(select(cls)))
    assert counts(e) == {t.__table__.name: 1 for t in TABLES}


def migrate_0004(e):
    with e['engine'].begin() as c:
        for t in reversed(PHASE11B_TABLES):t.drop(c)
        with Operations.context(MigrationContext.configure(c)):
            importlib.import_module('migrations.versions.0004_marketplace_cancellation').upgrade()


def downgrade_0004(e):
    with e['engine'].begin() as c:
        with Operations.context(MigrationContext.configure(c)):
            importlib.import_module('migrations.versions.0004_marketplace_cancellation').downgrade()


def test_migrated_tables_reject_sql_update_delete_and_populated_downgrade(resolution_env, order_input):
    e = resolution_env; migrate_0004(e); _, _, rid = ready(e, order_input); complete(e, rid)
    for table in PHASE11B_TABLES:
        for command in (f'UPDATE {table.name} SET id=id', f'DELETE FROM {table.name}'):
            with pytest.raises(DatabaseError, match='APPEND_ONLY'):
                with e['engine'].begin() as c:c.execute(text(command))
    with pytest.raises(RuntimeError, match='PHASE11B_DATA_PRESENT_DOWNGRADE_BLOCKED'):downgrade_0004(e)
    assert counts(e) == {t.__table__.name: 1 for t in TABLES}


def test_late_line_review_alone_blocks_downgrade(resolution_env, order_input):
    e = resolution_env; migrate_0004(e)
    with e['factory'].begin() as s:review(s, LATE_LINE, 'synthetic-order', {'cancelled_order_id': 'x'})
    with pytest.raises(RuntimeError, match='PHASE11B_REVIEW_PRESENT_DOWNGRADE_BLOCKED'):downgrade_0004(e)


def test_empty_migration_chain_0001_to_0004_roundtrip_and_frozen_snapshots(tmp_path):
    from packages.infrastructure import schema_v1, schema_v2, schema_v3, schema_v4
    from packages.infrastructure.db import database
    assert [len(x.metadata.tables) for x in (schema_v1, schema_v2, schema_v3, schema_v4)] == [28, 36, 40, 43]
    for name in ('marketplace_refund_evidence', 'marketplace_cancellation_statements', 'marketplace_cancellation_reconciliations'):
        assert name not in schema_v3.metadata.tables and name in schema_v4.metadata.tables
    engine, _ = database(f"sqlite:///{tmp_path/'chain.db'}")
    modules = [importlib.import_module('migrations.versions.' + x) for x in
        ('0001_initial', '0002_supplier_operations', '0003_review_resolution', '0004_marketplace_cancellation')]
    assert modules[3].down_revision == '0003' and modules[3].revision == '0004'
    with engine.begin() as c:
        with Operations.context(MigrationContext.configure(c)):
            for m in modules:m.upgrade()
    with engine.connect() as c:
        tables = set(c.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).scalars())
        assert set(schema_v4.metadata.tables) <= tables
    with engine.begin() as c:
        with Operations.context(MigrationContext.configure(c)):
            for m in reversed(modules):m.downgrade()
    with engine.connect() as c:
        assert not set(c.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).scalars()) & set(schema_v1.metadata.tables)
    engine.dispose()
