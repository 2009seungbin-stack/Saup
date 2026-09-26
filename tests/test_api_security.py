from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from packages.infrastructure.models import User, AuthSession, Supplier, AuditEvent
from packages.infrastructure.security import hash_password, digest
from apps.api.main import create_app

@pytest.fixture
def client(env):
    with TestClient(create_app(env['settings'],env['factory'])) as client: yield client

def login(client,env,username='admin',password='test-admin-password'):
    response=client.post('/auth/login',json={'username':username,'password':password},headers={'Origin':env['settings'].public_origin})
    assert response.status_code==200,response.text
    return {'Origin':env['settings'].public_origin,'X-CSRF-Token':response.json()['csrf_token']}

def test_auth_and_no_pii_read_models(client,env,order_input):
    assert client.get('/health').status_code==200
    assert client.get('/v1/orders').status_code==401
    headers=login(client,env)
    response=client.post('/demo/orders',json=order_input,headers=headers)
    assert response.status_code==202,response.text
    env['worker'].drain()
    response=client.get('/v1/orders');assert response.status_code==200
    assert '가상시' not in response.text and '010-0000' not in response.text and 'pii_ciphertext' not in response.text
    assert client.get('/v1/overview').json()['automation']['production_rate'] is None

def test_csrf_origin_and_cookie_protection(client,env):
    response=client.post('/auth/login',json={'username':'admin','password':'test-admin-password'},headers={'Origin':'https://evil.invalid'})
    assert response.status_code==403
    headers=login(client,env)
    assert client.post('/demo/seed').status_code==403
    assert client.post('/demo/seed',headers={'Origin':env['settings'].public_origin}).status_code==403
    assert client.post('/demo/seed',headers=headers).status_code==200
    with env['factory']() as s:
        session=s.scalar(select(AuthSession));assert session.token_hash==digest(client.cookies['saup_session'])
    response=client.post('/auth/logout',headers=headers);assert response.status_code==200
    assert client.get('/auth/me').status_code==401

def test_viewer_cannot_mutate(client,env,order_input):
    with env['factory'].begin() as s:s.add(User(username='reader',password_hash=hash_password('reader-test-password'),role='viewer'))
    headers=login(client,env,'reader','reader-test-password')
    assert client.get('/v1/catalog').status_code==200
    assert client.post('/demo/orders',json=order_input,headers=headers).status_code==403
    assert client.get('/v1/export/'+env['ids']['profile_id']).status_code==403

def test_session_expiry(client,env):
    login(client,env)
    with env['factory'].begin() as s:
        row=s.scalar(select(AuthSession));row.expires_at=row.created_at-timedelta(seconds=1)
    assert client.get('/auth/me').status_code==401

def test_login_rate_limit_and_redacted_validation(client,env,monkeypatch):
    from types import SimpleNamespace
    # Freeze only the limiter's clock, not the process clock or auth/session time.
    # Otherwise eleven requests can straddle a real minute and correctly reset.
    clock=[1_800_000_030.0]
    monkeypatch.setattr('packages.infrastructure.security.time',SimpleNamespace(time=lambda:clock[0]))
    for i in range(10):
        r=client.post('/auth/login',json={'username':'absent','password':'wrong'},headers={'Origin':env['settings'].public_origin})
        assert r.status_code==401
    assert client.post('/auth/login',json={'username':'absent','password':'wrong'},headers={'Origin':env['settings'].public_origin}).status_code==429
    clock[0]+=60
    assert client.post('/auth/login',json={'username':'absent','password':'wrong'},headers={'Origin':env['settings'].public_origin}).status_code==401
    response=client.post('/auth/login',json={'username':'admin','password':'sensitive'*100})
    assert response.status_code==422 and 'sensitive' not in response.text

