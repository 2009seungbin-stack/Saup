# Phase 11B verification record

Each result below is bound to the exact source SHA it executed on. Later commits (including this documentation commit)
need their own same-SHA runs; see the PR and Actions for those. No production deployment, real marketplace action or real
money movement occurred in any run.

## Starting state (2026-09-26)

- `main` = `77f5589c3ed4473cc8bca315e9e416cde162e7a0`; PR #4 (Phase 11A) open at `713929a46f81bc566f3d753cdce0877a60d64aac`
  (tree `ff6bed3839caa1f5dbcf208561912d7b8fd06123`), both as recorded in the handoff.
- Remote `feat/phase11b-marketplace-cancellation` pointed at `713929a` with no Phase 11B commits. No `Saup_Phase11B.*`
  patch/report/package existed on this machine → Phase 11B reconstructed from the specification.
- Baseline on this machine at `713929a` (Windows, Python 3.12.13): 246 ordinary passed, 8 service cases deselected — equal to
  the recorded Phase 11A count.

## TESTED — source `f8397c9e97cf9ef94b7af418f5e8441e7fdc54ec` (PR #5 head, base `77f5589`)

Verification run **36243250856** (backend + frontend) SUCCESS; Docker/Chromium acceptance run **36243250859** SUCCESS.

| Check | Executed result |
|---|---|
| Python 3.12.14 compileall | PASS |
| Ordinary application/API/migration/fixture tests | 323 passed; 0 failed / 0 errors / 0 skipped |
| Real PostgreSQL 16 integration | 11 passed (6 existing + 5 Phase 11B races); 0 failed/error/skipped |
| Real Redis 7 integration | 2 passed; 0 failed/error/skipped |
| Distinct backend cases | 336 |
| Statement coverage (ordinary suite) | 3251 / 3549 = 91.60326852634545% |
| Synthetic SQLite manual-evidence and demo-provider flows | PASS |
| npm ci / typecheck / Next production build | PASS / PASS / PASS |
| Docker image build, Compose start, Alembic through 0004, same-origin readiness | PASS |
| Real Chromium acceptance | 11 passed (7 supplier + 2 Phase 11A + 2 Phase 11B); 0 failed/error/skipped |
| PostgreSQL / Redis / API / worker / web normal restart | durable snapshot identical before/after (schema, accounts, orders, counts, balanced journals, journal count, all resolution records) |

Artifact checks performed after download (not only the green badge): every `source-sha`/`source_commit_sha` equals
`f8397c9`; backend source clean before/after with empty tracked diff; acceptance `source-status` empty before/after;
`source.zip` file list and sampled file hashes equal `git archive f8397c9`. The frontend tracked diff is only the
Next-generated `apps/web/next-env.d.ts` (retained, not concealed).

Acceptance business state after restart: schema `0004`; 2 refund evidence, 2 statements (one `ZERO_SELLER_SETTLEMENT`, one
`UNSUPPORTED_RESIDUAL_SETTLEMENT` with retained fee 700), 1 reconciliation. The reconciled order is Order `CANCELLED`,
SupplierOrder `CANCELLED`, Payment `SUCCEEDED`, Reservation `SPENT`, no shipment. The residual order stays
`CANCEL_REQUESTED`. `refund.execute` job count 0. All journals balanced.

Artifacts (retention 14 days for acceptance):

| Artifact | ID | Digest |
|---|---|---|
| phase10-backend-36243250856 | 10906112494 | sha256:5ae25ae8100ccfc4cef1769d6c217a2f48e08f1b71412353a46df6952f8c4b78 |
| phase10-frontend-36243250856 | 10906293536 | sha256:6d1eedfe91bb8c068d80fb284126d37eca64281be1ab0d79b75b8f443394e0a9 |
| phase10-acceptance-source-36243250859 | 10906822650 | sha256:4da6fbeb9ef72c4d423c2a7979983d6f622235ab233201e6d175a746e9d14236 |
| phase10-docker-browser-acceptance-36243250859 | 10905903234 | sha256:2509e57cab2b89249899d5c1b04a52ce14dd5adbc2c62f1a6e0b0c18634c0f9a |

## Local pre-push evidence (not CI evidence)

Uncommitted tree equal to `f8397c9` except the verify-runner UTF-8 fix and docs; Windows, Python 3.12.13, disposable local
PostgreSQL 16.4 and Redis 5.0.14: 323 + 11 + 2 passed, coverage 3251/3549. The new PostgreSQL race tests were repeated six
times locally without failure. Docker/Chromium were not run locally (no Docker on that machine).

## Failures found and fixed during development

- Detail view reported `READY_FOR_COMPLETION` after an out-of-band identity/discount change although completion correctly
  refused. Fixed by binding recorded evidence to its snapshot hash and running the same record check in statement
  recording, completion and the view.
- `scripts/verify_phase10.py` crashed on Windows when decoding a `git diff` containing Korean text with the ANSI codepage;
  it now decodes UTF-8 explicitly. Check steps were unaffected; CI (Linux) was not affected.
- Test-helper defects (payloads built from an already-blocked view; over-broad job assertion) were fixed in tests only.

## NOT TESTED / BLOCKED

NOT TESTED: Firefox/WebKit/mobile, load/chaos, backup/restore, production HTTPS, real marketplace documents.
BLOCKED: official marketplace/payment access, real refund receipts and statement formats; `REAL_PAYMENTS_ENABLED` stays off.
