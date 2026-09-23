from datetime import timedelta
from decimal import Decimal
import pytest
from sqlalchemy import select
from packages.application.risk import guard_cash_and_claims
from packages.application.after_sales import AfterSales, EVIDENCE
from packages.application.files import Files
from packages.infrastructure.models import (Supplier, SupplierProduct, MarketplaceListing, Order, SupplierOrder, Payment, Account, Claim, Job, Review, ImportBatch)
from packages.infrastructure.schema_v1 import now
from packages.integrations.suppliers.excel import workbook_bytes, ExcelProfile
from packages.domain.errors import DomainError
from test_workflows import complete_order, delivered

def test_low_cash_proactively_pauses_active_listings(env):
    with env['factory'].begin() as s:
        s.scalar(select(Account).where(Account.code=='BANK')).balance=0
        assert guard_cash_and_claims(s,env['commerce'])==5
        assert all(l.desired_state=='PAUSED' for l in s.scalars(select(MarketplaceListing)))

def test_claim_kill_switch_uses_minimum_sample_window(env,order_input):
    oid=delivered(env,order_input);a=AfterSales(env['commerce'])
    a.open_claim(oid,'bad-batch','ROTTEN',5000,list(EVIDENCE));env['worker'].drain()
    with env['factory'].begin() as s:assert guard_cash_and_claims(s,env['commerce'])==0
    env['settings'].claim_min_samples=1
    with env['factory'].begin() as s:
        assert guard_cash_and_claims(s,env['commerce'])==1
        assert s.scalar(select(Review).where(Review.category=='CLAIM_LOSS_KILL_SWITCH'))

def test_notifications_are_queued_without_pii(env,order_input):
    order_input['address']['postal_code']='bad'
    env['commerce'].ingest(order_input);env['worker'].drain()
    with env['factory']() as s:
        row=s.scalar(select(Job).where(Job.kind=='notification.send'))
        assert row.status=='DONE'
        assert 'address' not in str(row.payload) and '010-' not in str(row.payload)

def test_cancellation_detected_at_provider_recheck(env,order_input):
    oid=env['commerce'].ingest(order_input)['id']
    env['commerce'].registry.mocks['coupang'].set_order_status(order_input['external_id'],'CANCELLED')
    env['worker'].drain()
    with env['factory']() as s:
        assert s.get(Order,oid).state=='CANCELLED' and s.scalar(select(Payment)) is None

def test_supplier_cutoff_enforced(env,order_input):
    with env['factory'].begin() as s:s.get(Supplier,env['ids']['supplier_id']).cutoff='00:00'
    oid=env['commerce'].ingest(order_input)['id'];env['worker'].drain()
    with env['factory']() as s:
        assert s.get(Order,oid).state=='MANUAL_REVIEW'
        assert s.scalar(select(Review).where(Review.category=='SUPPLIER_CUTOFF'))

def test_excel_export_is_not_supplier_acceptance(env,order_input):
    with env['factory'].begin() as s:s.get(Supplier,env['ids']['supplier_id']).mode='excel'
    oid=env['commerce'].ingest(order_input)['id'];env['worker'].drain()
    data=Files(env['commerce']).export(env['ids']['profile_id'],'admin');assert data[:2]==b'PK'
    with env['factory']() as s:
        assert s.scalar(select(SupplierOrder)).status=='FILE_READY'
        assert s.get(Order,oid).state=='SUPPLIER_ORDER_PENDING'
        assert not s.scalar(select(Payment))

def test_changed_destination_prevents_pending_payment(env,order_input):
    oid=env['commerce'].ingest(order_input)['id'];env['commerce'].process_order(oid)
    with env['factory']() as s:so=s.scalar(select(SupplierOrder))
    env['commerce'].submit_supplier(so.id)
    with env['factory'].begin() as s:
        supplier=s.get(Supplier,env['ids']['supplier_id']);supplier.destination_approved=False
    env['worker'].drain()
    with env['factory']() as s:
        p=s.scalar(select(Payment));assert p.status=='MANUAL_APPROVAL'
        assert s.get(Order,oid).state=='MANUAL_REVIEW'

def test_partial_rows_imported_but_bad_rows_queued(env):
    data=workbook_bytes(['SKU','상품명','원가','배송비','재고'],[['NEW','합성 신제품',5000,3000,5],['BAD','잘못된 제품',-1,3000,5]])
    files=Files(env['commerce']);bid=files.submit(env['ids']['profile_id'],'price',data);env['worker'].drain()
    with env['factory']() as s:
        batch=s.get(ImportBatch,bid);assert batch.accepted==1 and batch.rejected==1
        assert batch.status=='COMPLETED_WITH_ERRORS'

def test_duplicate_shipment_rows_are_all_quarantined(env,order_input):
    oid=complete_order(env,order_input)
    with env['factory']() as s:so=s.scalar(select(SupplierOrder))
    row=[so.id,order_input['external_id'],'DEMO','00009999']
    data=workbook_bytes(['발주ID','마켓주문ID','택배사','송장번호'],[row,row])
    bid=Files(env['commerce']).submit(env['ids']['profile_id'],'shipment',data);env['worker'].drain()
    with env['factory']() as s:
        batch=s.get(ImportBatch,bid);assert batch.accepted==0 and batch.rejected==2
        assert s.get(Order,oid).state=='SHIPMENT_PENDING'

def test_ambiguous_large_refund_needs_explicit_approval(env,order_input):
    oid=delivered(env,order_input);a=AfterSales(env['commerce'])
    cid=a.open_claim(oid,'cl','ROTTEN',20000,list(EVIDENCE));env['worker'].drain();a.supplier_response(cid,1000,True)
    rid=a.request_refund(cid,20000,'big-refund');env['worker'].drain()
    from packages.infrastructure.models import Refund
    with env['factory']() as s:assert s.get(Refund,rid).status=='MANUAL_APPROVAL'
