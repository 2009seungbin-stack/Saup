# Saup architecture

Status: implementation in progress; not approved for live commerce or real money.

## Source and scope

Based on the supplied Saup_95pct_Commerce_Automation_Prompt.md. The repository was confirmed empty before initialization. Ordinary-transaction automation of 95% is a target, not a measured achievement.

## Design decisions before implementation

1. PostgreSQL is authoritative. Python 3.12+, FastAPI, SQLAlchemy 2 and Alembic manage the application. SQLite is supported only for deterministic local tests.
2. Domain rules use integer KRW and Decimal rates, explicit order transitions, immutable histories and balanced ledger postings. Supplier-specific deposits are never available to another supplier.
3. Commands lock order and treasury rows, use stable business idempotency keys and enforce uniqueness in the database. A key reused with changed parameters is rejected.
4. External side effects are driven by a transactional, PostgreSQL-backed outbox. Workers claim jobs with SKIP LOCKED, bounded retries and dead-letter/review handling. Redis handles distributed rate limits. This durable job queue is the selected alternative to Celery, avoiding a DB/broker dual-write gap.
5. Marketplace, supplier, payment and notification ports isolate all external systems. Mock mode is explicitly labelled. Production operations fail with BLOCKED_BY_CREDENTIALS or BLOCKED_BY_PROVIDER_ACCESS until documented, account-authorized access exists. No undocumented marketplace endpoints or banking browser automation.
6. Excel profiles are supplier-specific. Imports are bounded, validate every row, reject formulas and duplicates, preserve text identifiers and place invalid rows in a durable review queue. Exports do not claim that a supplier has accepted an order.
7. Original addresses are encrypted and never rewritten. Read models exclude PII. Admin sessions are revocable, HttpOnly and CSRF-protected with role checks and append-only audit records.
8. A listing's local desired pause and remotely confirmed pause are separate. A failed remote pause is an unresolved incident, not a claim that marketplace sales stopped.
9. The Next.js console reads actual API/DB state and distinguishes demo data from live data. Real payment code is disabled by default and is not replaced by fake success responses.

## Phases and acceptance gates

- Phase 1: monorepo, configuration, database, migrations, API/auth, worker, Docker, console, health and audit.
- Phase 2: catalog, suppliers, listings, explicit order state machine, history, treasury, claims and settlements.
- Phase 3: profile-based price import, order export and shipment import with error isolation.
- Phase 4: deterministic price/margin/risk/capacity, kill switches and review queue.
- Phase 5: adapter contracts, persistent demo implementations, explicit production blockers and contract tests.
- Phase 6: evidence/deadline checks, supplier response, bounded refunds, settlement reconciliation.
- Phase 7: manual-input discovery scoring and contribution-based experiments.
- Phase 8: authenticated operational dashboard, queue and transaction trail.
- Phase 9: failure tests, replay controls, retention, backup/restore and deployment documentation.

Each phase records its changes and test results in docs/implementation-status.md. Local tests are not evidence of production PostgreSQL concurrency, live provider access or 95% automation. Production remains gated on those validations.
