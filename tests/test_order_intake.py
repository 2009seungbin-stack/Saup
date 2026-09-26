"""Real workbook bytes and application transactions; no production money/provider use."""
from datetime import timedelta
from io import BytesIO
from zipfile import ZipFile
import json
from unittest.mock import patch
import pytest
from openpyxl import load_workbook
from pydantic import ValidationError
from sqlalchemy import select, func
from packages.application.order_intake import OrderIntake, SOURCE_REVIEW, IMPORT_SCOPE
from packages.domain.order_intake import ImportConfirmation, VerifyImportedOrder
from packages.domain.errors import DomainError
from packages.integrations.marketplaces.order_file import COLUMNS, SHEET, parse_orders, template
from packages.integrations.suppliers.excel import workbook_bytes
from packages.infrastructure.models import (Order, SupplierOrder, Payment, Reservation, Job, Review, AuditEvent,
    Command, Supplier, SupplierProduct, MarketplaceListing)
from packages.application.commerce import Commerce
from test_supplier_operations import excel_env, OP, ADMIN, VIEWER, batch, send, ack, payment, record, confirm, tracking


@pytest.fixture
def intake(excel_env):
    return OrderIntake(excel_env['commerce'])


def content(raw, **changes):
    values = {**{k: raw[k] for k in ('external_id','external_line_id','listing_id','quantity','gross_sale','discount') if k in raw},
        'discount': raw.get('discount', 0), **raw['address'], **changes}
    return [values[k] for k in COLUMNS]


def file_for(raw, *extra, **changes):
    return workbook_bytes(list(COLUMNS.values()), [content(raw, **changes), *extra], SHEET)


def import_file(service, data, actor=OP, **changes):
    preview = service.preview(data, 'coupang', actor)
    cmd = {'marketplace':'coupang','preview_token':preview['preview_token'],'source_reference':'seller-export-001',
        'confirmed_authorized_source':True, **changes}
    return service.commit(data, cmd, actor), cmd


def verify_payload(service, order_id, **changes):
    d = service.order_details(order_id)
    return {'idempotency_key':'verify-001','snapshot_hash':d['snapshot_hash'], 'source_reference':'seller-current-001',
        'evidence_hash':'e'*64,'observed_at':service.c.clock().isoformat(),'confirmed_current_order_open':True, **changes}


def counts(e):
    with e['factory']() as s:
        return {cls.__name__:s.scalar(select(func.count()).select_from(cls)) for cls in
            (Order, SupplierOrder, Payment, Reservation, Job, Review, AuditEvent, Command)}


def test_preview_read_only_and_pii_free(excel_env, intake, order_input):
    before = counts(excel_env); p = intake.preview(file_for(order_input), 'coupang', OP)
    assert counts(excel_env) == before and p['new_count']==1 and p['can_commit']
    text = json.dumps(p, ensure_ascii=False)
    for secret in order_input['address'].values():
        assert secret not in text
    ticket = intake.c.cipher.decrypt(p['preview_token'])
    assert 'address' not in json.dumps(ticket) and ticket['file_hash']==p['file_hash']


def test_import_and_replay_do_not_accept_pay_or_schedule_provider(excel_env, intake, order_input):
    data=file_for(order_input); first,cmd=import_file(intake,data);second=intake.commit(data,cmd,OP)
    assert first['id']==second['id'] and second['replayed'] and first['new_count']==1
    with excel_env['factory']() as s:
        order=s.get(Order,first['items'][0]['id']);assert order.state=='RECEIVED'
        assert not s.scalar(select(SupplierOrder)) and not s.scalar(select(Payment)) and not s.scalar(select(Reservation))
        assert not s.scalar(select(Job).where(Job.kind=='order.process'))
        assert s.scalar(select(Review).where(Review.category==SOURCE_REVIEW)).status=='OPEN'
        assert all(secret not in order.pii_ciphertext for secret in order_input['address'].values())
        assert intake.c.cipher.decrypt(order.pii_ciphertext)['original_address']==order_input['address']
        audit_data=json.dumps([x.new_value for x in s.scalars(select(AuditEvent))],ensure_ascii=False)
        receipts=json.dumps([x.result for x in s.scalars(select(Command))],ensure_ascii=False)
        for secret in order_input['address'].values():assert secret not in audit_data+receipts


