"""Shared blank-install API scenario. Transport is real HTTP or TestClient.

No database writes, seed endpoints or demo business data. All evidence here is
explicitly synthetic test evidence, never evidence of a live external action.
"""
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from openpyxl import load_workbook
from packages.integrations.suppliers.excel import workbook_bytes
from packages.integrations.marketplaces.order_file import COLUMNS


def evidence(name, **values):
    return {'reference': name, 'evidence_hash': sha256(name.encode()).hexdigest(), 'confirmed': True, **values}


def run(call, second_login, poll):
    """call(method,path,body=None,file=None,actor='admin',binary=False)."""
    def get(path, **kw): return call('GET', path, **kw)
    def post(path, body=None, **kw): return call('POST', path, body, **kw)
    def replay(path, body):
        def canonical(value):
            if isinstance(value,dict): return {k:canonical(v) for k,v in value.items() if not k.endswith('_at')}
            if isinstance(value,list): return [canonical(x) for x in value]
            return value
        a = post(path, body); b = post(path, body); assert canonical(a) == canonical(b), path
        return a
    assert get('/v1/setup')['suppliers'] == [], 'Blank business dataset required'
    post('/v1/users', {'username': 'second-admin', 'role': 'admin', 'password': 'Synthetic-second-admin-123!'})
    second_login()
    sid = replay('/v1/suppliers', {'name': 'Acceptance Excel Supplier', 'mode': 'excel', 'cutoff': '23:59', 'claim_days': 7, 'active': True})['id']
    mapping = {'columns': {key:key for key in ['supplier_sku','title','cost','shipping','stock','category','origin','tax_type','weight_grams','grade','unit']}}
    pid = replay('/v1/profiles', {'supplier_id': sid, 'name': 'Acceptance operator profile', 'mapping': mapping})['id']
    price = workbook_bytes(list(mapping['columns']), [['0001','Acceptance product',10000,2000,100,'produce','test-origin','EXEMPT',3000,'test-grade','box']])
    first = post(f'/v1/imports/{pid}/price', file=price)
    assert first == post(f'/v1/imports/{pid}/price', file=price)
    for _ in range(100):
        poll(); setup = get('/v1/setup')
        if setup['products']: break
    assert len(setup['products']) == 1
    lid = replay('/v1/listings', {'supplier_product_id': setup['products'][0]['id'], 'marketplace':'coupang', 'fee_rate':'0.10'})['id']
    assert get('/v1/setup')['listings'][0]['remote_state'] == 'UNKNOWN'
    destination = sha256(b'synthetic-approved-destination').hexdigest()
    post(f'/v1/suppliers/{sid}/destination/propose', {'destination_fingerprint':destination})
    post(f'/v1/suppliers/{sid}/destination/approve', {'destination_fingerprint':destination, 'verified_reference':'synthetic-destination-check'}, actor='second')
    replay('/v1/funds/opening-bank', evidence('synthetic-opening-bank', amount=1000000))
    replay(f'/v1/suppliers/{sid}/deposit', evidence('synthetic-deposit', amount=5000))
    replay(f'/v1/listings/{lid}/external-activation', evidence('synthetic-listing-verified', price=20000, external_id='synthetic-listing-1'))

    # Download, populate and upload the canonical template; IDs and PII stay text.
    template = get('/v1/order-imports/template', binary=True)
    wb = load_workbook(BytesIO(template)); ws = wb.active
    for name in ['normal','claim','cancel']:
        row = {'external_id':f'closure-{name}','external_line_id':'1','listing_id':lid,'quantity':1,'gross_sale':20000,'discount':0,
            'recipient':'Synthetic Customer','phone':'010-0000-0000','postal_code':'01234','address1':'Synthetic address 123','address2':'Test room'}
        ws.append([row[key] for key in COLUMNS])
    out = BytesIO(); wb.save(out); wb.close(); order_file = out.getvalue()
    preview = post('/v1/order-imports/preview', {'marketplace':'coupang'}, file=order_file)
    command = {'marketplace':'coupang','preview_token':preview['preview_token'],'source_reference':'synthetic-order-file','confirmed_authorized_source':True}
    imported = post('/v1/order-imports/commit', {'command':json.dumps(command)}, file=order_file)
    again = post('/v1/order-imports/commit', {'command':json.dumps(command)}, file=order_file)
    assert imported['id'] == again['id']
    orders = get('/v1/orders'); ids = {o['external_id'].removeprefix('closure-'):o['id'] for o in orders}
    for name, oid in ids.items():
        d = get(f'/v1/order-intake/{oid}')
        replay(f'/v1/order-intake/{oid}/verify-and-validate', {'idempotency_key':f'verify-{name}','snapshot_hash':d['snapshot_hash'],
            'source_reference':f'synthetic-current-{name}','evidence_hash':sha256(name.encode()).hexdigest(),
            'observed_at':datetime.now(timezone.utc).isoformat(),'confirmed_current_order_open':True})
    candidates = get('/v1/supplier-orders/eligible')
    soids = [x['id'] for x in candidates]
    batch = replay('/v1/supplier-order-batches', {'supplier_id':sid,'profile_id':pid,'supplier_order_ids':soids,'idempotency_key':'closure-batch'})
    assert get(f"/v1/supplier-order-batches/{batch['id']}/file", binary=True)
    replay(f"/v1/supplier-order-batches/{batch['id']}/mark-sent", {'send_channel':'MANUAL','send_reference':'synthetic-send','file_hash':batch['file_hash']})
    replay(f"/v1/supplier-order-batches/{batch['id']}/acknowledge", {'accepted_order_ids':soids,'rejected':[],'reported_changes':[],'reference':'synthetic-ack'})
    batch = get(f"/v1/supplier-order-batches/{batch['id']}")
    payments = {}
    for item in batch['items']:
        p = get(f"/v1/supplier-payments/{item['payment_id']}"); payments[item['order_id']] = p
        values = {k:p[k] for k in ['supplier_id','amount','bank_amount','deposit_amount','destination_fingerprint']}
        ref = 'synthetic-pay-'+p['id']
        proof = replay(f"/v1/supplier-payments/{p['id']}/evidence", values | {'method':'OTHER_APPROVED_METHOD','reference':ref,'evidence_hash':sha256(ref.encode()).hexdigest()})
        replay(f"/v1/supplier-payment-evidence/{proof['id']}/confirm", {'amount':p['amount'],'destination_fingerprint':destination,'reference':ref,'confirmed_money_moved':True})
    # Tracking is still supplied through the existing XLSX importer.
    rows = [[x['supplier_order_id'],next(o['external_id'] for o in orders if o['id']==x['order_id']),'CJ',f'00100000000{i}']
            for i,x in enumerate(batch['items']) if x['order_id'] != ids['cancel']]
    tracking = workbook_bytes(['발주ID','마켓주문ID','택배사','송장번호'], rows)
    upload = post(f'/v1/imports/{pid}/shipment', file=tracking)
    assert upload == post(f'/v1/imports/{pid}/shipment', file=tracking)
    for _ in range(100):
        poll(); work = get('/v1/operations')
        if len(work['shipments']) == 2: break
    assert len(work['shipments']) == 2
    for sh in work['shipments']:
        assert not sh['manual_confirmation'] and not sh['marketplace_synced']
        replay(f"/v1/shipments/{sh['id']}/external-confirmation", evidence('synthetic-shipment-'+sh['id'],
            **{k:sh[k] for k in ['marketplace','external_order_id','external_line_id','tracking_hash']}))
        replay(f"/v1/orders/{sh['order_id']}/delivery-confirmation", evidence('synthetic-delivery-'+sh['id']))
    cid = replay(f"/v1/orders/{ids['claim']}/claims", {'external_id':'synthetic-claim','category':'ROTTEN','amount':5000,
        'evidence':['parcel_label','entire_contents','damage_closeup']})['claim_id']
    replay(f'/v1/claims/{cid}/supplier-response', evidence('synthetic-claim-response',accepted=True,amount=3000))
    for index, amount in enumerate([2000,3000]):
        rid = replay(f'/v1/claims/{cid}/refunds', {'amount':amount,'key':f'closure-refund-{index}'})['refund_id']
        replay(f'/v1/refunds/{rid}/external-confirmation', evidence(f'synthetic-refund-{index}',order_id=ids['claim'],claim_id=cid,
            amount=amount,marketplace='coupang',confirmed_customer_refunded=True))
        assert get(f'/v1/claims/{cid}')['claim']['status'] == ('PARTIALLY_REFUNDED' if index==0 else 'REFUNDED')
    replay(f'/v1/claims/{cid}/supplier-recovery', evidence('synthetic-claim-recovery',amount=3000))
    for name in ['normal','claim']:
        actual = 18000 if name=='normal' else 13000
        st = replay(f"/v1/orders/{ids[name]}/settlement", evidence(f'synthetic-statement-{name}',external_id=f'statement-{name}',actual=actual-100,adjustment=0))['settlement_id']
        replay(f'/v1/settlements/{st}/corrections', evidence(f'synthetic-statement-correct-{name}',external_id=f'corrected-{name}',actual=actual,
            adjustment=0,expected_revision=0,reason='WRONG_AMOUNT'))
        replay(f'/v1/settlements/{st}/cash-confirmation', evidence(f'synthetic-bank-receipt-{name}',amount=actual,expected_revision=1))
    # Paid cancellation uses existing 11A then versioned 11B correction.
    p = payments[ids['cancel']]; so = next(x['supplier_order_id'] for x in batch['items'] if x['order_id']==ids['cancel'])
    post(f'/v1/supplier-orders/{so}/cancel')
    replay(f'/v1/supplier-orders/{so}/cancellation/confirm', {'reference':'synthetic-cancel','supplier_confirmed_cancelled':True})
    reviews = get('/v1/reviews'); review = next(x for x in reviews if x['entity_id']==so and x['category']=='SUPPLIER_CANCELLATION_FINANCIAL_REVIEW')
    recovery = {k:p[k] for k in ['supplier_id','amount','bank_amount','deposit_amount','destination_fingerprint']}
    customer = replay(f"/v1/review-resolutions/{review['id']}/confirm-supplier-recovery", recovery | {
        'payment_id':p['id'],'idempotency_key':'closure-cancel-recovery','reference':'synthetic-cancel-recovery',
        'evidence_hash':sha256(b'cancel-recovery').hexdigest(),'confirmed_funds_received':True})['customer_review_id']
    d = get(f'/v1/review-resolutions/{customer}'); snap=d['snapshot']
    refund = replay(f'/v1/review-resolutions/{customer}/record-marketplace-refund', {k:snap[k] for k in ['snapshot_hash','supplier_recovery_id','marketplace','external_order_id','external_line_id','customer_refund_amount']} | {
        'idempotency_key':'closure-cancel-refund','reference':'synthetic-cancel-refund','evidence_hash':sha256(b'cancel-refund').hexdigest(),'confirmed_customer_refunded':True})
    statement = {'idempotency_key':'closure-cancel-statement','snapshot_hash':snap['snapshot_hash'],'refund_evidence_id':refund['refund_evidence_id'],
        'customer_refund_amount':20000,'seller_payout_amount':0,'seller_debit_amount':0,'retained_fee_amount':100,'outstanding_balance':0,
        'reference':'synthetic-cancel-statement','evidence_hash':sha256(b'cancel-statement').hexdigest(),'confirmed_final_statement':True,'confirmed_marketplace_cancelled':True}
    st = replay(f'/v1/review-resolutions/{customer}/record-marketplace-statement',statement)
    assert not st['completion_allowed']
    replay(f'/v1/reviews/{customer}/marketplace-statement-corrections',statement | {'idempotency_key':'closure-cancel-correct',
        'statement_id':st['statement_id'],'expected_revision':0,'reason':'WRONG_AMOUNT','retained_fee_amount':0,
        'reference':'synthetic-cancel-correct','evidence_hash':sha256(b'cancel-correct').hexdigest()})
    replay(f'/v1/review-resolutions/{customer}/complete-marketplace-cancellation', {'idempotency_key':'closure-cancel-complete','snapshot_hash':snap['snapshot_hash'],
        'refund_evidence_id':refund['refund_evidence_id'],'statement_id':st['statement_id'],'expected_statement_revision':1,'confirmed_reconciliation':True})
    final = get('/v1/operations')
    assert {o['external_id']:o['state'] for o in final['orders']} == {'closure-normal':'CLOSED','closure-claim':'CLOSED','closure-cancel':'CANCELLED'}
    return {'orders':ids,'supplier_id':sid,'profile_id':pid,'claim_id':cid,'synthetic_only':True,'real_money_moved':False}
