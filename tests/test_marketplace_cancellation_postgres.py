"""Phase 11B races on real PostgreSQL. SQLite results are never evidence for these cases."""
import pytest
from sqlalchemy import select, func, text
from sqlalchemy.exc import DatabaseError
from test_supplier_postgres import pg_excel_env, race, sample
from test_marketplace_cancellation import (recovered, refund_payload, statement_payload, completion_payload, refund,
    statement, TABLES)
from test_supplier_operations import ADMIN
from packages.application.review_resolution import ReviewResolutionService
from packages.application.marketplace_cancellation import LATE_LINE
from packages.infrastructure.models import (Order, Payment, Reservation, Review, ReviewResolution, Journal, Posting, Job,
    MarketplaceRefundEvidence, MarketplaceCancellationStatement, MarketplaceCancellationReconciliation)
from packages.infrastructure.schema_v4 import PHASE11B_TABLES


def setup(e):
    e['resolution'] = ReviewResolutionService(e['commerce'])
    return e


def count(e, cls, *where):
    with e['factory']() as s:
        return s.scalar(select(func.count()).select_from(cls).where(*where))


def assert_money_untouched(e, p):
    with e['factory']() as s:
        assert s.get(Payment, p.id).status == 'SUCCEEDED'
        assert s.scalar(select(Reservation).where(Reservation.order_id == p.order_id)).status == 'SPENT'
        assert not s.scalar(select(Job).where(Job.kind == 'refund.execute'))
        assert not s.execute(select(Posting.journal_id).group_by(Posting.journal_id).having(func.sum(Posting.delta) != 0)).all()
        assert set(s.scalars(select(Journal.kind).where(Journal.order_id == p.order_id))) == {'SUPPLIER_PAYMENT', 'SUPPLIER_RECOVERY'}


@pytest.mark.postgres
def test_postgres_duplicate_refund_statement_and_completion_have_one_effect(pg_excel_env):
    e = setup(pg_excel_env); _, p, rid = recovered(e, sample(e)); svc = e['resolution']
    payload = refund_payload(e, rid)
    results = race(lambda: svc.record_marketplace_refund(rid, payload, ADMIN)); assert results[0] == results[1] and results[0][0] == 'ok'
    # A reopened browser (new idempotency key, same evidence) racing the original request.
    results = race(lambda: svc.record_marketplace_refund(rid, payload, ADMIN),
                   lambda: svc.record_marketplace_refund(rid, payload | {'idempotency_key': 'reopened'}, ADMIN))
    assert results[0] == results[1]
    payload = statement_payload(e, rid)
    results = race(lambda: svc.record_marketplace_statement(rid, payload, ADMIN)); assert results[0] == results[1] and results[0][0] == 'ok'
    payload = completion_payload(e, rid)
    results = race(lambda: svc.complete_marketplace_cancellation(rid, payload, ADMIN)); assert results[0] == results[1] and results[0][0] == 'ok'
    for cls in TABLES:
        assert count(e, cls) == 1
    assert count(e, ReviewResolution, ReviewResolution.review_id == rid) == 1
    with e['factory']() as s:assert s.get(Order, p.order_id).state == 'CANCELLED'
    assert_money_untouched(e, p)
    for table in PHASE11B_TABLES:
        for action in (f'UPDATE {table.name} SET id=id', f'DELETE FROM {table.name}'):
            with pytest.raises(DatabaseError, match='APPEND_ONLY'):
                with e['engine'].begin() as c:c.execute(text(action))


@pytest.mark.postgres
def test_postgres_same_marketplace_refund_receipt_competes_across_two_orders(pg_excel_env):
    e = setup(pg_excel_env); reviews = []
    for i in range(2):
        _, _, rid = recovered(e, sample(e), name=f'refund-race-{i}', key=f'batch-{i}', outgoing=f'out-{i}',
                              incoming=f'in-{i}', receipt_hash=str(i+1)*64)
        reviews.append((rid, refund_payload(e, rid, idempotency_key=f'refund-{i}', reference='shared-marketplace-refund',
                                            evidence_hash='e'*64)))
    results = race(*[lambda rid=rid, payload=payload: e['resolution'].record_marketplace_refund(rid, payload, ADMIN)
                     for rid, payload in reviews])
    assert sorted(k for k, _ in results) == ['conflict', 'ok']
    assert next(v for k, v in results if k == 'conflict') in {'MARKETPLACE_EVIDENCE_HASH_IN_USE', 'MARKETPLACE_EVIDENCE_REFERENCE_IN_USE'}
    assert count(e, MarketplaceRefundEvidence) == 1