def test_validated_import_reuses_entire_supplier_path_without_api_for_intake(excel_env, intake, order_input):
    e=excel_env; result,_=import_file(intake,file_for(order_input));oid=result['items'][0]['id']
    cmd=verify_payload(intake,oid)
    with patch.object(e['commerce'].registry,'marketplace',side_effect=AssertionError('unexpected provider call')):
        result=intake.verify_and_validate(oid,cmd,OP)
        assert result==intake.verify_and_validate(oid,cmd,OP)
    assert result['state']=='SUPPLIER_ORDER_PENDING' and not result['supplier_accepted'] and not result['api_verified']
    with e['factory']() as s:
        so=s.scalar(select(SupplierOrder)).id
        assert s.scalar(select(Reservation)).status=='HELD' and not s.scalar(select(Payment))
        assert s.scalar(select(Review).where(Review.category==SOURCE_REVIEW)).status=='RESOLVED'
    b=batch(e,[so]);send(e,b);ack(e,b);p=payment(e,so);proof=record(e,p);confirm(e,p,proof)
    with e['factory'].begin() as s:
        shipment=e['commerce'].add_shipment(s,tracking(e,so));sid=shipment.id
    from packages.domain.errors import IntegrationError
    with pytest.raises(IntegrationError, match='MANUAL_EXTERNAL_SHIPMENT_CONFIRMATION_REQUIRED'):
        e['commerce'].sync_shipment(sid)
    assert counts(e)['Payment']==1 and counts(e)['SupplierOrder']==1


def test_reference_conflict_never_overwrites_history(excel_env,intake,order_input):
    data=file_for(order_input);_,cmd=import_file(intake,data);before=counts(excel_env)
    with pytest.raises(DomainError,match='IDEMPOTENCY_CONFLICT'):
        intake.commit(data,cmd|{'source_reference':'different'},OP)
    assert before==counts(excel_env)


@pytest.mark.parametrize('field,value,code',[
    ('external_id',123,'IDENTIFIER_MUST_BE_TEXT'),('external_line_id',1,'IDENTIFIER_MUST_BE_TEXT'),
    ('postal_code',1234,'IDENTIFIER_MUST_BE_TEXT'),('phone',1000000000,'IDENTIFIER_MUST_BE_TEXT'),
    ('quantity',True,'INVALID_NUMBER'),('quantity',1.5,'INVALID_NUMBER'),('quantity',0,'ROW_VALIDATION_FAILED'),
    ('discount',None,'INVALID_NUMBER'),('gross_sale',-1,'INVALID_NUMBER'),
    ('address1','x','ROW_VALIDATION_FAILED'),('recipient','bad\nname','ROW_VALIDATION_FAILED'),
    ('external_id','\t123','INVALID_IDENTIFIER'),('quantity','1,00','INVALID_NUMBER'),
])
def test_bad_rows_fail_closed(excel_env,intake,order_input,field,value,code):
    data=file_for(order_input,**{field:value})
    p=intake.preview(data,'coupang',OP)
    assert p['error_count']==1 and not p['can_commit'] and p['errors'][0]['code']==code
    before=counts(excel_env)
    with pytest.raises(DomainError,match='ORDER_FILE_HAS_ERRORS'):
        intake.commit(data,{'marketplace':'coupang','preview_token':p['preview_token'],
            'source_reference':'invalid','confirmed_authorized_source':True},OP)
    assert before==counts(excel_env)


