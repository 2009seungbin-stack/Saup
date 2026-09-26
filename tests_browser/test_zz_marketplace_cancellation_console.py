"""Phase 11B acceptance: external marketplace cancellation evidence through the real UI.

Setup uses the real supplier UI and authenticated same-origin HTTP only. No HTTP
mocking and no direct financial/order state mutation. Nothing here sends money.
"""
from hashlib import sha256
import json
from uuid import uuid4
from playwright.sync_api import expect
from test_supplier_console import api, ok, create_by_api, open_batch, send_ui, acknowledge_ui
from test_z_review_resolution_console import resolutions
from conftest import REPORTS, ORIGIN, docker_fixture

ACTIONS = ('record-marketplace-refund', 'record-marketplace-statement', 'complete-marketplace-cancellation')


def digest(label):
    return sha256(f'{label}-{uuid4().hex}'.encode()).hexdigest()


def recovered_via_http(page, admin, fixture_data):
    """Paid, supplier-cancelled and supplier-recovered (Phase 11A) order; customer side still open."""
    value, order, so = create_by_api(page, fixture_data)
    open_batch(page, value['id']); send_ui(page, value); state = acknowledge_ui(page, value)
    pid = state['items'][0]['payment_id']; d = ok(api(page, f'/v1/supplier-payments/{pid}'))
    method = 'SUPPLIER_DEPOSIT' if d['deposit_amount'] == d['amount'] else 'MANUAL_TRANSFER' if not d['deposit_amount'] else 'OTHER_APPROVED_METHOD'
    outgoing = 'e2e-11b-outgoing-' + so['id']
    proof = ok(api(page, f'/v1/supplier-payments/{pid}/evidence', 'POST', {k: d[k] for k in
        ('supplier_id', 'amount', 'bank_amount', 'deposit_amount', 'destination_fingerprint')} |
        {'method': method, 'reference': outgoing, 'evidence_hash': digest('outgoing')}))
    ok(api(admin, f"/v1/supplier-payment-evidence/{proof['id']}/confirm", 'POST', {'amount': d['amount'],
        'destination_fingerprint': d['destination_fingerprint'], 'reference': outgoing, 'confirmed_money_moved': True}))
    ok(api(admin, f"/v1/supplier-orders/{so['id']}/cancel", 'POST'))
    ok(api(admin, f"/v1/supplier-orders/{so['id']}/cancellation/confirm", 'POST',
        {'reference': 'e2e-11b-cancel-' + so['id'], 'supplier_confirmed_cancelled': True}))
    financial = next(x for x in ok(api(admin, '/v1/review-resolutions'))
                     if x['entity_id'] == so['id'] and x['category'] == 'SUPPLIER_CANCELLATION_FINANCIAL_REVIEW')
    snap = ok(api(admin, f"/v1/review-resolutions/{financial['id']}"))['snapshot']
    recovery = ok(api(admin, f"/v1/review-resolutions/{financial['id']}/confirm-supplier-recovery", 'POST',
        {k: snap[k] for k in ('payment_id', 'supplier_id', 'amount', 'bank_amount', 'deposit_amount', 'destination_fingerprint')} |
        {'idempotency_key': 'e2e-11b-recovery-' + so['id'], 'reference': 'e2e-11b-incoming-' + so['id'],
         'evidence_hash': digest('incoming'), 'confirmed_funds_received': True}))
    return order, so, pid, recovery['customer_review_id']


def open_review(page, rid, stage):
    resolutions(page); page.get_by_role('button', name=rid, exact=True).click()
    expect(page.locator(f'[data-stage="{stage}"]')).to_be_visible()


def record_refund_ui(admin, rid):
    admin.get_by_label('마켓 고객 환불 참조 번호', exact=True).fill('e2e-marketplace-refund-' + rid)
    admin.get_by_label('고객 환불 증빙 SHA-256', exact=True).fill(digest('customer-refund'))
    button = admin.get_by_role('button', name='고객 환불 증빙 기록', exact=True); expect(button).to_be_disabled()
    admin.get_by_label('마켓에서 고객에게 전액 환불이 이미 완료되었음을 증빙으로 확인했습니다. 이 기록은 송금하지 않습니다.', exact=True).check()
    with admin.expect_response(lambda r: r.url.endswith('/record-marketplace-refund') and r.request.method == 'POST') as response:
        button.click()
    assert response.value.status == 200, response.value.text()
    expect(admin.locator('[data-stage="MARKETPLACE_STATEMENT_MISSING"]')).to_be_visible()