@pytest.mark.postgres
def test_postgres_statement_racing_completion_never_completes_without_statement(pg_excel_env):
    e = setup(pg_excel_env); _, p, rid = recovered(e, sample(e)); svc = e['resolution']; refund(e, rid)
    record = statement_payload(e, rid)
    snapshot = svc.get_review(rid)['snapshot']['snapshot_hash']
    early = {'idempotency_key': 'early-completion', 'snapshot_hash': snapshot,
             'refund_evidence_id': record['refund_evidence_id'], 'statement_id': 'not-yet-visible',
             'confirmed_reconciliation': True}
    results = race(lambda: svc.record_marketplace_statement(rid, record, ADMIN),
                   lambda: svc.complete_marketplace_cancellation(rid, early, ADMIN))
    assert results[0][0] == 'ok' and results[1] in {('conflict', 'MARKETPLACE_STATEMENT_REQUIRED'),
                                                    ('conflict', 'STALE_RECONCILIATION_EVIDENCE')}
    assert count(e, MarketplaceCancellationStatement) == 1 and count(e, MarketplaceCancellationReconciliation) == 0
    with e['factory']() as s:assert s.get(Order, p.order_id).state == 'CANCEL_REQUESTED'
    # The explicit, current-evidence completion still works afterwards.
    assert svc.complete_marketplace_cancellation(rid, completion_payload(e, rid), ADMIN)['order_state'] == 'CANCELLED'
    assert_money_untouched(e, p)


@pytest.mark.postgres
def test_postgres_completion_racing_late_marketplace_line_fails_closed(pg_excel_env):
    e = setup(pg_excel_env); _, p, rid = recovered(e, sample(e)); svc = e['resolution']; refund(e, rid); statement(e, rid)
    payload = completion_payload(e, rid)
    with e['factory']() as s:order = s.get(Order, p.order_id); line = sample(e) | {'external_id': order.external_id, 'external_line_id': '2'}
    results = race(lambda: svc.complete_marketplace_cancellation(rid, payload, ADMIN), lambda: e['commerce'].ingest(line))
    completion, ingest = results
    assert ingest[0] == 'ok' and ingest[1]['state'] == 'MANUAL_REVIEW'  # the late line is always held, never fulfilled
    with e['factory']() as s:
        held = s.scalar(select(Review).where(Review.category == LATE_LINE))
        assert held and held.entity_id == ingest[1]['id'] and held.status == 'OPEN'
        state = s.get(Order, p.order_id).state
    if completion[0] == 'ok':
        assert state == 'CANCELLED' and count(e, MarketplaceCancellationReconciliation) == 1
    else:
        assert completion[1] == 'MULTI_LINE_MARKETPLACE_ORDER_UNSUPPORTED'
        assert state == 'CANCEL_REQUESTED' and count(e, MarketplaceCancellationReconciliation) == 0
    assert_money_untouched(e, p)


@pytest.mark.postgres
def test_postgres_completion_racing_conflicting_completion_has_one_winner(pg_excel_env):
    e = setup(pg_excel_env); _, p, rid = recovered(e, sample(e)); svc = e['resolution']; refund(e, rid); statement(e, rid)
    good = completion_payload(e, rid); bad = good | {'idempotency_key': 'other-tab', 'statement_id': 'stale-statement'}
    results = race(lambda: svc.complete_marketplace_cancellation(rid, good, ADMIN),
                   lambda: svc.complete_marketplace_cancellation(rid, bad, ADMIN))
    assert results[0][0] == 'ok' and results[1][0] == 'conflict'
    assert results[1][1] in {'STALE_RECONCILIATION_EVIDENCE', 'MARKETPLACE_RECONCILIATION_CONFLICT'}
    assert count(e, MarketplaceCancellationReconciliation) == 1
    assert count(e, ReviewResolution, ReviewResolution.review_id == rid) == 1
    assert_money_untouched(e, p)
