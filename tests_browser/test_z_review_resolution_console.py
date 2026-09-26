"""Phase 11A acceptance follows the existing source-ordered supplier scenarios."""
from hashlib import sha256
import json
from playwright.sync_api import expect
from test_supplier_console import api,ok,create_by_api,open_batch,send_ui,acknowledge_ui
from conftest import REPORTS,docker_fixture


def resolutions(page):
    page.get_by_role('navigation',name='운영 메뉴').get_by_role('button',name='검토 해결',exact=True).click()
    expect(page.get_by_role('heading',name='검토 해결 · 증빙과 공급사 환급',exact=True)).to_be_visible()


def test_evidence_correction_then_cancelled_supplier_recovery_ui(pages,fixture_data):
    page=pages();value,order,so=create_by_api(page,fixture_data)
    open_batch(page,value['id']);send_ui(page,value);state=acknowledge_ui(page,value)
    pid=state['items'][0]['payment_id'];page.get_by_role('button',name='지급 증빙',exact=True).click()
    page.get_by_label('은행·공급사 지급 참조 번호',exact=True).fill('e2e-corrected-payment-'+value['id'])
    page.get_by_label('증빙 SHA-256',exact=True).fill(sha256(b'wrong synthetic document').hexdigest())
    page.get_by_role('button',name='증빙 기록 · 아직 지급 확정 아님',exact=True).click()
    expect(page.get_by_role('button',name='증빙 정정 요청 · 지급 확인 차단',exact=True)).to_be_visible()
    with page.expect_response(lambda r: r.url.endswith('/correction-request') and r.request.method=='POST') as response:
        page.get_by_role('button',name='증빙 정정 요청 · 지급 확인 차단',exact=True).click()
    assert response.value.status==201;rid=response.value.json()['review_id']
    expect(page.get_by_text('증빙 정정 검토 중입니다. 지급 확인이 차단되었습니다. 검토 해결 메뉴에서 처리하세요.',exact=True)).to_be_visible()
    payment=ok(api(page,f'/v1/supplier-payments/{pid}'))
    stale={'amount':payment['amount'],'reference':payment['evidence']['reference'],
        'destination_fingerprint':payment['destination_fingerprint'],'confirmed_money_moved':True}
    admin=pages('admin')
    blocked=api(admin,f"/v1/supplier-payment-evidence/{payment['evidence_id']}/confirm",'POST',stale)
    assert blocked['status']==409 and blocked['body']['error']=='PAYMENT_EVIDENCE_CORRECTION_REQUIRED'
    resolutions(admin);admin.get_by_role('button',name=rid,exact=True).click()
    expect(admin.get_by_role('heading',name='미확정 증빙 정정',exact=True)).to_be_visible()
    admin.get_by_label('해결 증빙 SHA-256',exact=True).fill(sha256(b'correct synthetic document').hexdigest())
    apply=admin.get_by_role('button',name='증빙 정정 적용',exact=True);expect(apply).to_be_disabled()
    admin.get_by_label('동일한 지급의 증빙 정보 정정이며 금액과 수취처는 변경하지 않음을 확인했습니다.',exact=True).check()
    apply.click();expect(admin.get_by_text('검토 상태: RESOLVED',exact=True)).to_be_visible()
    assert api(admin,f"/v1/supplier-payment-evidence/{payment['evidence_id']}/confirm",'POST',stale)['status']==409
    open_batch(admin,value['id']);admin.get_by_role('button',name='지급 증빙',exact=True).click()
    admin.get_by_label('해당 수취처로 이 금액의 실제 지급이 완료되었음을 증빙으로 확인했습니다.',exact=True).check()
    admin.get_by_role('button',name='관리자 지급 증빙 확인',exact=True).click()
    expect(admin.get_by_text('관리자 지급 증빙 확인이 완료되었습니다. 이 화면에서 송금을 실행한 것은 아닙니다.',exact=True)).to_be_visible()
    ok(api(admin,f"/v1/supplier-orders/{so['id']}/cancel",'POST'))
    ok(api(admin,f"/v1/supplier-orders/{so['id']}/cancellation/confirm",'POST',
        {'reference':'e2e-confirmed-cancel-'+so['id'],'supplier_confirmed_cancelled':True}))
    rows=ok(api(admin,'/v1/review-resolutions'))
    financial=next(x for x in rows if x['entity_id']==so['id'] and x['category']=='SUPPLIER_CANCELLATION_FINANCIAL_REVIEW')
    before=docker_fixture('snapshot')
    resolutions(admin);admin.get_by_role('button',name=financial['id'],exact=True).click()
    expect(admin.get_by_role('heading',name='지급 후 공급사 전액 환급 확인',exact=True)).to_be_visible()
    admin.get_by_label('해결 참조 번호',exact=True).fill('e2e-incoming-refund-'+so['id'])
    admin.get_by_label('해결 증빙 SHA-256',exact=True).fill(sha256(b'synthetic incoming refund, not outgoing payment').hexdigest())
    button=admin.get_by_role('button',name='관리자 공급사 환급 확인',exact=True);expect(button).to_be_disabled()
    admin.get_by_label('표시된 은행·공급사 예치금 배분대로 환급액이 실제 입금되었음을 확인했습니다.',exact=True).check()
    with admin.expect_response(lambda r: r.url.endswith('/confirm-supplier-recovery') and r.request.method=='POST') as response:
        button.click()
    assert response.value.status==200;result=response.value.json();command=response.value.request.post_data_json
    expect(admin.get_by_text('검토 상태: RESOLVED',exact=True)).to_be_visible()
    assert ok(api(admin,f"/v1/review-resolutions/{financial['id']}/confirm-supplier-recovery",'POST',command))==result
    after=docker_fixture('snapshot')
    assert after['counts']['supplier_cancellation_recoveries']==1 and after['counts']['supplier_payment_evidence_revisions']==1
    assert after['accounts']['BANK']==before['accounts']['BANK']+payment['bank_amount']
    observed=after['orders'][order['id']]
    assert observed['payment_status']=='SUCCEEDED' and observed['state']=='CANCEL_REQUESTED' and observed['reservation_status']=='SPENT'
    assert observed['shipment_id'] is None and after['balanced_journals']
    admin.get_by_role('button',name=result['customer_review_id'],exact=True).click()
    expect(admin.get_by_text('현재 실행 불가: NO_AUTOMATED_RESOLUTION_FOR_CATEGORY',exact=True)).to_be_visible()
    (REPORTS/'phase11-review-resolution.json').write_text(json.dumps({'result':result,'before':before,'after':after},indent=2))


def test_review_resolution_viewer_is_status_only(pages):
    page=pages('viewer');resolutions(page)
    rows=ok(api(page,'/v1/review-resolutions'));assert rows
    for row in rows:
        assert 'snapshot' not in row and 'reference' not in row
        expect(page.get_by_role('button',name=row['id'],exact=True)).not_to_be_visible()
    rid=rows[0]['id']
    assert api(page,f'/v1/review-resolutions/{rid}')['status']==403
    assert api(page,f'/v1/review-resolutions/{rid}/correct-payment-evidence','POST',{})['status']==403
    assert api(page,f'/v1/review-resolutions/{rid}/confirm-supplier-recovery','POST',{})['status']==403
