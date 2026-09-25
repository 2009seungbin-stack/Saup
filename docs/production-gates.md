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

## Remaining production checks

Docker clean build/start/restart; role/CSRF/ack/proof/download browser E2E; failure/load tests and restore drill; supplier spreadsheet review; dependency/security review and least-privilege DB roles; secrets management/key rotation/retention/MFA; incident/alerting/monitoring. Existing backend/frontend source and passing isolated tests do not close these gates.

## External dependencies

Coupang, Temu and AliExpress account/API approval and official contracts, authorized supplier processes, and a certified live payment/deposit provider. The application must explicitly block missing provider access and never invent endpoints or automate browser banking.