def test_leading_zeroes_literal_text_formula_and_no_address_rewrite(intake,order_input):
    raw=order_input|{'external_id':'0000123','external_line_id':'001'}
    data=file_for(raw,recipient='=not-a-formula')
    rows=parse_orders(data,'coupang').rows
    assert rows[0][1]['external_id']=='0000123' and rows[0][1]['external_line_id']=='001'
    assert rows[0][1]['address']['postal_code']=='01234' and rows[0][1]['address']['recipient']=='=not-a-formula'
    wb=load_workbook(BytesIO(data));wb[SHEET]['G2']='=1+1';out=BytesIO();wb.save(out);wb.close()
    assert intake.preview(out.getvalue(),'coupang',OP)['errors'][0]['code']=='FORMULA_NOT_ALLOWED'


@pytest.mark.parametrize('variant',['header','sheet','empty','extra_column','too_many_rows','zip'])
def test_workbook_shape_limits(intake,order_input,variant):
    if variant=='zip':data=b'not an excel file'
    elif variant=='empty':data=template()
    elif variant=='header':data=workbook_bytes(list(COLUMNS.values())[:-1],[],SHEET)
    elif variant=='sheet':data=workbook_bytes(list(COLUMNS.values()),[content(order_input)],'other')
    elif variant=='extra_column':data=workbook_bytes([*COLUMNS.values(),'hidden'],[[*content(order_input),'unmapped']],SHEET)
    else:data=workbook_bytes(list(COLUMNS.values()),[content(order_input)]*501,SHEET)
    with pytest.raises(DomainError):intake.preview(data,'coupang',OP)


def test_duplicate_rows_quarantined_and_atomic_file(intake,excel_env,order_input):
    data=file_for(order_input,content(order_input))
    p=intake.preview(data,'coupang',OP)
    assert p['error_count']==2 and not p['can_commit'] and not p['rows']
    assert counts(excel_env)['Order']==0


def test_mixed_valid_invalid_file_does_not_partially_import(intake,excel_env,order_input):
    data=file_for(order_input,content(order_input,external_id='other',listing_id='unknown'))
    p=intake.preview(data,'coupang',OP)
    assert p['new_count']==1 and p['error_count']==1
    with pytest.raises(DomainError,match='ORDER_FILE_HAS_ERRORS'):import_file(intake,data)
    assert counts(excel_env)['Order']==0


def test_unchanged_orders_in_different_files_remain_duplicates(intake,excel_env,order_input):
    first,_=import_file(intake,file_for(order_input))
    second,_=import_file(intake,file_for(order_input,content(order_input,external_id='another')))
    assert second['new_count']==1 and second['duplicate_count']==1
    assert second['items'][0]['id']==first['items'][0]['id'] and counts(excel_env)['Order']==2


def test_changed_existing_order_never_overwrites_pii(intake,order_input):
    import_file(intake,file_for(order_input))
    p=intake.preview(file_for(order_input,address2='CHANGED'),'coupang',OP)
    assert p['errors'][0]['code']=='ORDER_IDENTITY_PAYLOAD_CONFLICT'


def test_tampered_swapped_cross_actor_preview(intake,order_input):
    data=file_for(order_input);p=intake.preview(data,'coupang',OP)
    cmd={'marketplace':'coupang','preview_token':p['preview_token'],'source_reference':'source','confirmed_authorized_source':True}
    for raw,who,blob in [(cmd|{'preview_token':'x'*100},OP,data),(cmd,ADMIN,data),(cmd,OP,file_for(order_input,external_id='changed'))]:
        with pytest.raises(DomainError,match='ORDER_PREVIEW_TOKEN_INVALID'):intake.commit(blob,raw,who)


