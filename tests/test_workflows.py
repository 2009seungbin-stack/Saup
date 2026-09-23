from decimal import Decimal
from datetime import timedelta
import pytest
from sqlalchemy import select, func
from packages.domain.errors import DomainError
from packages.infrastructure.models import (Order, SupplierOrder, Payment, SupplierProduct, MarketplaceListing,
    SupplierPriceHistory, Review, Reservation, Shipment, Claim, Refund, Settlement, Account, ExternalRecord, Job, Posting, Journal)
from packages.application.catalog import apply_price, pause_listing
from packages.application.finance import treasury, post, capacity, daily_commitments
from packages.application.seed import demo_profile, price_fixture
from packages.application.files import Files
from packages.application.after_sales import AfterSales, EVIDENCE


def complete_order(env, data):
    oid=env['commerce'].ingest(data)['id']; env['worker'].drain()
    with env['factory']() as s:
        order=s.get(Order,oid)
        assert order.state=='SHIPMENT_PENDING', (order.state, [(x.category,x.details) for x in s.scalars(select(Review))])
    return oid

def delivered(env,data):
    oid=complete_order(env,data)
    with env['factory'].begin() as s:
        so=s.scalar(select(SupplierOrder).where(SupplierOrder.order_id==oid))
        env['commerce'].add_shipment(s,{'supplier_order_id':so.id,'marketplace_order_id':data['external_id'],
            'courier':'DEMO','tracking':'000012345678'})
    env['worker'].drain(); env['commerce'].delivered(oid)
    return oid

def test_duplicate_order_supplier_and_payment(env,order_input):
    c=env['commerce']; first=c.ingest(order_input); second=c.ingest(order_input)
    assert first['id']==second['id'] and second['duplicate']
    env['worker'].drain(); c.process_order(first['id'])
    with env['factory']() as s:
        so=s.scalar(select(SupplierOrder)); p=s.scalar(select(Payment)); assert so and p
        assert s.scalar(select(func.count()).select_from(Order))==1
    c.submit_supplier(so.id); c.execute_payment(p.id)
    with env['factory']() as s:
        assert s.scalar(select(func.count()).select_from(Payment))==1
        assert s.scalar(select(func.count()).select_from(ExternalRecord).where(ExternalRecord.namespace=='payment:pay_supplier'))==1
        assert s.get(Payment,p.id).status=='SUCCEEDED'

def test_conflicting_order_identity_rejected(env,order_input):
    env['commerce'].ingest(order_input)
    order_input['quantity']=2
    with pytest.raises(DomainError,match='CONFLICT'): env['commerce'].ingest(order_input)

@pytest.mark.parametrize('change,reason',[('price','MARGIN_BELOW_THRESHOLD'),('stock','OUT_OF_STOCK'),('cash','INSUFFICIENT_CASH'),('address','ADDRESS_ERROR')])
def test_invalid_orders_enter_review(env,order_input,change,reason):
    if change=='address': order_input['address']['postal_code']='broken'
    with env['factory'].begin() as s:
        listing=s.get(MarketplaceListing,order_input['listing_id']); sp=s.get(SupplierProduct,listing.supplier_product_id)
        if change=='price': sp.cost=order_input['gross_sale']
        if change=='stock': sp.stock=0; sp.stock_status='OUT_OF_STOCK'
        if change=='cash': s.scalar(select(Account).where(Account.code=='BANK')).balance=1
    oid=env['commerce'].ingest(order_input)['id'];env['worker'].drain()
    with env['factory']() as s:
        assert s.get(Order,oid).state=='MANUAL_REVIEW'
        assert s.scalar(select(Review).where(Review.category==reason))
        assert not s.scalar(select(Payment))

def test_price_spike_retains_history_and_pauses(env):
    with env['factory'].begin() as s:
        sp=s.scalar(select(SupplierProduct).where(SupplierProduct.supplier_sku=='001'))
        data={**demo_profile().defaults,'supplier_sku':'001','title':'황금향 3kg','cost':20000,'shipping':3000,'stock':100}
        apply_price(s,env['settings'],sp.supplier_id,data,'changed-file-hash')
        listing=s.scalar(select(MarketplaceListing).where(MarketplaceListing.supplier_product_id==sp.id))
        assert listing.desired_state=='PAUSED' and listing.remote_state=='UNCONFIRMED'
        assert s.scalar(select(func.count()).select_from(SupplierPriceHistory).where(SupplierPriceHistory.supplier_product_id==sp.id))==2
    env['worker'].drain()
    with env['factory']() as s: assert s.get(MarketplaceListing,listing.id).remote_state=='PAUSED'

