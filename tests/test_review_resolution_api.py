"""Actual auth/session/CSRF/RBAC boundary for Phase 11A commands."""
import json
import pytest
from sqlalchemy import select
from test_api_security import client
from test_supplier_api_security import user_login, align_api_clock
from test_supplier_operations import excel_env,accepted_order,record,confirm,OP
from test_review_resolution import resolution_env,request,correction,cancel_paid,recovery_payload
from packages.infrastructure.models import Review, SupplierEvidenceRevision


@pytest.mark.parametrize('role',['operator','viewer'])
def test_non_admin_cannot_apply_correction_or_recovery(client,resolution_env,order_input,role):
    e=resolution_env;so,_,p=accepted_order(e,order_input);proof=record(e,p);rid=request(e,proof)['review_id']
    headers=user_login(client,e,role)
    a=client.post(f'/v1/review-resolutions/{rid}/correct-payment-evidence',headers=headers,json={
        'idempotency_key':'api-correct','expected_revision_id':None,'reference':'bank-receipt-001',
        'evidence_hash':'b'*64,'verified_same_payment':True})
    b=client.post(f'/v1/review-resolutions/{rid}/confirm-supplier-recovery',headers=headers,json=recovery_payload(e,p))
    assert a.status_code==b.status_code==403
    if role=='viewer':
        assert client.post(f"/v1/supplier-payment-evidence/{proof['id']}/correction-request",headers=headers,json={
            'idempotency_key':'api-request','reason':'WRONG_ATTACHMENT'}).status_code==403
        assert client.get(f'/v1/review-resolutions/{rid}').status_code==403
    with e['factory']() as s:assert not s.scalar(select(SupplierEvidenceRevision))


def test_correction_http_csrf_origin_snapshot_and_privacy(client,resolution_env,order_input):
    e=resolution_env;_,_,p=accepted_order(e,order_input);proof=record(e,p);headers=user_login(client,e,'admin')
    url=f"/v1/supplier-payment-evidence/{proof['id']}/correction-request"
    payload={'idempotency_key':'api-request','reason':'WRONG_ATTACHMENT','expected_revision_id':None}
    assert client.post(url,json=payload).status_code==403
    assert client.post(url,json=payload,headers=headers|{'Origin':'https://evil.invalid'}).status_code==403
    response=client.post(url,json=payload,headers=headers);assert response.status_code==201,response.text
    rid=response.json()['review_id']
    ack=client.post(f'/v1/reviews/{rid}/acknowledge',headers=headers,json={'reason':'seen-not-resolved'})
    assert ack.json()['status']=='ACKNOWLEDGED'
    data=client.get(f'/v1/review-resolutions/{rid}');assert data.json()['eligible']
    for output in (data,client.get('/v1/review-resolutions')):
        for forbidden in ('pii_ciphertext','recipient','phone','가상시','010-0000','row_ciphertext'):
            assert forbidden not in output.text
    correction_url=f'/v1/review-resolutions/{rid}/correct-payment-evidence'
    cmd={'idempotency_key':'api-correct','reference':'bank-receipt-001','evidence_hash':'b'*64,'verified_same_payment':True}
    assert client.post(correction_url,json=cmd|{'amount':1},headers=headers).status_code==422
    result=client.post(correction_url,json=cmd,headers=headers);assert result.status_code==200,result.text
    assert result.json()==client.post(correction_url,json=cmd,headers=headers).json()
    assert client.get(f'/v1/review-resolutions/{rid}').json()['status']=='RESOLVED'


def test_recovery_http_admin_only_explicit_attestation_and_customer_hold(client,resolution_env,order_input):
    e=resolution_env;so,_,p=accepted_order(e,order_input);confirm(e,p,record(e,p));rid=cancel_paid(e,so)
    headers=user_login(client,e,'admin');url=f'/v1/review-resolutions/{rid}/confirm-supplier-recovery';cmd=recovery_payload(e,p)
    assert client.post(url,json=cmd).status_code==403
    assert client.post(url,json=cmd|{'confirmed_funds_received':False},headers=headers).status_code==422
    bad=client.post(url,json=cmd|{'amount':1},headers=headers);assert bad.status_code==409
    result=client.post(url,json=cmd,headers=headers);assert result.status_code==200,result.text
    assert result.json()['order_state']=='CANCEL_REQUESTED'
    customer=client.get('/v1/review-resolutions/'+result.json()['customer_review_id']).json()
    assert not customer['eligible'] and customer['action'] is None
    assert client.post(url,json=cmd,headers=headers).json()==result.json()