def test_expired_preview_but_successful_replay_survives_restart(intake,excel_env,order_input):
    data=file_for(order_input);p=intake.preview(data,'coupang',OP)
    cmd={'marketplace':'coupang','preview_token':p['preview_token'],'source_reference':'source','confirmed_authorized_source':True}
    initial=intake.c.clock();intake.c.clock=lambda:initial+timedelta(minutes=11)
    with pytest.raises(DomainError,match='ORDER_PREVIEW_EXPIRED'):intake.commit(data,cmd,OP)
    intake.c.clock=lambda:initial
    result=intake.commit(data,cmd,OP)
    restarted=OrderIntake(Commerce(excel_env['settings'],excel_env['factory'],clock=lambda:initial+timedelta(hours=2)))
    replay=restarted.commit(data,cmd,OP)
    assert replay['id']==result['id'] and replay['replayed']


def test_stale_preview_requires_review_again(intake,excel_env,order_input):
    data=file_for(order_input);p=intake.preview(data,'coupang',OP)
    excel_env['commerce'].ingest(order_input)
    with pytest.raises(DomainError,match='ORDER_PREVIEW_STALE'):
        intake.commit(data,{'marketplace':'coupang','preview_token':p['preview_token'],
            'source_reference':'source','confirmed_authorized_source':True},OP)


def test_import_rolls_back_everything_on_second_row_failure(excel_env,intake,order_input,monkeypatch):
    data=file_for(order_input,content(order_input,external_id='second'));p=intake.preview(data,'coupang',OP)
    old=intake.c.ingest_in_session
    def fail(s,data,**kw):
        result=old(s,data,**kw)
        if data.external_id=='second':raise DomainError('AFTER_SECOND_INSERT')
        return result
    monkeypatch.setattr(intake.c,'ingest_in_session',fail);before=counts(excel_env)
    with pytest.raises(DomainError,match='AFTER_SECOND_INSERT'):
        intake.commit(data,{'marketplace':'coupang','preview_token':p['preview_token'],
            'source_reference':'source','confirmed_authorized_source':True},OP)
    assert counts(excel_env)==before


@pytest.mark.parametrize('age',[-1,901])
def test_current_status_evidence_freshness(intake,order_input,age):
    receipt,_=import_file(intake,file_for(order_input));oid=receipt['items'][0]['id']
    cmd=verify_payload(intake,oid,observed_at=(intake.c.clock()-timedelta(seconds=age)).isoformat())
    with pytest.raises(DomainError,match='CURRENT_MARKETPLACE_EVIDENCE_REQUIRED'):intake.verify_and_validate(oid,cmd,OP)


def test_pre_order_retry_does_not_force_money_or_supplier_acceptance(excel_env,intake,order_input):
    e=excel_env;result,_=import_file(intake,file_for(order_input));oid=result['items'][0]['id']
    with e['factory'].begin() as s:s.get(Supplier,e['ids']['supplier_id']).cutoff='00:00'
    cmd=verify_payload(intake,oid);assert intake.verify_and_validate(oid,cmd,OP)['state']=='MANUAL_REVIEW'
    with e['factory']() as s:
        assert not s.scalar(select(Reservation)) and not s.scalar(select(Payment)) and not s.scalar(select(SupplierOrder))
    with e['factory'].begin() as s:s.get(Supplier,e['ids']['supplier_id']).cutoff='23:59'
    again=verify_payload(intake,oid,idempotency_key='retry-fresh')
    assert intake.verify_and_validate(oid,again,OP)['state']=='SUPPLIER_ORDER_PENDING'
    with e['factory']() as s:
        assert s.scalar(select(Review).where(Review.category=='SUPPLIER_CUTOFF')).status=='RESOLVED'
        assert s.scalar(select(SupplierOrder)).status=='PENDING' and not s.scalar(select(Payment))


def test_cancel_unknown_review_or_existing_effects_prevent_retry(intake,excel_env,order_input):
    result,_=import_file(intake,file_for(order_input));oid=result['items'][0]['id']
    cmd=verify_payload(intake,oid)
    from packages.application.common import review
    with excel_env['factory'].begin() as s:review(s,'UNKNOWN_EXTERNAL_EFFECT',oid)
    assert not intake.order_details(oid)['can_verify_and_validate']
    with pytest.raises(DomainError,match='ORDER_HAS_UNSUPPORTED_REVIEW'):intake.verify_and_validate(oid,cmd,OP)
    excel_env['commerce'].cancel(oid)
    with pytest.raises(DomainError,match='ORDER_NOT_VALIDATABLE'):intake.verify_and_validate(oid,cmd,OP)