def test_cancel_before_supplier(env,order_input):
    oid=env['commerce'].ingest(order_input)['id'];env['commerce'].cancel(oid);env['worker'].drain()
    with env['factory']() as s:
        assert s.get(Order,oid).state=='CANCELLED' and not s.scalar(select(SupplierOrder))

def test_cancel_after_supplier_before_payment(env,order_input):
    oid=env['commerce'].ingest(order_input)['id'];env['commerce'].process_order(oid)
    with env['factory']() as s: so=s.scalar(select(SupplierOrder))
    env['commerce'].submit_supplier(so.id);env['commerce'].cancel(oid);env['worker'].drain()
    with env['factory']() as s:
        assert s.get(Order,oid).state=='CANCELLED'
        assert s.scalar(select(Reservation)).status=='RELEASED'
        assert s.scalar(select(Payment)).status=='CANCELLED'

def test_cancel_after_payment_not_silently_refunded(env,order_input):
    oid=complete_order(env,order_input);env['commerce'].cancel(oid)
    with env['factory']() as s:
        assert s.get(Order,oid).state=='CANCEL_REQUESTED'
        assert s.scalar(select(Review).where(Review.category=='CANCELLATION_AFTER_PAYMENT'))
        assert not s.scalar(select(Refund))

def test_invalid_excel_is_durable_error(env):
    files=Files(env['commerce']);bid=files.submit(env['ids']['profile_id'],'price',b'bad')
    assert files.submit(env['ids']['profile_id'],'price',b'bad')==bid
    env['worker'].drain()
    from packages.infrastructure.models import ImportBatch
    with env['factory']() as s:
        assert s.get(ImportBatch,bid).status=='FAILED'
        assert s.scalar(select(Review).where(Review.entity_id==bid))

def test_price_import_idempotent(env):
    files=Files(env['commerce']);data=price_fixture()
    bid=files.submit(env['ids']['profile_id'],'price',data);env['worker'].drain()
    from packages.infrastructure.models import ImportBatch
    with env['factory']() as s:
        batch=s.get(ImportBatch,bid);assert batch.accepted==5 and batch.rejected==0
        assert s.scalar(select(func.count()).select_from(SupplierPriceHistory))==5
    assert files.submit(env['ids']['profile_id'],'price',data)==bid

def test_duplicate_shipment_no_second_update(env,order_input):
    oid=complete_order(env,order_input)
    with env['factory'].begin() as s:
        so=s.scalar(select(SupplierOrder)); data={'supplier_order_id':so.id,'marketplace_order_id':order_input['external_id'],'courier':'DEMO','tracking':'00001111'}
        a=env['commerce'].add_shipment(s,data); b=env['commerce'].add_shipment(s,data); assert a.id==b.id
    env['worker'].drain()
    with env['factory']() as s: assert s.scalar(select(func.count()).select_from(Shipment))==1

def test_quality_claim_evidence_required(env,order_input):
    oid=delivered(env,order_input);a=AfterSales(env['commerce']);cid=a.open_claim(oid,'claim1','ROTTEN',5000,[])
    with env['factory']() as s: assert s.get(Claim,cid).status=='EVIDENCE_REQUIRED'

def test_supplier_rejection_requires_review(env,order_input):
    oid=delivered(env,order_input);a=AfterSales(env['commerce']);cid=a.open_claim(oid,'claim1','ROTTEN',5000,list(EVIDENCE))
    env['worker'].drain();a.supplier_response(cid,0,False)
    with env['factory']() as s:
        assert s.get(Claim,cid).status=='MANUAL_REVIEW'
        assert s.scalar(select(Review).where(Review.category=='SUPPLIER_REJECTED_CLAIM'))

def test_partial_supplier_recovery_full_customer_refund(env,order_input):
    oid=delivered(env,order_input);a=AfterSales(env['commerce']);amount=order_input['gross_sale']
    cid=a.open_claim(oid,'claim1','ROTTEN',amount,list(EVIDENCE));env['worker'].drain();a.supplier_response(cid,4000,True)
    with env['factory']() as s: assert treasury(s,env['settings'],env['ids']['supplier_id'])['supplier_deposit']==0
    a.confirm_supplier_recovery(cid,4000,'demo-recovery-1')
    rid=a.request_refund(cid,amount,'full-refund-1',actor='admin');env['worker'].drain()
    assert a.request_refund(cid,amount,'full-refund-1',actor='admin')==rid
    with env['factory']() as s:
        assert s.get(Refund,rid).status=='SUCCEEDED'
        assert s.get(Claim,cid).customer_refund==amount
        assert treasury(s,env['settings'],env['ids']['supplier_id'])['supplier_deposit']==4000
    with pytest.raises(DomainError): a.request_refund(cid,1,'extra-refund',actor='admin')

