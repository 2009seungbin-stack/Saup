"""Repeatable, synthetic vertical-slice acceptance demonstration; no external money."""
import argparse
import json
from pathlib import Path
from uuid import uuid4
from sqlalchemy import select, func
from packages.infrastructure.settings import Settings
from packages.infrastructure.db import database
from packages.infrastructure.models import Order, SupplierOrder, Payment, Shipment, Claim, Refund, Settlement, Posting, ExternalRecord, ImportBatch, MarketplaceListing
from packages.application.seed import seed, price_fixture
from packages.application.commerce import Commerce
from packages.application.files import Files
from packages.application.after_sales import AfterSales, EVIDENCE
from packages.application.finance import treasury
from packages.integrations.suppliers.excel import workbook_bytes
from apps.worker.main import Worker

def run_demo(settings,factory,output):
    if settings.app_mode not in {'demo','test'}:raise RuntimeError('DEMO_DISABLED')
    ids=seed(settings,factory,demo=True);c=Commerce(settings,factory);w=Worker(c);files=Files(c);after=AfterSales(c)
    output=Path(output);output.mkdir(parents=True,exist_ok=True);tag=uuid4().hex[:10]
    (output/'prices.xlsx').write_bytes(price_fixture())
    batch=files.submit(ids['profile_id'],'price',price_fixture());w.drain()
    with factory() as s:
        listing=s.get(MarketplaceListing,ids['listing_ids'][0]);price=listing.price
        if listing.desired_state!='ACTIVE':raise RuntimeError('DEMO_REQUIRES_ACTIVE_SYNTHETIC_LISTING; use an isolated demo database')
    payload={'marketplace':'coupang','external_id':'DEMO-'+tag,'external_line_id':'1','listing_id':ids['listing_ids'][0],
        'quantity':1,'gross_sale':price,'address':{'recipient':'합성 데모 고객','phone':'010-0000-0000','postal_code':'01234',
        'address1':'가상시 테스트로 123','address2':'실재하지 않는 데모 주소'}}
    order=c.ingest(payload);duplicate=c.ingest(payload);assert duplicate['id']==order['id'];oid=order['id'];w.drain()
    with factory() as s:
        o=s.get(Order,oid);assert o.state=='SHIPMENT_PENDING',o.state
        so=s.scalar(select(SupplierOrder).where(SupplierOrder.order_id==oid));soid=so.id
        p=s.scalar(select(Payment).where(Payment.order_id==oid));pid=p.id
    (output/'supplier-orders.xlsx').write_bytes(files.export(ids['profile_id'],'demo-script'))
    c.execute_payment(pid);c.submit_supplier(soid)  # Deliberate retries prove stable business identities.
    tracking=workbook_bytes(['발주ID','마켓주문ID','택배사','송장번호'],[[soid,payload['external_id'],'DEMO',f'0000{tag}']])
    (output/'shipments.xlsx').write_bytes(tracking)
    files.submit(ids['profile_id'],'shipment',tracking);w.drain();c.delivered(oid)
    cid=after.open_claim(oid,'CLAIM-'+tag,'BRUISED',5000,list(EVIDENCE));w.drain()
    after.supplier_response(cid,2000,True);after.confirm_supplier_recovery(cid,2000,'RECOVERY-'+tag)
    rid=after.request_refund(cid,5000,'REFUND-'+tag);w.drain()
    with factory() as s:
        o=s.get(Order,oid);expected=o.gross_sale-o.discount-o.fee-o.promotion_cost-5000
        cash_before=treasury(s,settings)['bank_balance']
    sid=after.reconcile_settlement(oid,'STATEMENT-'+tag,expected)
    with factory() as s:assert treasury(s,settings)['bank_balance']==cash_before
    after.confirm_settlement_cash(sid,'BANK-'+tag)
    bad_batch=files.submit(ids['profile_id'],'price',b'malformed synthetic file '+tag.encode());w.drain()
    spike=files.submit(ids['profile_id'],'price',price_fixture(spike=True));w.drain()
    with factory() as s:
        o=s.get(Order,oid);assert o.state=='CLOSED'
        assert s.get(Payment,pid).status=='SUCCEEDED' and s.get(Refund,rid).status=='SUCCEEDED'
        sums=list(s.execute(select(func.sum(Posting.delta),func.count()).group_by(Posting.journal_id)))
        assert all(total==0 and count>=2 for total,count in sums)
        effects=s.scalar(select(func.count()).select_from(ExternalRecord).where(ExternalRecord.namespace=='payment:pay_supplier',ExternalRecord.business_key==f'payment:{oid}'))
        assert effects==1
        assert s.get(MarketplaceListing,ids['listing_ids'][0]).desired_state=='PAUSED'
        result={'mode':'SYNTHETIC_DEMO','order_id':oid,'final_state':o.state,'duplicate_order_same_id':True,
            'supplier_payment_effect_count':effects,'customer_refund':5000,'confirmed_supplier_recovery':2000,
            'actual_settlement':expected,'actual_contribution_after_claim':expected-o.cost_snapshot+2000,
            'ledger_journals_balanced':len(sums),'malformed_import_status':s.get(ImportBatch,bad_batch).status,
            'price_spike_desired_state':s.get(MarketplaceListing,ids['listing_ids'][0]).desired_state,
            'price_spike_remote_state':s.get(MarketplaceListing,ids['listing_ids'][0]).remote_state,
            'production_automation_rate':None,'real_money_transferred':False,
            'important':'Synthetic provider events were explicitly injected. This is not proof of 95% production automation.'}
    (output/'demo-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='artifacts/demo');args=parser.parse_args()
    settings=Settings();_,factory=database(settings.database_url)
    print(json.dumps(run_demo(settings,factory,args.output),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