def record_statement_ui(admin, rid, refund_amount, **amounts):
    values = {'판매자 지급액': 0, '판매자 차감액': 0, '마켓 보유 수수료': 0, '미결 잔액': 0} | amounts
    button = admin.get_by_role('button', name='최종 정산서 기록', exact=True)
    admin.get_by_label('정산서 고객 환불액', exact=True).fill(str(refund_amount))
    for label, value in values.items():
        admin.get_by_label(label, exact=True).fill(str(value))  # zero is typed explicitly, never defaulted
    admin.get_by_label('마켓 정산서 참조 번호', exact=True).fill('e2e-marketplace-statement-' + rid)
    admin.get_by_label('정산서 증빙 SHA-256', exact=True).fill(digest('statement'))
    admin.get_by_label('이 문서가 해당 주문행의 최종 취소 정산서임을 확인했습니다.', exact=True).check()
    expect(button).to_be_disabled()
    admin.get_by_label('마켓에서 주문 취소가 완료되었음을 확인했습니다.', exact=True).check()
    with admin.expect_response(lambda r: r.url.endswith('/record-marketplace-statement') and r.request.method == 'POST') as response:
        button.click()
    assert response.value.status == 200, response.value.text()


def test_marketplace_cancellation_reconciliation_ui(pages, fixture_data):
    page = pages(); admin = pages('admin')
    order, so, pid, rid = recovered_via_http(page, admin, fixture_data)
    before = docker_fixture('snapshot')
    assert before['orders'][order['id']]['state'] == 'CANCEL_REQUESTED'
    open_review(admin, rid, 'CUSTOMER_REFUND_EVIDENCE_MISSING')
    expect(admin.get_by_text('this does not send money', exact=False).first).to_be_visible()
    detail = ok(api(admin, f'/v1/review-resolutions/{rid}')); required = detail['snapshot']['customer_refund_amount']
    record_refund_ui(admin, rid)
    record_statement_ui(admin, rid, required)
    expect(admin.locator('[data-stage="READY_FOR_COMPLETION"]')).to_be_visible()
    button = admin.get_by_role('button', name='마켓 취소 대사 완료', exact=True); expect(button).to_be_disabled()
    admin.get_by_label('기록된 고객 환불 증빙과 0원 최종 정산서를 재확인했으며 이 명령이 송금하지 않음을 이해합니다.', exact=True).check()
    with admin.expect_response(lambda r: r.url.endswith('/complete-marketplace-cancellation') and r.request.method == 'POST') as response:
        button.click()
    assert response.value.status == 200; result = response.value.json(); command = response.value.request.post_data_json
    expect(admin.locator('[data-stage="RESOLVED"]')).to_be_visible()
    expect(admin.get_by_text('검토 상태: RESOLVED', exact=True)).to_be_visible()
    assert ok(api(admin, f'/v1/review-resolutions/{rid}/complete-marketplace-cancellation', 'POST', command)) == result
    after = docker_fixture('snapshot'); observed = after['orders'][order['id']]
    assert observed['state'] == 'CANCELLED' and observed['supplier_state'] == 'CANCELLED'
    assert observed['payment_status'] == 'SUCCEEDED' and observed['reservation_status'] == 'SPENT'
    assert observed['shipment_id'] is None and observed['marketplace_reconciliation_id'] == result['reconciliation_id']
    for table in ('marketplace_refund_evidence', 'marketplace_cancellation_statements', 'marketplace_cancellation_reconciliations'):
        assert after['counts'][table] == before['counts'][table] + 1
    # Evidence only: no ledger movement, no balance change, no refund/money job.
    assert after['journal_count'] == before['journal_count'] and after['accounts'] == before['accounts']
    assert after['job_counts'].get('refund.execute', 0) == before['job_counts'].get('refund.execute', 0) == 0
    assert after['job_counts'].get('payment.execute', 0) == before['job_counts'].get('payment.execute', 0)
    assert after['balanced_journals']
    (REPORTS / 'phase11b-marketplace-cancellation.json').write_text(json.dumps({'result': result, 'before': before, 'after': after}, indent=2))


