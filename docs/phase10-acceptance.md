# Phase 10 — Docker and browser acceptance

## Scope

This acceptance layer extends Phase 10; it is not a new commerce architecture,
real supplier integration, production deployment, or live payment certification.
PR #2 remains the review destination. Use a source-matched Actions run, not this
file's presence, to determine whether a particular commit passed.

`.github/workflows/acceptance.yml` builds the actual backend and frontend images,
runs the existing Compose PostgreSQL 17/Redis 7/API/worker/web/init services,
checks same-origin readiness, and drives the production Next build using a real
Chromium browser. There is no HTTP route mocking, in-memory replacement database,
or direct mutation of order/payment/shipment states for the transaction tests.
Marketplace responses and payment-provider responses remain explicitly DEMO.

## Browser scenarios

The seven selected cases cover the UI-created mixed supplier batch and actual
XLSX downloads, send attestation/replay/conflict, mixed supplier acceptance,
operator evidence registration versus separate admin confirmation, paid tracking
upload/replay, viewer read-only/PII restrictions, CSRF/Origin/session-cookie
contracts, supplier-reported price changes, pre-send versus post-send cancellation,
and the separately labelled DEMO_PROVIDER path. The normal manual transaction is
UI-driven; focused negative cases use authenticated HTTP only to arrange their
orders/batches. Test setup is synthetic, not acceptance by a real supplier.

The final verifier reads PostgreSQL to assert balanced journals, completed shipment
jobs and blocked lines without payments. It compares IDs, counts, money balances,
reservations and journal counts before and after restarting PostgreSQL, Redis,
API, worker and web without deleting volumes. This checks normal restart
persistence, not point-in-time recovery, network-partition safety or load capacity.

## Guarded synthetic fixture

`scripts/acceptance_fixture.py` is a CLI, not a public API. It requires both
`SAUP_ACCEPTANCE=1` and a `saup-acceptance-*` Compose project, demo mode, live
payments disabled and the expected disposable PostgreSQL address. It refuses
existing orders or non-pristine suppliers. It only changes the existing synthetic
supplier to Excel mode and creates random viewer/operator credentials; production
business state is never repaired by this fixture. Ordinary tests verify these
refusals and reject incomplete or duplicated verification outcomes.

Credentials enter the fixture via stdin. The fixture representation is redacted
in pytest failures. No .env, session storage, traces, HAR or bank screenshots are
uploaded. Screenshots and downloaded XLSX files contain only synthetic data.
Artifacts have a 14-day retention period. The test project and its volumes are
removed in an always-run cleanup step.

## Reproduce on a clean disposable checkout

Do not point these commands at an existing operator workspace or real database.
The demo's localhost ports must be free; stop nothing belonging to another project.

```bash
export COMPOSE_PROJECT_NAME=saup-acceptance-local-$(date +%s)
python scripts/bootstrap.py > /dev/null
# Fresh random secrets are written to .env; existing .env is never overwritten.
docker compose build --pull
docker compose up -d --wait --wait-timeout 180
python -m pip install -r tests_browser/requirements.txt
python -m playwright install --with-deps chromium
mkdir -p reports/acceptance
python -m pytest -q tests_browser --junitxml=reports/acceptance/browser-junit.xml
docker compose exec -T -e SAUP_ACCEPTANCE=1 \
  -e COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME" api \
  python -m scripts.acceptance_fixture verify
# Only remove this disposable test project's volumes after preserving evidence.
docker compose down --volumes --remove-orphans
```

Use the workflow for the full before/after restart comparison and source archive.
The ordinary suite does not silently skip optional browser cases: this directory
is selected explicitly, and acceptance rejects zero/incomplete/skipped results.

## Evidence and limitations

See `phase10-verification.md` for dated executed checkpoints. Artifacts include
source SHA and archive, build/install logs, JUnit, browser version, synthetic file
hashes, safe business snapshots, screenshots and service/restart diagnostics.
A job failure is a failed gate even when preceding Docker steps succeeded.

Not established: Firefox/WebKit or mobile coverage, visual-design approval,
production HTTPS/MFA, a real supplier's workbook, real payment evidence validity,
load/chaos tests, disaster recovery or production migration. Paid-cancellation
refund reconciliation, revised terms and evidence correction stay guarded review
cases until dedicated resolution commands exist. No production automation rate
is claimed.