def test_api_ingestion_cannot_be_relabelled_as_file_verified(intake,excel_env,order_input):
    oid=excel_env['commerce'].ingest(order_input)['id']
    with pytest.raises(DomainError,match='ORDER_NOT_FROM_VERIFIED_IMPORT'):intake.order_details(oid)


def test_state_snapshot_rechecked_under_lock(intake,excel_env,order_input):
    result,_=import_file(intake,file_for(order_input));oid=result['items'][0]['id'];cmd=verify_payload(intake,oid)
    with excel_env['factory'].begin() as s:
        sp=s.get(SupplierProduct,s.get(MarketplaceListing,order_input['listing_id']).supplier_product_id);sp.cost+=1
    with pytest.raises(DomainError,match='ORDER_VALIDATION_SNAPSHOT_STALE'):intake.verify_and_validate(oid,cmd,OP)


@pytest.mark.parametrize('value',[False,1,'true',None])
def test_attestation_literals_only(value,intake,order_input):
    with pytest.raises(ValidationError):ImportConfirmation.model_validate({'marketplace':'coupang','preview_token':'x'*100,
        'source_reference':'source','confirmed_authorized_source':value})
    with pytest.raises(ValidationError):VerifyImportedOrder.model_validate({'idempotency_key':'key','snapshot_hash':'a'*64,
        'source_reference':'source','evidence_hash':'b'*64,'observed_at':intake.c.clock(), 'confirmed_current_order_open':value})


def test_viewer_domain_guards(intake,order_input):
    data=file_for(order_input)
    with pytest.raises(DomainError,match='FORBIDDEN'):intake.preview(data,'coupang',VIEWER)
    with pytest.raises(DomainError,match='FORBIDDEN'):intake.commit(data,{},VIEWER)
    with pytest.raises(DomainError,match='FORBIDDEN'):intake.verify_and_validate('unknown',{},VIEWER)


def test_claimed_dimensions_cannot_hide_unmapped_rows_or_columns(intake,order_input):
    # A malicious export can lie in <dimension>; inspect physical XML cells too.
    data=file_for(order_input)
    for hidden_cell in ('L2','A502'):
        output=BytesIO()
        with ZipFile(BytesIO(data)) as src, ZipFile(output,'w') as dst:
            for name in src.namelist():
                value=src.read(name)
                if name=='xl/worksheets/sheet1.xml':
                    row='502' if hidden_cell=='A502' else '2'
                    value=value.replace(b'</sheetData>',f'<row r="{row}"><c r="{hidden_cell}" t="inlineStr"><is><t>hidden</t></is></c></row></sheetData>'.encode())
                dst.writestr(name,value)
        with pytest.raises(DomainError,match='ORDER_WORKSHEET_LIMIT'):
            intake.preview(output.getvalue(),'coupang',OP)


def test_failure_after_reservation_rolls_back_business_effects(excel_env,intake,order_input,monkeypatch):
    result,_=import_file(intake,file_for(order_input));oid=result['items'][0]['id']
    with excel_env['factory']() as s:
        spid=s.get(MarketplaceListing,order_input['listing_id']).supplier_product_id
        stock=s.get(SupplierProduct,spid).stock
    def fail(*args):raise DomainError('SYNTHETIC_AFTER_RESERVATION')
    monkeypatch.setattr(intake.c.supplier_operations,'freeze_intent',fail)
    r=intake.verify_and_validate(oid,verify_payload(intake,oid),OP)
    assert r['state']=='MANUAL_REVIEW'
    with excel_env['factory']() as s:
        assert not s.scalar(select(SupplierOrder)) and not s.scalar(select(Reservation)) and not s.scalar(select(Payment))
        assert s.get(SupplierProduct,spid).stock==stock
    # The unknown error is not included in this bounded retry's allowlist.
    assert not intake.order_details(oid)['can_verify_and_validate']


