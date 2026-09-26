# Production gates — explicit evidence, not inferred success

## Gate status source

Use `phase10-verification.md` and the same source commit's Actions artifacts. `scripts/verify_phase10.py --require-services` fails for missing/skipped PostgreSQL or Redis gates; compile/unit/coverage/PG/Redis/frontend build have distinct results. Lockfile bootstrap success is not application CI success. Main merge, Docker/browser tests and live provider acceptance must never be inferred.

## Supplier operational gate

The implemented Phase 10 synthetic path must cover batch generation/export/send, complete mixed supplier response, exact frozen economics, payment preparation/evidence+admin confirmation or explicit demo provider, valid tracking import, and exactly one marketplace shipment job on replay. Run `python -m scripts.demo_supplier_operations --output reports/phase10/synthetic.json`.

Before a real pilot, validate one authorized supplier's real profile/header/identifier conventions, acceptance and cancellation evidence rules, destination binding, supplier-specific deposit balances, cutoff and inventory freshness. Agree secure delivery/retention, operator/admin separation, and exception escalation. Never seed synthetic cash or mark a demo provider as live. There is no blanket automation-rate claim.

## Migration gate

Backup first; run Alembic 0001→0002 against a disposable copy. Existing Excel supplier states become explicit review. Reconcile whether a file was sent/accepted before adopting it. No schema-v1 rewrite and no destructive populated downgrade: Phase 10 data blocks downgrade. Test restore rather than attempting to erase append-only evidence.

## Financial gate

REAL_PAYMENTS_ENABLED remains blocked without a certified live connector. Evidence is an attestation of a completed external action, not a transfer API. Destination/amount/reservation/cash/AUTO/DAILY limits remain mandatory; UNKNOWN remains unknown. Confirmed supplier cancellation after payment does not confirm a refund or restore spendable funds. Wrong evidence, revised terms, and financial cancellation require dedicated reconciliation, not force paid/state buttons.

## Executed acceptance checkpoint

Source `b6dae8c1bdf4491b00c18d4e83aed49de2549693` passed application Docker image builds, Compose init/migrations/start, actual Chromium UI/security supplier paths, and normal PostgreSQL/Redis/application restart persistence in run 36207399204. Ordinary/Python 3.12/PostgreSQL 16/Redis/frontend gates passed in run 36207399192. Compose acceptance used PostgreSQL 17. This is synthetic acceptance, not a production pilot or proof of disaster recovery. Read the source-matched artifacts for later commits.

## Remaining production checks

Cross-browser/mobile acceptance and production HTTPS; failure/load tests and backup restore drill; supplier spreadsheet review; dependency/security review and least-privilege DB roles; secrets management/key rotation/retention/MFA; incident/alerting/monitoring. Existing backend/frontend source and passing isolated tests do not close these gates.

## External dependencies

Coupang, Temu and AliExpress account/API approval and official contracts, authorized supplier processes, and a certified live payment/deposit provider. The application must explicitly block missing provider access and never invent endpoints or automate browser banking.


## Phase 11A bounded review resolution

Phase 11A requires migration 0003 and coordinated application version rollout: old binaries do not understand evidence correction holds. Nonempty new history or correction reviews block downgrade. Partial/changed-allocation/post-shipment recoveries and customer refund completion remain blocked. See phase11-review-resolution.md; only current-SHA executed artifacts qualify as verification.

## Phase 11B marketplace cancellation reconciliation

Requires migration 0004 and a coordinated rollout of API/worker/web: older binaries neither understand the late-line hold nor the new reviews. Downgrade is refused when Phase 11B rows or residual/late-line reviews exist. Gates still open: real marketplace refund/statement formats and official API access, multi-line parent orders, partial/fee-adjusted cancellations, post-shipment cancellations, evidence storage/retention/key rotation, backup/restore drills. Only current-SHA executed artifacts qualify as verification.
