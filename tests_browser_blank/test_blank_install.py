"""Actual Chromium sessions and API requests against a genuinely blank stack."""
import json
from pathlib import Path
import time
from playwright.sync_api import sync_playwright, expect
from scripts.closure_scenario import run

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports'/'blank';OUT.mkdir(parents=True,exist_ok=True)


def test_blank_install_operator_workflow():
    env=dict(line.split('=',1) for line in (ROOT/'.env').read_text().splitlines() if '=' in line and not line.startswith('#'))
    with sync_playwright() as p:
        browser=p.chromium.launch();contexts={};pages={};errors=[]
        (OUT/'browser-version.txt').write_text(browser.version+'\n')
        def login(name,username,password):
            ctx=browser.new_context(base_url='http://localhost:3000',viewport={'width':1440,'height':1100})
            page=ctx.new_page();page.goto('/')
            page.get_by_label('아이디',exact=True).fill(username)
            page.get_by_label('비밀번호',exact=True).fill(password)
            page.get_by_role('button',name='로그인',exact=True).click()
            expect(page.get_by_role('heading',name='운영 현황',exact=True)).to_be_visible(timeout=15000)
            page.on('pageerror',lambda _:errors.append('UNCAUGHT_BROWSER_ERROR'))
            contexts[name]=ctx;pages[name]=page
        login('admin','admin',env['ADMIN_PASSWORD'])
        page=pages['admin'];page.get_by_role('button',name='초기 설정',exact=True).click()
        expect(page.get_by_text('공급사 생성 필요',exact=True)).to_be_visible()
        expect(page.get_by_role('form',name='1. 로컬 계정 생성')).to_be_visible()
        def call(method,path,body=None,file=None,actor='admin',binary=False):
            ctx=contexts[actor];csrf=next(c['value'] for c in ctx.cookies() if c['name']=='saup_csrf')
            args={'headers':{'Origin':'http://localhost:3000','X-CSRF-Token':csrf}}
            if file:
                args['multipart']={**(body or {}),'file':{'name':'input.xlsx','mimeType':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','buffer':file}}
            elif body is not None:args['data']=body
            response=ctx.request.fetch('/api'+path,method=method,**args)
            assert response.ok,(path,response.status,response.text())
            return response.body() if binary else response.json()
        result=run(call,lambda:login('second','second-admin','Synthetic-second-admin-123!'),lambda:time.sleep(.25))
        page.reload();expect(page.get_by_role('heading',name='운영 현황',exact=True)).to_be_visible()
        for name in ['초기 설정','외부 처리 확인','클레임','정산']:
            page.get_by_role('button',name=name,exact=True).click()
            expect(page.get_by_role('heading',name=name,exact=True)).to_be_visible()
            if name=='클레임':expect(page.get_by_text('ROTTEN · REFUNDED',exact=False)).to_be_visible()
            if name=='정산':expect(page.get_by_text('입금 확인됨',exact=True)).to_have_count(2)
            page.screenshot(path=str(OUT/f'{name}.png'),full_page=True)
        # Exercise an actual form, including its successful mutation/refresh.
        page.get_by_role('button',name='초기 설정',exact=True).click()
        form=page.get_by_role('form',name='1. 로컬 계정 생성')
        form.get_by_label('새 아이디',exact=True).fill('blank-viewer')
        form.get_by_label('새 비밀번호 (12자 이상)',exact=True).fill('Synthetic-viewer-123!')
        form.get_by_label('역할',exact=True).select_option('viewer')
        form.get_by_role('button',name='1. 로컬 계정 생성',exact=True).click()
        expect(form.get_by_role('status')).to_have_text('기록 완료')
        login('viewer','blank-viewer','Synthetic-viewer-123!')
        viewer=pages['viewer'];viewer.get_by_role('button',name='초기 설정',exact=True).click()
        expect(viewer.get_by_role('heading',name='초기 설정',exact=True)).to_be_visible()
        expect(viewer.get_by_role('form',name='1. 로컬 계정 생성')).to_have_count(0)
        assert not errors
        # Allow the normal worker to finish notification jobs before durable snapshot.
        time.sleep(2)
        (OUT/'scenario.json').write_text(json.dumps(result,indent=2)+'\n')
        browser.close()