def test_upload_is_queued_then_processed(client,env):
    headers=login(client,env)
    response=client.post('/v1/imports/'+env['ids']['profile_id']+'/price',files={'file':('bad.xlsx',b'broken')},headers=headers)
    assert response.status_code==202
    assert client.get('/v1/imports').json()[0]['status']=='QUEUED'
    env['worker'].drain()
    assert client.get('/v1/imports').json()[0]['status']=='FAILED'

def test_destination_change_requires_different_admin(client,env):
    headers=login(client,env);sid=env['ids']['supplier_id'];dest='a'*64
    assert client.post(f'/v1/suppliers/{sid}/destination/propose',json={'destination_fingerprint':dest},headers=headers).status_code==200
    r=client.post(f'/v1/suppliers/{sid}/destination/approve',json={'destination_fingerprint':dest,'verified_reference':'verification-123'},headers=headers)
    assert r.status_code==403
    with env['factory']() as s:assert not s.get(Supplier,sid).destination_approved

def test_readiness_is_not_fake(client,env):
    assert client.get('/ready').status_code==503
    env['worker'].maintenance()
    assert client.get('/ready').status_code==200

def test_actual_request_body_limit(client,env):
    response=client.post('/auth/login',content=b'x'*(env['settings'].upload_max_bytes+100_001),headers={'Content-Type':'application/json'})
    assert response.status_code==413

def test_financial_trail_and_ledger_include_claim_and_settlement(client,env,order_input):
    from test_workflows import delivered
    from packages.application.after_sales import AfterSales,EVIDENCE
    from packages.infrastructure.models import Order
    oid=delivered(env,order_input);a=AfterSales(env['commerce']);cid=a.open_claim(oid,'trail-claim','ROTTEN',5000,list(EVIDENCE))
    env['worker'].drain();a.supplier_response(cid,2000,True);a.confirm_supplier_recovery(cid,2000,'trail-recovery')
    a.request_refund(cid,5000,'trail-refund');env['worker'].drain()
    with env['factory']() as s:o=s.get(Order,oid);expected=o.gross_sale-o.fee-5000
    sid=a.reconcile_settlement(oid,'trail-statement',expected);a.confirm_settlement_cash(sid,'trail-bank')
    login(client,env)
    events={row['event'] for row in client.get(f'/v1/orders/{oid}/trail').json()}
    assert {'ORDER_RECEIVED','SUPPLIER_ORDER_CREATED','SUPPLIER_PAYMENT_CREATED','MARKETPLACE_SHIPMENT_UPDATED','CLAIM_OPENED',
        'SUPPLIER_CLAIM_RESPONSE','REFUND_CREATED','SETTLEMENT_RECONCILED','SETTLEMENT_CASH_CONFIRMED'}.issubset(events)
    journals=client.get(f'/v1/orders/{oid}/ledger').json();assert journals and all(row['sum']==0 for row in journals)
    assert client.get('/v1/claims').json()[0]['customer_refund']==5000
    assert client.get('/v1/settlements').json()[0]['confirmed_cash'] is True

def test_api_discovery_and_probe(client,env):
    from packages.infrastructure.models import Product
    headers=login(client,env)
    response=client.post('/v1/discovery/evaluate',headers=headers,json={
        'demand':{'purchases':80,'review_velocity':80,'search_interest':80,'seasonality':80},
        'competition':{'review_barrier':20,'seller_concentration':20,'price_pressure':20,'sameness':20},
        'expected_margin':'0.2','source':'authorized synthetic export','sample_size':50})
    assert response.status_code==200 and response.json()['action']=='ENTER'
    with env['factory']() as s:pid=s.scalar(select(Product.id))
    response=client.post('/v1/experiments',headers=headers,json={'product_id':pid,'impressions':5000,'clicks':500,'carts':100,
        'orders':40,'claims':0,'contribution':-5000,'window_start':'2026-09-01T00:00:00+09:00','window_end':'2026-09-10T00:00:00+09:00'})
    assert response.status_code==200 and response.json()['state']=='REWORK' and not response.json()['automatically_scaled']
