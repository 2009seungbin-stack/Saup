from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone, time
from zoneinfo import ZoneInfo
from decimal import Decimal
import hmac
import json
import logging
import secrets
from uuid import uuid4
from typing import Literal
from fastapi import FastAPI, Request, Depends, HTTPException, UploadFile, File
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import select, func, text
from sqlalchemy.exc import IntegrityError
from packages.domain.errors import DomainError
from packages.domain.schemas import OrderInput
from packages.domain.discovery import evaluate, experiment_state
from packages.infrastructure.settings import Settings
from packages.infrastructure.db import database, aware
from packages.infrastructure.security import RateLimiter, digest, verify_password, fingerprint
from packages.infrastructure.models import (User, AuthSession, Order, Product, Supplier, SupplierProduct, MarketplaceListing,
    SupplierExcelProfile, SupplierOrder, Payment, Claim, Refund, Settlement, Review, AuditEvent, ImportBatch, Job, Heartbeat, Experiment, Journal, Posting, Account)
from packages.application.common import lock_treasury, audit
from packages.application.finance import treasury, capacity
from packages.application.seed import seed, price_fixture
from packages.application.commerce import Commerce
from packages.application.after_sales import AfterSales
from packages.application.files import Files
from packages.integrations.suppliers.excel import ExcelProfile
from apps.worker.main import Worker

LOG=logging.getLogger("saup.api")

class BodyLimit:
    """Bound actual received bytes, including chunked requests, before body parsing."""
    def __init__(self, app, limit): self.app,self.limit=app,limit
    async def __call__(self, scope, receive, send):
        if scope['type']!='http': return await self.app(scope,receive,send)
        body=bytearray()
        while True:
            message=await receive()
            if message['type']=='http.disconnect': return
            body.extend(message.get('body',b''))
            if len(body)>self.limit:
                return await JSONResponse({'error':'REQUEST_TOO_LARGE'},413)(scope,receive,send)
            if not message.get('more_body',False): break
        sent=False
        async def bounded_receive():
            nonlocal sent
            if not sent:
                sent=True;return {'type':'http.request','body':bytes(body),'more_body':False}
            return await receive()
        await self.app(scope,bounded_receive,send)

class Input(BaseModel):
    model_config=ConfigDict(extra='forbid')
class Approval(Input):
    amount:StrictInt=Field(gt=0,le=10**12)
    destination_fingerprint:str=Field(pattern=r'^[a-f0-9]{64}$')
class ClaimInput(Input):
    external_id:str=Field(min_length=1,max_length=120)
    category:str=Field(min_length=1,max_length=40)
    amount:StrictInt=Field(gt=0,le=10**12)
    evidence:list[str]=Field(max_length=3)
class SupplierResponse(Input):
    accepted:bool
    amount:StrictInt=Field(ge=0,le=10**12)
class RefundInput(Input):
    amount:StrictInt=Field(gt=0,le=10**12)
    key:str=Field(min_length=1,max_length=160)
class SettlementInput(Input):
    external_id:str=Field(min_length=1,max_length=120)
    actual:StrictInt=Field(ge=0,le=10**12)
    adjustment:StrictInt=Field(default=0,ge=-10**9,le=10**9)
class Receipt(Input):
    receipt_id:str=Field(min_length=1,max_length=100)
    amount:StrictInt=Field(default=0,ge=0,le=10**12)
class ProfileInput(Input):
    supplier_id:str=Field(min_length=1,max_length=36)
    name:str=Field(min_length=1,max_length=100)
    mapping:ExcelProfile
class ReviewAck(Input):
    reason: str = Field(min_length=5,max_length=160)
class BankProposal(Input):
    destination_fingerprint:str=Field(pattern=r'^[a-f0-9]{64}$')
class BankApproval(BankProposal):
    verified_reference:str=Field(min_length=8,max_length=100)
class DiscoveryInput(Input):
    demand:dict[str,StrictInt]
    competition:dict[str,StrictInt]
    expected_margin:Decimal=Field(ge=-1,lt=1)
    source:str=Field(min_length=1,max_length=200)
    sample_size:StrictInt=Field(ge=0,le=100000000)
class ProbeInput(Input):
    product_id:str
    impressions:StrictInt=Field(ge=0)
    clicks:StrictInt=Field(ge=0)
    carts:StrictInt=Field(ge=0)
    orders:StrictInt=Field(ge=0)
    claims:StrictInt=Field(ge=0)
    contribution:StrictInt
    window_start:datetime
    window_end:datetime


