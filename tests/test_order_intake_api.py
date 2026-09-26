"""Session/RBAC/CSRF/Origin and non-demo routes, with no plaintext PII views."""
import json
import pytest
from test_api_security import client
from test_supplier_api_security import user_login, align_api_clock
from test_supplier_operations import excel_env, OP
from test_order_intake import intake, file_for, import_file, verify_payload


def upload(client, url, data, headers, fields):
    return client.post(url,files={'file':('orders.xlsx',data,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')},
        data=fields,headers=headers)


def test_api_import_current_verification_and_templates(client,excel_env,order_input):
    e=excel_env;headers=user_login(client,e,'operator');data=file_for(order_input)
    for url in ('/v1/order-imports/template','/v1/order-imports/catalog?marketplace=coupang'):
        r=client.get(url);assert r.status_code==200 and r.content.startswith(b'PK')
    p=upload(client,'/v1/order-imports/preview',data,headers,{'marketplace':'coupang'})
    assert p.status_code==200,p.text
    cmd={'marketplace':'coupang','preview_token':p.json()['preview_token'],'source_reference':'api-export','confirmed_authorized_source':True}
    r=upload(client,'/v1/order-imports/commit',data,headers,{'command':json.dumps(cmd)})
    assert r.status_code==201,r.text;oid=r.json()['items'][0]['id']
    second=upload(client,'/v1/order-imports/commit',data,headers,{'command':json.dumps(cmd)})
    assert second.json()['id']==r.json()['id'] and second.json()['replayed']
    d=client.get(f'/v1/order-intake/{oid}');assert d.json()['can_verify_and_validate']
    for output in (p,r,d,client.get('/v1/order-intake/pending'),client.get('/v1/order-imports')):
        for forbidden in ('010-0000','가상시','recipient','pii_ciphertext','original_address'):
            assert forbidden not in output.text
    v={'idempotency_key':'api-verify','snapshot_hash':d.json()['snapshot_hash'],'source_reference':'api-current',
        'evidence_hash':'e'*64,'observed_at':e['commerce'].clock().isoformat(),'confirmed_current_order_open':True}
    result=client.post(f'/v1/order-intake/{oid}/verify-and-validate',json=v,headers=headers)
    assert result.status_code==200,result.text
    assert result.json()['state']=='SUPPLIER_ORDER_PENDING' and not result.json()['api_verified']


def test_viewer_only_history(client,excel_env,order_input):
    headers=user_login(client,excel_env,'viewer');data=file_for(order_input)
    assert client.get('/v1/order-imports').status_code==200
    for url in ('/v1/order-imports/template','/v1/order-imports/catalog?marketplace=coupang','/v1/order-intake/pending','/v1/order-intake/unknown'):
        assert client.get(url).status_code==403
    assert upload(client,'/v1/order-imports/preview',data,headers,{'marketplace':'coupang'}).status_code==403
    assert upload(client,'/v1/order-imports/commit',data,headers,{'command':'{}'}).status_code==403
    assert client.post('/v1/order-intake/unknown/verify-and-validate',json={},headers=headers).status_code==403


def test_order_file_csrf_origin_and_confirmation_validation(client,excel_env,order_input):
    headers=user_login(client,excel_env,'operator');data=file_for(order_input)
    for h in ({},{'Origin':excel_env['settings'].public_origin},headers|{'Origin':'https://evil.invalid'}):
        assert upload(client,'/v1/order-imports/preview',data,h,{'marketplace':'coupang'}).status_code==403
    p=upload(client,'/v1/order-imports/preview',data,headers,{'marketplace':'coupang'}).json()
    for value in ('true',1,False,None):
        command={'marketplace':'coupang','preview_token':p['preview_token'],'source_reference':'source','confirmed_authorized_source':value}
        assert upload(client,'/v1/order-imports/commit',data,headers,{'command':json.dumps(command)}).status_code==422
    assert upload(client,'/v1/order-imports/preview',data,headers,{'marketplace':'invented'}).status_code==422


def test_verify_route_csrf_and_boolean_validation(client,excel_env,intake,order_input):
    r,_=import_file(intake,file_for(order_input));oid=r['items'][0]['id'];cmd=verify_payload(intake,oid)
    headers=user_login(client,excel_env,'operator')
    url=f'/v1/order-intake/{oid}/verify-and-validate'
    assert client.post(url,json=cmd).status_code==403
    assert client.post(url,json=cmd,headers=headers|{'Origin':'https://evil.invalid'}).status_code==403
    assert client.post(url,json=cmd|{'confirmed_current_order_open':1},headers=headers).status_code==422
    assert client.post(url,json=cmd|{'observed_at':'2026-09-26T01:00:00'},headers=headers).status_code==422
