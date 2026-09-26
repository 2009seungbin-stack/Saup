"""Phase 11B HTTP boundary: admin-only typed commands, session/CSRF/Origin, no PII."""
import pytest
from sqlalchemy import select, func
from test_api_security import client
from test_supplier_api_security import user_login
from test_supplier_operations import excel_env
from test_review_resolution import resolution_env
from test_marketplace_cancellation import (recovered, refund_payload, statement_payload, completion_payload, refund,
    statement, TABLES)
from packages.infrastructure.models import Order

ACTIONS = ('record-marketplace-refund', 'record-marketplace-statement', 'complete-marketplace-cancellation')
FORBIDDEN_OUTPUT = ('pii_ciphertext', 'recipient', 'phone', '가상시', '010-0000', 'row_ciphertext', 'file_ciphertext')


def url(rid, action):
    return f'/v1/review-resolutions/{rid}/{action}'


@pytest.mark.parametrize('role', ['operator', 'viewer'])
def test_non_admin_cannot_mutate_customer_reconciliation(client, resolution_env, order_input, role):
    e = resolution_env; _, _, rid = recovered(e, order_input); payload = refund_payload(e, rid)
    headers = user_login(client, e, role)
    for action in ACTIONS:
        assert client.post(url(rid, action), headers=headers, json=payload).status_code == 403
    detail = client.get(f'/v1/review-resolutions/{rid}', headers=headers)
    if role == 'viewer':
        assert detail.status_code == 403
        rows = client.get('/v1/review-resolutions', headers=headers).json()
        row = next(x for x in rows if x['id'] == rid)
        assert set(row) == {'id', 'category', 'entity_id', 'status', 'resolution_code', 'resolved_by', 'resolved_at',
                            'created_at', 'action'}
    else:
        body = detail.json(); assert detail.status_code == 200 and body['stage'] == 'CUSTOMER_REFUND_EVIDENCE_MISSING'
        assert body['snapshot']['customer_refund_amount'] > 0
    with e['factory']() as s:
        assert all(not s.scalar(select(func.count()).select_from(cls)) for cls in TABLES)


def test_admin_http_flow_csrf_origin_validation_and_privacy(client, resolution_env, order_input):
    e = resolution_env; _, p, rid = recovered(e, order_input); headers = user_login(client, e, 'admin')
    payload = refund_payload(e, rid)
    assert client.post(url(rid, ACTIONS[0]), json=payload).status_code == 403  # no CSRF token
    assert client.post(url(rid, ACTIONS[0]), json=payload, headers=headers | {'Origin': 'https://evil.invalid'}).status_code == 403
    for bad in ({'confirmed_customer_refunded': 'true'}, {'confirmed_customer_refunded': 1}, {'customer_refund_amount': '1'},
                {'unexpected': 'field'}):
        assert client.post(url(rid, ACTIONS[0]), json=payload | bad, headers=headers).status_code == 422
    wrong = client.post(url(rid, ACTIONS[0]), json=payload | {'customer_refund_amount': 1}, headers=headers)
    assert wrong.status_code == 409 and wrong.json() == {'error': 'FULL_CUSTOMER_REFUND_REQUIRED'}
    first = client.post(url(rid, ACTIONS[0]), json=payload, headers=headers); assert first.status_code == 200, first.text
    assert client.post(url(rid, ACTIONS[0]), json=payload, headers=headers).json() == first.json()
    zero = statement_payload(e, rid); omitted = dict(zero); omitted.pop('outstanding_balance')
    assert client.post(url(rid, ACTIONS[1]), json=omitted, headers=headers).status_code == 422
    assert client.post(url(rid, ACTIONS[1]), json=zero, headers=headers).status_code == 200
    ready = client.get(f'/v1/review-resolutions/{rid}', headers=headers).json()
    assert ready['stage'] == 'READY_FOR_COMPLETION' and ready['money_sent'] is False
    done = client.post(url(rid, ACTIONS[2]), json=completion_payload(e, rid), headers=headers)
    assert done.status_code == 200 and done.json()['order_state'] == 'CANCELLED'
    for response in (client.get(f'/v1/review-resolutions/{rid}', headers=headers), client.get('/v1/review-resolutions', headers=headers)):
        for forbidden in FORBIDDEN_OUTPUT:
            assert forbidden not in response.text
    with e['factory']() as s:assert s.get(Order, p.order_id).state == 'CANCELLED'


def test_http_residual_statement_shows_block_and_rejects_completion(client, resolution_env, order_input):
    e = resolution_env; _, p, rid = recovered(e, order_input); headers = user_login(client, e, 'admin')
    refund(e, rid); statement(e, rid, retained_fee_amount=700)
    view = client.get(f'/v1/review-resolutions/{rid}', headers=headers).json()
    assert view['stage'] == 'BLOCKED_UNSUPPORTED_RESIDUAL_SETTLEMENT' and view['next_action'] is None
    assert view['marketplace_cancellation']['statement']['retained_fee_amount'] == 700
    blocked = client.post(url(rid, ACTIONS[2]), json=completion_payload(e, rid), headers=headers)
    assert blocked.status_code == 409 and blocked.json()['error'] == 'UNSUPPORTED_RESIDUAL_SETTLEMENT'
    with e['factory']() as s:assert s.get(Order, p.order_id).state == 'CANCEL_REQUESTED'
