"""Exercise the actual HTTP auth/CSRF/RBAC boundary, not only domain roles."""
import pytest
from sqlalchemy import select
from packages.infrastructure.models import User, Review, SupplierOrderBatch, SupplierPaymentEvidence
from packages.infrastructure.security import hash_password
from test_api_security import client, login
from test_supplier_operations import (excel_env, make_order, batch, send, ack, payment, record,
                                     proof_payload, accepted_order, ADMIN, OP)


def user_login(client, env, role):
    if role == "admin":
        return login(client, env)
    name = "supplier-"+role
    with env["factory"].begin() as s:
        s.add(User(username=name, password_hash=hash_password("supplier-test-password"), role=role))
    return login(client, env, name, "supplier-test-password")


def test_supplier_reads_exclude_pii_and_encrypted_payloads(client, excel_env, order_input):
    e=excel_env; so=make_order(e,order_input); b=batch(e,[so])
    user_login(client,e,"viewer")
    for url in ("/v1/supplier-order-batches", f"/v1/supplier-order-batches/{b['id']}", f"/v1/supplier-order-batches/{b['id']}/trail"):
        response=client.get(url); assert response.status_code==200,response.text
        for forbidden in ("010-0000", "가상시", "recipient", "pii_ciphertext", "row_ciphertext", "file_ciphertext", "profile_snapshot"):
            assert forbidden not in response.text
    assert client.get(f"/v1/supplier-order-batches/{b['id']}/file").status_code==403


@pytest.mark.parametrize("action",["create","sent","ack","cancel","resolve","evidence","confirm","revalidate","confirm_cancel"])
def test_viewer_cannot_mutate_any_supplier_command(client,excel_env,order_input,action):
    e=excel_env; so,b,p=accepted_order(e,order_input); proof=record(e,p)
    headers=user_login(client,e,"viewer")
    routes={
        "create":("/v1/supplier-order-batches",{"supplier_id":e['ids']['supplier_id'],"profile_id":e['ids']['profile_id'],"supplier_order_ids":[so],"idempotency_key":"api-create"}),
        "sent":(f"/v1/supplier-order-batches/{b['id']}/mark-sent",{"send_channel":"EMAIL","send_reference":"api-sent","file_hash":b['file_hash']}),
        "ack":(f"/v1/supplier-order-batches/{b['id']}/acknowledge",{"reference":"api-ack","accepted_order_ids":[so]}),
        "cancel":(f"/v1/supplier-order-batches/{b['id']}/cancel",None),
        "resolve":(f"/v1/supplier-order-batches/{b['id']}/resolve",None),
        "evidence":(f"/v1/supplier-payments/{p.id}/evidence",proof_payload(e,p)),
        "confirm":(f"/v1/supplier-payment-evidence/{proof['id']}/confirm",{"amount":p.amount,"destination_fingerprint":p.destination_fingerprint,"reference":"bank-receipt-001","confirmed_money_moved":True}),
        "revalidate":(f"/v1/supplier-orders/{so}/revalidate",{"reference":"revalidate","original_terms_reconfirmed":True}),
        "confirm_cancel":(f"/v1/supplier-orders/{so}/cancellation/confirm",{"reference":"cancellation","supplier_confirmed_cancelled":True}),
    }
    url,body=routes[action]
    r=client.post(url,json=body,headers=headers)
    assert r.status_code==403,r.text


def test_operator_cannot_confirm_payment_evidence(client,excel_env,order_input):
    e=excel_env; so,b,p=accepted_order(e,order_input); proof=record(e,p)
    headers=user_login(client,e,"operator")
    r=client.post(f"/v1/supplier-payment-evidence/{proof['id']}/confirm",headers=headers,json={
        "amount":p.amount,"destination_fingerprint":p.destination_fingerprint,"reference":"bank-receipt-001","confirmed_money_moved":True})
    assert r.status_code==403
    assert payment(e,so).status=='EVIDENCE_PENDING'


def test_supplier_commands_enforce_csrf_and_origin(client,excel_env,order_input):
    e=excel_env; so=make_order(e,order_input); b=batch(e,[so]); headers=user_login(client,e,"operator")
    url=f"/v1/supplier-order-batches/{b['id']}/mark-sent"
    data={"send_channel":"PORTAL","send_reference":"portal-001","file_hash":b['file_hash']}
    assert client.post(url,json=data).status_code==403
    assert client.post(url,json=data,headers={"Origin":e['settings'].public_origin}).status_code==403
    assert client.post(url,json=data,headers=headers|{"Origin":"https://evil.invalid"}).status_code==403
    assert client.post(url,json=data,headers=headers).status_code==200
    assert client.post(url,json=data,headers=headers).status_code==200


def test_api_create_and_download_returns_frozen_binary(client,excel_env,order_input):
    e=excel_env; so=make_order(e,order_input); headers=user_login(client,e,"operator")
    payload={"supplier_id":e['ids']['supplier_id'],"profile_id":e['ids']['profile_id'],"supplier_order_ids":[so],"idempotency_key":"api-batch-001"}
    first=client.post('/v1/supplier-order-batches',json=payload,headers=headers)
    assert first.status_code==201,first.text
    repeat=client.post('/v1/supplier-order-batches',json=payload,headers=headers)
    assert repeat.json()['id']==first.json()['id']
    r=client.get(f"/v1/supplier-order-batches/{first.json()['id']}/file")
    assert r.status_code==200 and r.content[:2]==b'PK' and r.headers['Cache-Control']=='no-store'
    assert 'attachment' in r.headers['Content-Disposition']


def test_review_ack_does_not_resolve_or_reopen_resolved_business_issue(client,excel_env,order_input):
    e=excel_env; so=make_order(e,order_input); b=batch(e,[so]); headers=user_login(client,e,"operator")
    with e['factory']() as s:
        row=s.scalar(select(Review).where(Review.category=='SUPPLIER_FILE_ACK_REQUIRED')); rid=row.id
    r=client.post(f'/v1/reviews/{rid}/acknowledge',json={'reason':'seen-not-accepted'},headers=headers)
    assert r.status_code==200 and r.json()['status']=='ACKNOWLEDGED'
    assert payment(e,so) is None
    send(e,b);ack(e,b)
    r=client.post(f'/v1/reviews/{rid}/acknowledge',json={'reason':'seen-again'},headers=headers)
    assert r.status_code==200 and r.json()['status']=='RESOLVED'

@pytest.fixture(autouse=True)
def align_api_clock(client, excel_env):
    # API factory owns a second Commerce instance; both test clocks must agree.
    client.app.state.commerce.clock = excel_env['commerce'].clock