def test_automatic_worker_cannot_skip_manual_source_verification(excel_env,intake,order_input):
    result,_=import_file(intake,file_for(order_input));oid=result['items'][0]['id']
    with patch.object(intake.c.registry,'marketplace',side_effect=AssertionError('automatic verification not allowed')):
        intake.c.process_order(oid)
    with excel_env['factory']() as s:
        assert s.get(Order,oid).state=='RECEIVED' and not s.scalar(select(SupplierOrder))


def test_source_verification_keeps_live_payment_and_provider_blockers(excel_env,intake,order_input):
    from packages.integrations.adapters import BlockedAdapter
    result,_=import_file(intake,file_for(order_input));oid=result['items'][0]['id']
    blocked=BlockedAdapter('coupang','BLOCKED_BY_CREDENTIALS')
    with patch.object(intake.c.registry,'marketplace',return_value=blocked):
        outcome=intake.verify_and_validate(oid,verify_payload(intake,oid),OP)
    assert not outcome['api_verified'] and outcome['state']=='SUPPLIER_ORDER_PENDING'
    assert not excel_env['settings'].real_payments_enabled
    from packages.infrastructure.settings import Settings
    with pytest.raises(ValidationError,match='no certified live payment adapter'):
        Settings(_env_file=None,pii_encryption_key=excel_env['settings'].pii_encryption_key,real_payments_enabled=True)


def test_confirmed_cancellation_evidence_blocks_late_file_line(excel_env,intake,order_input):
    # Actual application cancellation/recovery/evidence flow; no SQL state forcing.
    from test_marketplace_cancellation import recovered, refund
    from packages.application.review_resolution import ReviewResolutionService
    e=excel_env;e['resolution']=ReviewResolutionService(e['commerce'])
    _,_,rid=recovered(e,order_input,name=order_input['external_id']);refund(e,rid)
    late=order_input|{'external_line_id':'late-002'}
    result,_=import_file(intake,file_for(late));oid=result['items'][0]['id']
    d=intake.order_details(oid)
    assert d['state']=='MANUAL_REVIEW' and not d['can_verify_and_validate']
    with pytest.raises(DomainError,match='MARKETPLACE_LINE_AFTER_CANCELLATION_EVIDENCE'):
        intake.verify_and_validate(oid,verify_payload(intake,oid),OP)


@pytest.mark.parametrize('mutation', ['duplicate_cell','row_mismatch','duplicate_row','unscanned_sheet'])
def test_ambiguous_physical_xml_is_rejected(intake,order_input,mutation):
    data=file_for(order_input)
    source=ZipFile(BytesIO(data)); target=BytesIO()
    with ZipFile(target,'w') as dest:
        for info in source.infolist():
            value=source.read(info.filename)
            if info.filename=='xl/worksheets/sheet1.xml':
                if mutation=='duplicate_cell':value=value.replace(b'r="B2"', b'r="A2"')
                if mutation=='row_mismatch':value=value.replace(b'r="A2"', b'r="A3"')
                if mutation=='duplicate_row':value=value.replace(b'<row r="2">', b'<row r="1">')
            if mutation=='unscanned_sheet' and info.filename=='xl/_rels/workbook.xml.rels':
                value=value.replace(b'/xl/worksheets/sheet1.xml',b'/xl/custom.xml')
            dest.writestr(info,value)
        if mutation=='unscanned_sheet':dest.writestr('xl/custom.xml',source.read('xl/worksheets/sheet1.xml'))
    source.close()
    with pytest.raises(DomainError):intake.preview(target.getvalue(),'coupang',OP)
