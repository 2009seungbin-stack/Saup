import json
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from packages.infrastructure.settings import Settings
from packages.infrastructure.db import database
from packages.infrastructure.models import Base, Order, OperationalReceipt, Posting, Claim, Refund, Settlement, Journal, Account, ExternalRecord
from packages.application.seed import seed
from packages.application.commerce import Commerce
from packages.application.operations import Operations
from packages.application.after_sales import AfterSales, EVIDENCE
from packages.domain.errors import DomainError
from apps.api.main import create_app
from apps.worker.main import Worker
from scripts.closure_scenario import run, evidence
from test_supplier_operations import ADMIN, OP, VIEWER
from test_workflows import delivered


@pytest.fixture
def blank(tmp_path):
    settings=Settings(_env_file=None,app_mode='test',database_url=f"sqlite:///{tmp_path/'blank.db'}",
        pii_encryption_key=Fernet.generate_key().decode(),admin_password='Synthetic-first-admin-123!')
    engine,factory=database(settings.database_url);Base.metadata.create_all(engine);seed(settings,factory,demo=False)
    c=Commerce(settings,factory); app=create_app(settings,factory); worker=Worker(c)
    clients={name:TestClient(app) for name in ['admin','second']}
    def login(name,username,password):
        client=clients[name];r=client.post('/auth/login',json={'username':username,'password':password},headers={'Origin':settings.public_origin})
        assert r.status_code==200
        client.headers.update({'Origin':settings.public_origin,'X-CSRF-Token':r.json()['csrf_token']})
    login('admin','admin',settings.admin_password.get_secret_value())
    def call(method,path,body=None,file=None,actor='admin',binary=False):
        kwargs={'files':{'file':('input.xlsx',file,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')},'data':body} if file else {'json':body} if body is not None else {}
        r=clients[actor].request(method,path,**kwargs)
        assert r.status_code<300,(path,r.status_code,r.text)
        return r.content if binary else r.json()
    yield {'settings':settings,'factory':factory,'engine':engine,'commerce':c,'worker':worker,'call':call,'clients':clients,'login':login}
    for client in clients.values():client.close()
    engine.dispose()


def test_blank_install_full_operational_api_closure(blank):
    e=blank
    result=run(e['call'],lambda:e['login']('second','second-admin','Synthetic-second-admin-123!'),e['worker'].drain)
    with e['factory']() as s:
        assert s.scalar(select(func.count()).select_from(Order))==3
        assert s.scalar(select(func.count()).select_from(Refund))==2
        assert s.scalar(select(func.count()).select_from(Settlement))==2
        assert all(total==0 for total in s.scalars(select(func.sum(Posting.delta)).group_by(Posting.journal_id)))
        assert not s.scalar(select(ExternalRecord.id).where(ExternalRecord.namespace.not_like('notification%')))
        for cls in (OperationalReceipt,):
            text=json.dumps([x.payload for x in s.scalars(select(cls))])
            assert 'Synthetic Customer' not in text and '010-0000' not in text and 'Synthetic-second-admin-123!' not in text
    assert result['synthetic_only']


def test_setup_funds_replay_conflict_and_supplier_isolation(blank):
    e=blank;ops=Operations(e['commerce']);cmd=evidence('opening',amount=1000000)
    assert ops.funds(cmd,ADMIN)==ops.funds(cmd,ADMIN)
    with pytest.raises(DomainError,match='CONFIRMATION_CONFLICT'):ops.funds(cmd|{'amount':1000001},ADMIN)
    ids=[ops.supplier({'name':name,'cutoff':'23:59','claim_days':3,'active':True},ADMIN)['id'] for name in ['A','B']]
    ops.funds(evidence('deposit-a',amount=10000),ADMIN,ids[0])
    with e['factory']() as s:
        from packages.application.finance import balance
        assert balance(s,f'DEPOSIT:{ids[0]}')==10000 and balance(s,f'DEPOSIT:{ids[1]}')==0
        assert balance(s,'BANK')==990000
    with pytest.raises(DomainError,match='INSUFFICIENT'):ops.funds(evidence('overdraw',amount=1000000),ADMIN,ids[1])


@pytest.mark.parametrize('value',[0,-1,True,1.5,10**12+1])
def test_invalid_opening_money(blank,value):
    r=blank['clients']['admin'].post('/v1/funds/opening-bank',json=evidence('bad',amount=value));assert r.status_code==422


@pytest.mark.parametrize('role',['viewer','operator'])
def test_setup_and_money_rbac_csrf_origin_and_no_password(blank,role):
    e=blank;c=e['clients']['admin']; password='Synthetic-operator-password'
    r=c.post('/v1/users',json={'username':'test-user','role':role,'password':password});assert r.status_code==200 and password not in r.text
    assert c.post('/v1/users',json={'username':'test-user','role':'admin','password':password}).status_code==409
    e['login']('second','test-user',password);client=e['clients']['second']
    assert client.post('/v1/funds/opening-bank',json=evidence('rbac',amount=100)).status_code==403
    assert client.post('/v1/users',json={'username':'another-user','role':'admin','password':password}).status_code==403
    assert client.post('/v1/suppliers',json={'name':'test','cutoff':'14:00','claim_days':3,'active':True}).status_code==403
    assert c.post('/v1/funds/opening-bank',json=evidence('csrf',amount=1),headers={'X-CSRF-Token':'bad'}).status_code==403
    assert c.post('/v1/funds/opening-bank',json=evidence('origin',amount=1),headers={'Origin':'https://wrong.invalid'}).status_code==403
    if role=='viewer': assert client.post('/v1/listings',json={'supplier_product_id':'x','marketplace':'coupang','fee_rate':'0.1'}).status_code==403


def test_same_proposer_cannot_approve_and_demo_supplier_rejected(blank):
    c=blank['clients']['admin'];payload={'name':'supplier','cutoff':'14:00','claim_days':3,'active':True}
    assert c.post('/v1/suppliers',json=payload|{'mode':'demo'}).status_code==422
    sid=c.post('/v1/suppliers',json=payload).json()['id']
    assert c.post('/v1/suppliers',json=payload|{'claim_days':4}).status_code==409
    c.post(f'/v1/suppliers/{sid}/destination/propose',json={'destination_fingerprint':'a'*64})
    assert c.post(f'/v1/suppliers/{sid}/destination/approve',json={'destination_fingerprint':'a'*64,'verified_reference':'checked-reference'}).status_code==403


def test_provider_partial_refund_regression_and_unknown_unchanged(env,order_input):
    oid=delivered(env,order_input);a=AfterSales(env['commerce'])
    cid=a.open_claim(oid,'partial','ROTTEN',5000,list(EVIDENCE));env['worker'].drain();a.supplier_response(cid,2000,True)
    r=a.request_refund(cid,2000,'first',actor='admin');env['worker'].drain()
    with env['factory']() as s:assert s.get(Claim,cid).status=='PARTIALLY_REFUNDED'
    a.request_refund(cid,3000,'rest',actor='admin');env['worker'].drain()
    with env['factory']() as s:assert s.get(Claim,cid).status=='REFUNDED' and s.get(Claim,cid).customer_refund==5000
    with pytest.raises(DomainError):a.request_refund(cid,1,'extra',actor='admin')


def test_open_partial_claim_prevents_closed(env,order_input):
    oid=delivered(env,order_input);a=AfterSales(env['commerce'])
    cid=a.open_claim(oid,'partial-open','ROTTEN',5000,list(EVIDENCE));env['worker'].drain();a.supplier_response(cid,2000,True)
    a.request_refund(cid,2000,'part',actor='admin');env['worker'].drain()
    sid=a.reconcile_settlement(oid,'partial-statement',order_input['gross_sale']-2000-(order_input['gross_sale']//10))
    a.confirm_settlement_cash(sid,'partial-bank')
    with env['factory']() as s:assert s.get(Order,oid).state=='SETTLED'