def test_settlement_statement_is_not_cash_and_mismatch_flagged(env,order_input):
    oid=delivered(env,order_input);a=AfterSales(env['commerce'])
    with env['factory']() as s:
        o=s.get(Order,oid);expected=o.gross_sale-o.fee;bank=treasury(s,env['settings'])['bank_balance']
    sid=a.reconcile_settlement(oid,'statement-1',expected-1000)
    with env['factory']() as s:
        assert treasury(s,env['settings'])['bank_balance']==bank
        assert s.scalar(select(Review).where(Review.category=='SETTLEMENT_ANOMALY'))
    a.confirm_settlement_cash(sid,'receipt-1')
    with env['factory']() as s: assert treasury(s,env['settings'])['bank_balance']==bank+expected-1000

def test_large_payment_manual_approval(env,order_input):
    env['settings'].auto_payment_limit=1
    oid=env['commerce'].ingest(order_input)['id'];env['worker'].drain()
    with env['factory']() as s: p=s.scalar(select(Payment));assert p.status=='MANUAL_APPROVAL'
    env['commerce'].approve_payment(p.id,p.amount,p.destination_fingerprint,'admin');env['worker'].drain()
    with env['factory']() as s: assert s.get(Payment,p.id).status=='SUCCEEDED'

def test_payment_timeout_after_remote_commit_reconciles_without_duplicate(env,order_input):
    env['commerce'].registry.mock_payment.fail_next['pay_supplier']='timeout_after'
    oid=env['commerce'].ingest(order_input)['id'];env['worker'].drain()
    with env['factory']() as s: p=s.scalar(select(Payment));assert p.status=='UNKNOWN'
    env['commerce'].execute_payment(p.id);env['commerce'].reconcile_payment(p.id)
    with env['factory']() as s:
        assert s.get(Payment,p.id).status=='SUCCEEDED'
        assert s.scalar(select(func.count()).select_from(ExternalRecord).where(ExternalRecord.namespace=='payment:pay_supplier'))==1

def test_price_sync_timeout_fails_closed_but_remote_unconfirmed(env):
    c=env['commerce'];c.registry.mocks['coupang'].fail_next['sync_listing']='timeout_before'
    lid=env['ids']['listing_ids'][0]
    with env['factory'].begin() as s:
        listing=s.get(MarketplaceListing,lid);listing.sync_revision=1
        from packages.application.common import enqueue
        enqueue(s,'listing.sync',f'listing:{lid}:1',{'listing_id':lid,'revision':1,'desired_state':'ACTIVE','price':listing.price})
    assert env['worker'].tick()
    with env['factory']() as s:
        l=s.get(MarketplaceListing,lid);assert l.desired_state=='PAUSED' and l.remote_state=='UNCONFIRMED'
        assert s.scalar(select(Review).where(Review.category=='PRICE_SYNC_FAILED'))

def test_unsettled_cash_excluded_and_deposit_is_supplier_specific(env):
    with env['factory'].begin() as s:
        post(s,'test-credit','TEST',{'MARKETPLACE_RECEIVABLE':999999,'REVENUE':-999999})
        post(s,'test-deposit','TEST',{'DEPOSIT:other':999999,'EQUITY':-999999})
        position=treasury(s,env['settings'],env['ids']['supplier_id'])
        assert position['available_cash']==850000
        assert capacity(s,env['settings'],env['ids']['supplier_id'],10000)==85

def test_all_journals_balanced_after_sale_and_refund(env,order_input):
    oid=delivered(env,order_input);a=AfterSales(env['commerce'])
    cid=a.open_claim(oid,'cl1','ROTTEN',5000,list(EVIDENCE));env['worker'].drain();a.supplier_response(cid,2000,True)
    a.confirm_supplier_recovery(cid,2000,'rcv');a.request_refund(cid,5000,'refund');env['worker'].drain()
    with env['factory']() as s:
        order=s.get(Order,oid);expected=order.gross_sale-order.fee-5000
    sid=a.reconcile_settlement(oid,'st',expected);a.confirm_settlement_cash(sid,'bank')
    with env['factory']() as s:
        assert s.get(Order,oid).state=='CLOSED'
        assert all(total==0 and count>=2 for total,count in s.execute(select(func.sum(Posting.delta),func.count()).group_by(Posting.journal_id)))
        assert s.scalar(select(Account.balance).where(Account.code=='MARKETPLACE_RECEIVABLE'))==0
        assert s.scalar(select(Account.balance).where(Account.code=='SETTLEMENT_CLEARING'))==0
