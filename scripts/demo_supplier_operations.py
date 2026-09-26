"""Synthetic Phase 10 acceptance in a fresh, temporary SQLite DB. Never uses .env."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import importlib
import json
from alembic.migration import MigrationContext
from alembic.operations import Operations
from cryptography.fernet import Fernet
from sqlalchemy import select, func
from packages.infrastructure.db import database
from packages.infrastructure.settings import Settings
from packages.infrastructure.models import (Supplier, SupplierProduct, SupplierOrder, Order, Payment,
    SupplierPaymentEvidence, SupplierPaymentConfirmation, Shipment, Job, AuditEvent, Journal, Posting, MarketplaceListing)
from packages.application.seed import seed
from packages.application.commerce import Commerce
from packages.application.files import Files
from packages.domain.supplier_operations import Actor
from packages.integrations.suppliers.excel import workbook_bytes
from apps.worker.main import Worker


def demonstrate(payment_path):
    with TemporaryDirectory(prefix='saup-phase10-synthetic-') as directory:
        settings=Settings(_env_file=None,app_mode='test',database_url=f'sqlite:///{directory}/synthetic.db',
            pii_encryption_key=Fernet.generate_key().decode(),admin_password='synthetic-test-only-password')
        engine,factory=database(settings.database_url)
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                importlib.import_module('migrations.versions.0001_initial').upgrade()
                importlib.import_module('migrations.versions.0002_supplier_operations').upgrade()
                importlib.import_module('migrations.versions.0003_review_resolution').upgrade()
        try:
            ids=seed(settings,factory,demo=True);c=Commerce(settings,factory);worker=Worker(c);worker.drain()
            c.clock=lambda:datetime.now(timezone.utc).replace(hour=3,minute=0,second=0,microsecond=0)
            with factory.begin() as s:
                s.get(Supplier,ids['supplier_id']).mode='excel'
                for row in s.scalars(select(SupplierProduct)):row.last_inventory_at=c.clock()
            ops=c.supplier_operations;operator=Actor('synthetic-operator','operator');admin=Actor('synthetic-admin','admin')
            orders=[];supplier_orders=[]
            for i in range(2):
                with factory() as s:price=s.get(MarketplaceListing,ids['listing_ids'][i]).price
                raw={'marketplace':'coupang','external_id':f'PHASE10-SYNTHETIC-{i}','external_line_id':'1',
                    'listing_id':ids['listing_ids'][i],'quantity':1,'gross_sale':price,
                    'address':{'recipient':'합성 테스트 고객','phone':'010-0000-0000','postal_code':'01234',
                        'address1':'가상시 테스트로 123','address2':'실재하지 않는 합성 주소'}}
                order=c.ingest(raw);assert c.ingest(raw)['id']==order['id'];orders.append(order['id']);c.process_order(order['id'])
                with factory() as s:supplier_orders.append(s.scalar(select(SupplierOrder.id).where(SupplierOrder.order_id==order['id'])))
            cmd={'supplier_id':ids['supplier_id'],'profile_id':ids['profile_id'],'supplier_order_ids':supplier_orders,
                'idempotency_key':'synthetic-batch','payment_path':payment_path}
            batch=ops.create_batch(cmd,operator);assert ops.create_batch(cmd,operator)['id']==batch['id']
            content,_=ops.export_batch(batch['id'],operator);assert hashlib.sha256(content).hexdigest()==batch['file_hash']
            assert ops.export_batch(batch['id'],operator)[0]==content
            send={'send_channel':'MANUAL','send_reference':'synthetic-send-proof','file_hash':batch['file_hash']}
            ops.mark_sent(batch['id'],send,operator);ops.mark_sent(batch['id'],send,operator)
            acknowledgement={'accepted_order_ids':[supplier_orders[0]],'rejected':[{'supplier_order_id':supplier_orders[1],
                'reason':'OUT_OF_STOCK'}],'reference':'synthetic-supplier-response'}
            ops.acknowledge(batch['id'],acknowledgement,operator);ops.acknowledge(batch['id'],acknowledgement,operator)
            with factory() as s:
                payment=s.scalar(select(Payment).where(Payment.supplier_order_id==supplier_orders[0]))
                assert not s.scalar(select(Payment).where(Payment.supplier_order_id==supplier_orders[1]))
            if payment_path=='MANUAL_EVIDENCE':
                detail=ops.payment_details(payment.id,operator)
                evidence={k:detail[k] for k in ('supplier_id','amount','bank_amount','deposit_amount','destination_fingerprint')}
                evidence.update(method='MANUAL_TRANSFER',reference='synthetic-transfer-reference',evidence_hash='a'*64)
                proof=ops.record_evidence(payment.id,evidence,operator)
                assert ops.record_evidence(payment.id,evidence,operator)['id']==proof['id']
                with factory() as s:assert s.get(Payment,payment.id).status!='SUCCEEDED'
                confirmation={'amount':payment.amount,'destination_fingerprint':payment.destination_fingerprint,
                    'reference':evidence['reference'],'confirmed_money_moved':True}
                confirmed=ops.confirm_evidence(proof['id'],confirmation,admin)
                assert ops.confirm_evidence(proof['id'],confirmation,admin)==confirmed
            else:
                c.execute_payment(payment.id);c.execute_payment(payment.id)
            files=Files(c)
            tracking=workbook_bytes(['발주ID','마켓주문ID','택배사','송장번호'],[[supplier_orders[0],
                'PHASE10-SYNTHETIC-0','CJ','001234567890']])
            first=files.submit(ids['profile_id'],'shipment',tracking);assert files.submit(ids['profile_id'],'shipment',tracking)==first
            worker.drain()
            with factory() as s:
                assert s.get(SupplierOrder,supplier_orders[0]).status=='SHIPPED'
                assert s.get(SupplierOrder,supplier_orders[1]).status=='REJECTED'
                assert s.get(Payment,payment.id).status=='SUCCEEDED'
                shipment=s.scalar(select(Shipment));assert shipment and shipment.marketplace_synced
                counts={cls.__table__.name:s.scalar(select(func.count()).select_from(cls)) for cls in (
                    SupplierOrder,Payment,SupplierPaymentEvidence,SupplierPaymentConfirmation,Shipment)}
                assert counts['supplier_orders']==2 and counts['payments']==1 and counts['shipments']==1
                assert counts['supplier_payment_evidence']==int(payment_path=='MANUAL_EVIDENCE')
                jobs=s.scalar(select(func.count()).select_from(Job).where(Job.kind=='marketplace.shipment'));assert jobs==1
                journal_count=0
                for jid in s.scalars(select(Journal.id)):
                    assert s.scalar(select(func.sum(Posting.delta)).where(Posting.journal_id==jid))==0;journal_count+=1
                events=list(s.scalars(select(AuditEvent.event)))
                required={'SUPPLIER_BATCH_CREATED','SUPPLIER_BATCH_FILE_EXPORTED','SUPPLIER_BATCH_SENT',
                    'SUPPLIER_BATCH_ACKNOWLEDGED','SUPPLIER_ORDER_ACCEPTED','SUPPLIER_ORDER_REJECTED'}
                assert required<=set(events)
                return {'status':'PASS','payment_path':payment_path,'database':'temporary SQLite',
                    'real_money_moved':False,'marketplace_provider':'EXPLICIT_DEMO','accepted_supplier_state':'SHIPPED',
                    'rejected_supplier_state':'REJECTED','marketplace_shipment_update':'MOCK_CONFIRMED',
                    'file_sha256':batch['file_hash'],'counts':counts,'shipment_jobs':jobs,
                    'balanced_journals':journal_count,'audit_events':events,'interventions':ops.metrics()}
        finally:engine.dispose()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    result={'synthetic_only':True,'production_ready':False,
        'scenarios':[demonstrate(path) for path in ('MANUAL_EVIDENCE','DEMO_PROVIDER')]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('PASS: manual evidence and demo-provider Excel supplier flows; no real money or marketplace calls')

if __name__=='__main__':main()
