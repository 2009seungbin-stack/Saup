"""Real Chromium + existing Docker API/worker/PostgreSQL. No HTTP mocking.

This suite is intentionally outside tests/: invoke it explicitly. Missing Docker
or fixture authorization is a failure, never a production-critical skip.
"""
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
from collections import deque
import pytest
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'reports' / 'acceptance'
ORIGIN = 'http://localhost:3000'
REDACTIONS = set()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Playwright ARIA diagnostics can include password-field values."""
    outcome = yield
    report = outcome.get_result()
    if report.failed:
        safe = report.longreprtext
        for secret in REDACTIONS:
            safe = safe.replace(secret, '[REDACTED_DISPOSABLE_TEST_SECRET]')
        report.longrepr = safe
        report.sections = [(name, _redact(content)) for name, content in report.sections]


def _redact(value):
    for secret in REDACTIONS:
        value = value.replace(secret, '[REDACTED_DISPOSABLE_TEST_SECRET]')
    return value


@pytest.fixture(scope='session')
def login_budget():
    """Pace fresh test sessions without changing/bypassing the real limiter."""
    attempts = deque()
    def acquire():
        while attempts and time.monotonic() - attempts[0] >= 61:
            attempts.popleft()
        if len(attempts) >= 8:
            time.sleep(max(0, 61 - (time.monotonic() - attempts[0])))
            while attempts and time.monotonic() - attempts[0] >= 61:
                attempts.popleft()
        attempts.append(time.monotonic())
    return acquire


class RedactedFixture(dict):
    def __repr__(self):
        return '<isolated synthetic fixture; credentials redacted>'


def docker_fixture(operation, payload=None):
    project = os.environ.get('COMPOSE_PROJECT_NAME', '')
    if not project.startswith('saup-acceptance-'):
        raise RuntimeError('Run only in a disposable saup-acceptance-* Compose project')
    command = ['docker', 'compose', 'exec', '-T', '-e', 'SAUP_ACCEPTANCE=1',
               '-e', f'COMPOSE_PROJECT_NAME={project}', 'api', 'python', '-m',
               'scripts.acceptance_fixture', operation]
    result = subprocess.run(command, cwd=ROOT, input=json.dumps(payload) if payload else '',
                            capture_output=True, text=True, timeout=45)
    if result.returncode:
        # Do not put credentials, stdin or arbitrary server errors in test artifacts.
        raise RuntimeError(f'Isolated acceptance fixture {operation} failed: exit {result.returncode}')
    return json.loads(result.stdout)


@pytest.fixture(scope='session')
def fixture_data():
    REPORTS.mkdir(parents=True, exist_ok=True)
    credentials = {f'{role}_password': secrets.token_urlsafe(24) for role in ('operator', 'viewer')}
    data = docker_fixture('seed', credentials)
    config = dict(line.split('=', 1) for line in (ROOT / '.env').read_text().splitlines() if '=' in line and not line.startswith('#'))
    REDACTIONS.update(credentials.values())
    REDACTIONS.add(config['ADMIN_PASSWORD'])
    return RedactedFixture({**data, 'credentials': {'operator': ('e2e-operator', credentials['operator_password']),
                                   'viewer': ('e2e-viewer', credentials['viewer_password']),
                                   'admin': (config['ADMIN_USERNAME'], config['ADMIN_PASSWORD'])}})


@pytest.fixture(scope='session')
def browser():
    with sync_playwright() as pw:
        instance = pw.chromium.launch()
        (REPORTS / 'browser-version.txt').write_text(instance.version + '\n')
        yield instance
        instance.close()


@pytest.fixture
def pages(browser, fixture_data, request, login_budget):
    opened = []
    contexts = {}
    errors = []
    def open_page(role='operator'):
        if role not in contexts:
            login_budget()
            ctx = browser.new_context(base_url=ORIGIN, locale='ko-KR', viewport={'width': 1440, 'height': 1100}, accept_downloads=True)
            page = ctx.new_page(); page.goto('/')
            username, password = fixture_data['credentials'][role]
            page.get_by_label('아이디', exact=True).fill(username)
            page.get_by_label('비밀번호', exact=True).fill(password)
            with page.expect_response(lambda r: r.url.endswith('/auth/login') and r.request.method == 'POST') as response:
                page.get_by_role('button', name='로그인', exact=True).click()
            if response.value.status != 200:
                page.get_by_label('비밀번호', exact=True).fill('')
                ctx.close()
                raise AssertionError(f'Acceptance login failed: HTTP {response.value.status}')
            expect(page.get_by_role('heading', name='운영 현황', exact=True)).to_be_visible(timeout=15000)
            contexts[role] = ctx
        else:
            page = contexts[role].new_page(); page.goto('/')
            expect(page.get_by_role('heading', name='운영 현황', exact=True)).to_be_visible(timeout=15000)
        expect(page.locator('.panel tbody tr').first).to_be_visible(timeout=15000)
        page.on('pageerror', lambda _error: errors.append('UNCAUGHT_BROWSER_ERROR'))
        opened.append((role, page)); return page
    yield open_page
    for index, (role, page) in enumerate(opened):
        # No traces/HAR/storage state: these could include auth cookies/passwords.
        page.screenshot(path=str(REPORTS / f'{request.node.name}-{role}-{index}.png'), full_page=True,
                        mask=[page.locator('input[type=password]')])
    for ctx in contexts.values(): ctx.close()
    assert not errors, 'Uncaught browser JavaScript errors'