def safe_row(row, fields):
    result={}
    for name in fields.split():
        value=getattr(row,name)
        result[name]=value.isoformat() if isinstance(value,datetime) else str(value) if isinstance(value,Decimal) else value
    return result


def create_app(settings=None, factory=None):
    settings=settings or Settings()
    if factory is None: _,factory=database(settings.database_url)
    c=Commerce(settings,factory); after=AfterSales(c); files=Files(c); worker=Worker(c); limiter=RateLimiter(settings)
    app=FastAPI(title='Saup operations API',version='0.1.0',docs_url='/docs' if settings.app_mode!='production' else None)
    app.state.commerce=c;app.state.factory=factory;app.state.settings=settings
    app.add_middleware(BodyLimit,limit=settings.upload_max_bytes+100_000)

    @app.exception_handler(DomainError)
    async def domain_error(request,exc): return JSONResponse({'error':exc.code},status_code=exc.status)
    @app.exception_handler(RequestValidationError)
    async def validation_error(request,exc):
        return JSONResponse({'error':'VALIDATION_ERROR','fields':[{'loc':list(x['loc']),'type':x['type']} for x in exc.errors()]},422)
    @app.exception_handler(IntegrityError)
    async def integrity_error(request,exc): return JSONResponse({'error':'CONCURRENT_OR_DUPLICATE_WRITE'},409)

    @app.middleware('http')
    async def secure_headers(request,call_next):
        correlation=str(uuid4());request.state.correlation_id=correlation
        response=await call_next(request)
        response.headers.update({'X-Correlation-ID':correlation,'X-Content-Type-Options':'nosniff',
            'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY'})
        if settings.app_mode=='production': response.headers['Strict-Transport-Security']='max-age=31536000; includeSubDomains'
        # No paths/querystrings, customer data, cookies or request bodies in logs.
        LOG.info(json.dumps({'event':'http_request','correlation_id':correlation,'method':request.method,'status':response.status_code}))
        return response

    from .routers.auth import create_auth_router
    from .routers.supplier_operations import create_supplier_operations_router
    auth_router, identity, viewer, operator, admin = create_auth_router(settings, factory, limiter)
    app.include_router(auth_router)
    app.include_router(create_supplier_operations_router(c.supplier_operations, viewer, operator, admin))

    def demo_only():
        if settings.app_mode not in {'demo','test'}: raise DomainError('DEMO_DISABLED',403)

    @app.get('/health')
    def health(): return {'status':'alive','mode':settings.app_mode,'real_payments_enabled':False}

    @app.get('/ready')
    def ready():
        try:
            with factory() as s:
                s.execute(text('SELECT 1'))
                heartbeat=s.scalar(select(Heartbeat).where(Heartbeat.worker=='commerce-worker'))
                worker_ready=bool(heartbeat and (datetime.now(timezone.utc)-aware(heartbeat.last_seen)).total_seconds()<90)
            redis_ready=True
            if limiter.client is not None: redis_ready=bool(limiter.client.ping())
            status=worker_ready and redis_ready
            return JSONResponse({'database':True,'worker':worker_ready,'redis':redis_ready,'ready':status},200 if status else 503)
        except Exception: return JSONResponse({'ready':False,'error':'DEPENDENCY_UNAVAILABLE'},503)

    @app.get('/v1/integrations')
    def integrations(user=Depends(viewer)): return c.registry.statuses()

    @app.get('/v1/overview')
    def overview(user=Depends(viewer)):
        now=datetime.now(ZoneInfo('Asia/Seoul'));start=datetime.combine(now.date(),time.min,now.tzinfo)
        with factory() as s:
            orders=list(s.scalars(select(Order).where(Order.created_at>=start)))
            return {'mode':settings.app_mode,'window':{'start':start.isoformat(),'timezone':'Asia/Seoul'},
                'today':{'orders':len(orders),'gross_sales':sum(x.gross_sale-x.discount for x in orders),
                  'expected_contribution':sum(x.gross_sale-x.discount-x.fee-x.promotion_cost-x.cost_snapshot for x in orders if x.cost_snapshot),
                  'claims':s.scalar(select(func.count()).select_from(Claim).where(Claim.created_at>=start))},
                'cash':treasury(s,settings),
                'risk':{'open_reviews':s.scalar(select(func.count()).select_from(Review).where(Review.status=='OPEN')),
                    'paused_listings':s.scalar(select(func.count()).select_from(MarketplaceListing).where(MarketplaceListing.desired_state=='PAUSED')),
                    'dead_jobs':s.scalar(select(func.count()).select_from(Job).where(Job.status=='DEAD'))},
                'automation':{'production_rate':None,'reason':'NOT_MEASURED','completed_local_orders':sum(x.state=='CLOSED' for x in orders),
                    'untouched_local_completed_orders':sum(x.state=='CLOSED' and x.human_interventions==0 for x in orders)}}

    @app.get('/v1/catalog')
    def catalog(user=Depends(viewer)):
        with factory() as s:
            rows=[]
            for listing in s.scalars(select(MarketplaceListing).limit(200)):
                sp=s.get(SupplierProduct,listing.supplier_product_id);product=s.get(Product,sp.product_id)
                rows.append({**safe_row(listing,'id marketplace price desired_state remote_state fee_rate'),
                    **{'sku':product.sku,'title':product.title,'cost':sp.cost,'shipping':sp.shipping,'stock':sp.stock,
                       'supplier_id':sp.supplier_id,'supplier_product_id':sp.id,
                       'safe_additional_order_capacity':capacity(s,settings,sp.supplier_id,sp.cost+sp.shipping)}})
            return rows

    @app.get('/v1/orders')
    def orders(user=Depends(viewer)):
        with factory() as s:return [safe_row(x,'id external_id external_line_id marketplace state quantity gross_sale fee cost_snapshot cancel_requested created_at correlation_id')
            for x in s.scalars(select(Order).order_by(Order.created_at.desc()).limit(200))]

    @app.get('/v1/orders/{order_id}/trail')
    def trail(order_id:str,user=Depends(viewer)):
        with factory() as s:
            order=s.get(Order,order_id)
            if order is None:raise DomainError('ORDER_NOT_FOUND',404)
            return [safe_row(x,'id event actor entity_id old_value new_value reason correlation_id created_at') for x in s.scalars(
                select(AuditEvent).where(AuditEvent.correlation_id==order.correlation_id).order_by(AuditEvent.created_at))]

    @app.get('/v1/orders/{order_id}/ledger')
    def ledger(order_id:str,user=Depends(viewer)):
        with factory() as s:
            if not s.get(Order,order_id):raise DomainError('ORDER_NOT_FOUND',404)
            result=[]
            for journal in s.scalars(select(Journal).where(Journal.order_id==order_id).order_by(Journal.created_at)):
                entries=[{'account':account.code,'delta':entry.delta} for entry,account in s.execute(
                    select(Posting,Account).join(Account,Posting.account_id==Account.id).where(Posting.journal_id==journal.id))]
                result.append({**safe_row(journal,'id kind created_at correlation_id'),'entries':entries,'sum':sum(x['delta'] for x in entries)})
            return result

    @app.get('/v1/claims')
    def claim_list(user=Depends(viewer)):
        with factory() as s:return [safe_row(x,'id order_id category status deadline requested_amount supplier_response supplier_accepted_amount supplier_recovery customer_refund') for x in s.scalars(select(Claim).order_by(Claim.created_at.desc()).limit(200))]

    @app.get('/v1/settlements')
    def settlement_list(user=Depends(viewer)):
        with factory() as s:return [safe_row(x,'id order_id expected actual difference adjustment confirmed_cash created_at') for x in s.scalars(select(Settlement).order_by(Settlement.created_at.desc()).limit(200))]

    @app.get('/v1/reviews')
    def reviews(user=Depends(viewer)):
        with factory() as s:return [safe_row(x,'id category entity_id details status resolution_code resolved_by resolved_at created_at') for x in s.scalars(select(Review).order_by(Review.created_at.desc()).limit(200))]

    @app.post('/v1/reviews/{review_id}/acknowledge')
    def acknowledge_review(review_id:str,data:ReviewAck,user=Depends(operator)):
        with factory.begin() as s:
            lock_treasury(s);row=s.get(Review,review_id)
            if row is None:raise DomainError('REVIEW_NOT_FOUND',404)
            if row.status=='OPEN':
                row.status='ACKNOWLEDGED'
                # Acknowledging is not resolving or approving a money/order action.
                audit(s,'REVIEW_ACKNOWLEDGED',row.id,actor=user['username'],new={'reason_hash':digest(data.reason)})
            return {'status':row.status,'business_state_changed':False}

    @app.get('/v1/payments')
    def payments(user=Depends(operator)):
        with factory() as s:return [safe_row(x,'id order_id amount destination_fingerprint status approved_by created_at') for x in s.scalars(select(Payment).order_by(Payment.created_at.desc()).limit(200))]

    @app.get('/v1/profiles')
    def profiles(user=Depends(viewer)):
        with factory() as s:return [safe_row(x,'id supplier_id name version mapping') for x in s.scalars(select(SupplierExcelProfile))]

    @app.post('/v1/profiles')
    def create_profile(data:ProfileInput,user=Depends(admin)):
        with factory.begin() as s:
            lock_treasury(s)
            if not s.get(Supplier,data.supplier_id):raise DomainError('SUPPLIER_NOT_FOUND',404)
            profile=SupplierExcelProfile(supplier_id=data.supplier_id,name=data.name,mapping=data.mapping.model_dump())
            s.add(profile);s.flush();audit(s,'SUPPLIER_PROFILE_CREATED',profile.id,actor=user['username'])
            return {'id':profile.id}

    @app.post('/v1/imports/{profile_id}/{kind}',status_code=202)
    async def upload(profile_id:str,kind:Literal['price','shipment'],file:UploadFile=File(...),user=Depends(operator)):
        data=await file.read(settings.upload_max_bytes+1)
        return {'batch_id':files.submit(profile_id,kind,data),'status':'QUEUED'}

    @app.get('/v1/imports')
    def imports(user=Depends(viewer)):
        with factory() as s:return [safe_row(x,'id kind status accepted rejected created_at') for x in s.scalars(select(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(100))]

    @app.get('/v1/export/{profile_id}')
    def export(profile_id:str,user=Depends(operator)):
        return Response(files.export(profile_id,user['username']),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={'Content-Disposition':'attachment; filename="supplier-orders.xlsx"'})

    @app.post('/v1/orders/{order_id}/cancel')
    def cancel(order_id:str,user=Depends(operator)):
        c.cancel(order_id,user['username']);return {'status':'CANCELLATION_REQUESTED'}

    @app.post('/v1/payments/{payment_id}/approve')
    def approve(payment_id:str,data:Approval,user=Depends(admin)):
        c.approve_payment(payment_id,data.amount,data.destination_fingerprint,user['username']);return {'status':'APPROVED'}

    @app.post('/v1/payments/{payment_id}/reconcile')
    def reconcile_payment(payment_id:str,user=Depends(admin)):return c.reconcile_payment(payment_id)

    @app.post('/v1/jobs/{job_id}/replay')
    def replay(job_id:str,user=Depends(admin)):
        worker.replay(job_id,user['username']);return {'status':'QUEUED'}

    @app.post('/v1/suppliers/{supplier_id}/destination/propose')
    def bank_propose(supplier_id:str,data:BankProposal,user=Depends(admin)):
        with factory.begin() as s:
            lock_treasury(s);supplier=s.get(Supplier,supplier_id)
            if supplier is None:raise DomainError('SUPPLIER_NOT_FOUND',404)
            supplier.destination_fingerprint=data.destination_fingerprint;supplier.destination_approved=False
            supplier.destination_proposed_by=user['username'];supplier.destination_approved_by=None
            audit(s,'BANK_ACCOUNT_CHANGED',supplier.id,actor=user['username'],new={'approved':False},reason='REVERIFICATION_REQUIRED')
            return {'status':'REVERIFICATION_REQUIRED'}

    @app.post('/v1/suppliers/{supplier_id}/destination/approve')
    def bank_approve(supplier_id:str,data:BankApproval,user=Depends(admin)):
        with factory.begin() as s:
            lock_treasury(s);supplier=s.get(Supplier,supplier_id)
            if supplier is None:raise DomainError('SUPPLIER_NOT_FOUND',404)
            if supplier.destination_proposed_by==user['username']:raise DomainError('SECOND_ADMIN_REQUIRED',403)
            if supplier.destination_fingerprint!=data.destination_fingerprint:raise DomainError('DESTINATION_CHANGED')
            supplier.destination_approved=True;supplier.destination_approved_by=user['username']
            audit(s,'BANK_DESTINATION_VERIFIED',supplier.id,actor=user['username'],new={'verification_reference_hash':digest(data.verified_reference)})
            return {'status':'WHITELISTED','live_payments_enabled':False}

    @app.post('/v1/discovery/evaluate')
    def discovery(data:DiscoveryInput,user=Depends(operator)):
        from dataclasses import asdict
        result=evaluate(data.demand,data.competition,data.expected_margin,data.source,data.sample_size,settings.min_margin)
        return asdict(result)

    @app.post('/v1/experiments')
    def experiment(data:ProbeInput,user=Depends(operator)):
        if data.window_start.tzinfo is None or data.window_end.tzinfo is None or data.window_end<=data.window_start:
            raise DomainError('INVALID_TIME_WINDOW',422)
        if data.clicks>data.impressions or data.orders>data.clicks or data.carts>data.clicks:raise DomainError('INVALID_FUNNEL',422)
        state=experiment_state(data.impressions,data.orders,data.contribution,data.claims)
        with factory.begin() as s:
            lock_treasury(s)
            if not s.get(Product,data.product_id):raise DomainError('PRODUCT_NOT_FOUND',404)
            metrics=data.model_dump(exclude={'product_id','window_start','window_end'})
            metrics['ctr']=data.clicks/data.impressions if data.impressions else None
            metrics['conversion_rate']=data.orders/data.clicks if data.clicks else None
            row=Experiment(product_id=data.product_id,state=state,metrics=metrics,window_start=data.window_start,
                window_end=data.window_end,method='manual authorized metrics; deterministic contribution guard v1')
            s.add(row);s.flush();audit(s,'PROBE_EVALUATED',row.id,actor=user['username'],new={'state':state})
            return {'id':row.id,'state':state,'automatically_scaled':False}

    @app.post('/demo/seed')
    def demo_seed(user=Depends(admin)):
        demo_only();return seed(settings,factory,demo=True)

    @app.post('/demo/orders',status_code=202)
    def demo_order(data:OrderInput,user=Depends(operator)):
        demo_only();return c.ingest(data.model_dump())

    @app.get('/demo/price-file')
    def demo_price_file(user=Depends(viewer)):
        demo_only();return Response(price_fixture(),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={'Content-Disposition':'attachment; filename="demo-prices.xlsx"'})

    @app.post('/demo/orders/{order_id}/delivered')
    def demo_delivered(order_id:str,user=Depends(operator)):
        demo_only();c.delivered(order_id);return {'status':'DELIVERED'}

    @app.post('/demo/orders/{order_id}/claims')
    def demo_claim(order_id:str,data:ClaimInput,user=Depends(operator)):
        demo_only();return {'claim_id':after.open_claim(order_id,data.external_id,data.category,data.amount,data.evidence)}

    @app.post('/demo/claims/{claim_id}/supplier-response')
    def demo_response(claim_id:str,data:SupplierResponse,user=Depends(operator)):
        demo_only();after.supplier_response(claim_id,data.amount,data.accepted,actor=user['username']);return {'status':'RECORDED'}

    @app.post('/demo/claims/{claim_id}/supplier-recovery')
    def demo_recovery(claim_id:str,data:Receipt,user=Depends(admin)):
        demo_only();after.confirm_supplier_recovery(claim_id,data.amount,data.receipt_id,actor=user['username']);return {'status':'RECORDED'}

    @app.post('/demo/claims/{claim_id}/refund')
    def demo_refund(claim_id:str,data:RefundInput,user=Depends(admin)):
        demo_only();return {'refund_id':after.request_refund(claim_id,data.amount,data.key,actor=user['username'])}

    @app.post('/demo/orders/{order_id}/settlement')
    def demo_settlement(order_id:str,data:SettlementInput,user=Depends(operator)):
        demo_only();return {'settlement_id':after.reconcile_settlement(order_id,data.external_id,data.actual,data.adjustment,actor=user['username'])}

    @app.post('/demo/settlements/{settlement_id}/confirm')
    def demo_confirm(settlement_id:str,data:Receipt,user=Depends(admin)):
        demo_only();after.confirm_settlement_cash(settlement_id,data.receipt_id,actor=user['username']);return {'status':'CONFIRMED'}
    return app
