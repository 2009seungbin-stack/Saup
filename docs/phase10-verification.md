# Phase 10 verification — Docker/browser acceptance follow-up

## Source identity and interpretation

Repository `2009seungbin-stack/Saup`; PR #2 was merged on 2026-09-26 at `3983ca576d63eccd47d722457d1245c3e20c0fd6`. See `phase10-main-merge.md` for the final pre-merge head and separately executed main CI. The checkpoints below remain historical evidence for their stated SHAs, not proof that later checks ran. No production deployment or real money movement is asserted. Executable code and migration history remain authoritative.

The checkpoint below was executed before this documentation commit. Later commits, including documentation changes, require their own same-SHA Actions artifacts. Never combine results for different SHAs and call them one source-matched success.

## TESTED — 2026-09-26 checkpoint

Source: `b6dae8c1bdf4491b00c18d4e83aed49de2549693`.

Verification run: **36207399192**; backend and frontend **SUCCESS**.
Application Docker/Chromium acceptance run: **36207399204**, **SUCCESS**.

| Check | Executed result |
|---|---|
| Python 3.12 compileall | PASS |
| Ordinary application/API/migration/fixture tests | 204 passed; zero failed/error/skipped |
| Real PostgreSQL 16 integration | 3 passed; zero failed/error/skipped |
| Real Redis 7 integration | 2 passed; zero failed/error/skipped |
| Actual Chromium UI acceptance | 7 passed; zero failed/error/skipped |
| Distinct selected pytest cases | 216 passed |
| Ordinary suite statement coverage | 90.60379918588873% (2,671 / 2,948 statements) |
| Temporary SQLite synthetic paths | manual evidence and demo provider both PASS |
| npm ci / typecheck / Next production build | PASS / PASS / PASS |
| Backend/web application Docker image builds | PASS |
| Compose init, Alembic 0002, startup and same-origin readiness | PASS |
| PostgreSQL 17 / Redis 7 / application normal restart persistence | PASS |

Five service cases are deselected from the ordinary suite and actually selected in the separate PostgreSQL/Redis gates. Browser tests are separately selected, not silently skipped. Coverage is Python statement coverage, not branch/frontend coverage or financial-correctness probability. The base verifier does not run Docker/browser checks: its NOT_TESTED fields are supplemented by the separate acceptance artifact, not edited into false success.

The manual browser transaction used real UI login, two demo orders, eligible selection, batch creation, repeated downloads, explicit send, mixed acceptance/rejection, local synthetic proof hashing, operator evidence registration, separate admin confirmation and tracking import. Focused negative cases use real authenticated HTTP for setup; no HTTP mocking or direct order/payment/shipment state mutation. The second completed path uses a clearly labelled DEMO_PROVIDER. No real transfer or live marketplace request occurred.

The final synthetic PostgreSQL state has 6 orders: 2 SHIPPED, 1 REJECTED, 1 MANUAL_REVIEW, 2 CANCELLED. Exactly 2 payments, 2 shipments, 1 manual evidence and 1 admin confirmation remain. Each shipped order has one DONE marketplace shipment job. Three journals are balanced. These durable records and all account balances are identical before/after restarting DB, Redis, API, worker and web. This is normal restart persistence, not backup restore or chaos testing.

Artifacts retain exact source SHA/archive, logs/JUnit, source manifests/status/diff, coverage, browser version/screenshots, synthetic XLSX/hash evidence and safe before/after business snapshots. Next can generate `next-env.d.ts`; its tracked diff is retained, not concealed as a pristine frontend tree. Acceptance never uploads .env, traces, HAR or session storage. Artifact retention is 14 days for the acceptance workflow.

## Actual failures found and corrected

Run 36206624554 on `7d58063dfbc32277b78f7262bcb4cad37191beb0`: Docker/start/install passed but browser results were **4 passed, 3 failed**. The runner clicked before catalog hydration and selected dropdowns by an unsuitable exact label; waits and accessible combobox selectors were corrected without relaxing business/security assertions. Downstream restart checks were skipped on that failed run, not counted as passed.

Run 36207008779 on `029799c82df36d4e910dd33176e5929fd02cc43f`: Docker/browser/restart **passed**, but the separate verification run 36207008783 had one existing login-limit test failure (203 passed / 1 failed). Eleven real-time login attempts straddled a minute boundary. The test now freezes only the limiter clock and explicitly checks reset in the next minute; the actual rate-limit policy and code were not weakened.

Code review also found the operator's evidence panel displayed waiting after admin confirmation. It now distinguishes confirmed evidence, with a browser regression assertion. Initial failed-test fixture repr could include disposable random test credentials; it is now redacted. That disposable project was torn down; the old failed artifacts were not silently deleted. Do not redistribute old raw failure logs as a sanitized report.

## Earlier provenance — not proof for later code

Source `4fb92d9377326395bf0182cb0996d4d38cc20213`, run 36152696667: 183 ordinary + 3 PostgreSQL + 2 Redis = 188 passed, coverage 90.60379918588873%, npm ci/typecheck/build passed. Application Docker/browser checks were then not executed.

The first application Docker-only checkpoint was run 36206038974 on `58afca6ca9989eaee46854d0999192813c53d979`: actual image builds, Compose start/proxy and application restart passed. It did not include the later browser/business persistence assertions. The initial Phase 10/source-import/local history remains in `history/2026-09-25-phase10-verification.md`.

## NOT TESTED / BLOCKED / FUTURE

Not established: production deployment/migration, Firefox/WebKit/mobile, production TLS/MFA/CSP, load/network-partition/chaos tests, backup restore/PITR, key rotation/retention and a real supplier workbook/receipt. Actual supplier authorization, approved destinations/confirmed deposits, official marketplace access and a certified live payment connector remain external blockers. `REAL_PAYMENTS_ENABLED=true` remains blocked. No production automation rate is claimed.

Evidence correction, paid-cancellation refund reconciliation and revised supplier terms require future typed resolution commands, not a universal force-state/payment API. No new commerce feature or migration was introduced by this acceptance follow-up.

## Reproduce

Use `python -m scripts.verify_phase10 --mode backend --require-services --output reports/phase10/backend` with disposable TEST_POSTGRES_URL/TEST_REDIS_URL, and `--mode frontend` for the locked frontend build. Follow `phase10-acceptance.md` for actual Docker/Chromium, or execute the committed read-only Actions workflows. Missing infrastructure, zero selected cases or skipped production-critical cases fail their gate.