def test_marketplace_cancellation_rbac_csrf_and_residual_block(pages, fixture_data):
    page = pages(); admin = pages('admin'); viewer = pages('viewer')
    order, so, pid, rid = recovered_via_http(page, admin, fixture_data)
    # Viewer: status/IDs only.
    resolutions(viewer); expect(viewer.get_by_role('button', name=rid, exact=True)).not_to_be_visible()
    row = next(x for x in ok(api(viewer, '/v1/review-resolutions')) if x['id'] == rid)
    assert 'snapshot' not in row and 'marketplace_cancellation' not in row and 'stage' not in row
    assert api(viewer, f'/v1/review-resolutions/{rid}')['status'] == 403
    # Operator: safe detail, no financial mutation.
    open_review(page, rid, 'CUSTOMER_REFUND_EVIDENCE_MISSING')
    expect(page.get_by_text('관리자만 마켓 취소 대사 명령을 실행할 수 있습니다.', exact=True)).to_be_visible()
    expect(page.get_by_role('button', name='고객 환불 증빙 기록', exact=True)).to_have_count(0)
    detail = ok(api(page, f'/v1/review-resolutions/{rid}')); snap = detail['snapshot']
    refund = {'idempotency_key': 'e2e-forbidden', 'snapshot_hash': snap['snapshot_hash'],
        'supplier_recovery_id': snap['supplier_recovery_id'], 'marketplace': snap['marketplace'],
        'external_order_id': snap['external_order_id'], 'external_line_id': snap['external_line_id'],
        'customer_refund_amount': snap['customer_refund_amount'], 'reference': 'e2e-forbidden-' + rid,
        'evidence_hash': digest('forbidden'), 'confirmed_customer_refunded': True}
    for actor in (page, viewer):
        for action in ACTIONS:
            assert api(actor, f'/v1/review-resolutions/{rid}/{action}', 'POST', refund)['status'] == 403
    # Admin session without CSRF token, and with a foreign Origin, is refused server-side.
    assert api(admin, f'/v1/review-resolutions/{rid}/{ACTIONS[0]}', 'POST', refund, csrf=False)['status'] == 403
    token = next(c['value'] for c in admin.context.cookies() if c['name'] == 'saup_csrf')
    foreign = admin.context.request.post(f'{ORIGIN}/api/v1/review-resolutions/{rid}/{ACTIONS[0]}', data=refund,
        headers={'Origin': 'https://evil.invalid', 'X-CSRF-Token': token, 'Content-Type': 'application/json'})
    assert foreign.status == 403
    assert detail['marketplace_cancellation']['refund_evidence'] is None
    # Admin: nonzero seller residual is recorded as evidence but blocks completion.
    open_review(admin, rid, 'CUSTOMER_REFUND_EVIDENCE_MISSING')
    record_refund_ui(admin, rid)
    record_statement_ui(admin, rid, snap['customer_refund_amount'], **{'마켓 보유 수수료': 700})
    expect(admin.locator('[data-stage="BLOCKED_UNSUPPORTED_RESIDUAL_SETTLEMENT"]')).to_be_visible()
    expect(admin.get_by_text('현재 실행 불가: UNSUPPORTED_RESIDUAL_SETTLEMENT', exact=True)).to_be_visible()
    expect(admin.get_by_role('button', name='마켓 취소 대사 완료', exact=True)).to_have_count(0)
    records = ok(api(admin, f'/v1/review-resolutions/{rid}'))['marketplace_cancellation']
    blocked = api(admin, f'/v1/review-resolutions/{rid}/{ACTIONS[2]}', 'POST', {'idempotency_key': 'e2e-blocked',
        'snapshot_hash': snap['snapshot_hash'], 'refund_evidence_id': records['refund_evidence']['id'],
        'statement_id': records['statement']['id'], 'confirmed_reconciliation': True})
    assert blocked['status'] == 409 and blocked['body']['error'] == 'UNSUPPORTED_RESIDUAL_SETTLEMENT'
    residual = [x for x in ok(api(admin, '/v1/review-resolutions')) if x['category'] == 'MARKETPLACE_CANCELLATION_RESIDUAL_SETTLEMENT']
    assert any(x['entity_id'] == records['statement']['id'] and x['status'] == 'OPEN' for x in residual)
    observed = docker_fixture('snapshot')['orders'][order['id']]
    assert observed['state'] == 'CANCEL_REQUESTED' and observed['payment_status'] == 'SUCCEEDED'
    assert observed['reservation_status'] == 'SPENT' and observed['marketplace_reconciliation_id'] is None
