# Deployment and operations

## Local topology

Compose starts PostgreSQL, Redis, an initialization service, FastAPI, a DB-queue worker and Next.js. Redis is used for distributed rate limiting; the PostgreSQL queue is the explicitly selected robust alternative to Celery, keeping job enqueue and business state in one transaction.

API health checks are separate: `/health` is process liveness; `/ready` reports actual DB, Redis and recent worker heartbeat. A missing heartbeat is not reported ready. Containers bind web/API host ports to 127.0.0.1; PostgreSQL/Redis are not published.

Backend and web images run as non-root users. Initialization runs migrations then seeds only synthetic demo entities. Compose is not a production deployment manifest; production mode intentionally refuses the demo seed. There is no hosted deployment in this delivery.

## Worker operations

Jobs have a unique business key, payload, due time, bounded attempts and lease token. Claim uses PostgreSQL FOR UPDATE SKIP LOCKED. Completion requires the same lease token. Retryable transient failures back off exponentially; uncertain money results do not trigger replay. Exhausted/fatal jobs become DEAD and enter the review queue. Non-financial safe jobs can be explicitly replayed; financial/order uncertainty requires reconciliation.

```bash
python -m apps.worker.main --once
python -m apps.worker.main --drain
python -m apps.worker.main
```

`--drain` processes currently due jobs; it does not advance time, wait out backoff or prove all queued work completed. Long-running provider calls must have timeouts shorter than the lease and provider-specific idempotency. There is no live provider implementation yet. Rate/circuit-breaker patterns for actual HTTP connectors must be added and tested against their documented behavior.

Maintenance records heartbeat, pauses stale/unknown stock and applies cash/rolling-claim guards. Console notification jobs emit redacted structured events. Email/webhook delivery transports, external monitoring, alert escalation and per-provider sync-status histories remain incomplete.

## Backup/restore procedure to validate

Create encrypted PostgreSQL backups with your authorized infrastructure tools and restricted database credentials. Preserve schema revision, source commit/package hash and separately managed encryption keys. Store backups outside the database host under access control. Restore into an isolated environment with all integrations and real payments disabled. Compare journal balance/materialized account balances, reservation totals, order/payment uniqueness, pending outbox leases and decryption of approved synthetic samples. Do not resume live dispatch until uncertain external actions are reconciled against provider receipts.

A backup/restore exercise was not performed in this environment. No restore SLA/RPO/RTO is claimed. Follow the organization-approved backup product's official procedures; this document is an operational checklist, not an executed backup.

## Dependency/build gate

Python behavior was tested with the installed environment recorded in reports. The requested runtime target remains Python >=3.12; this session ran 3.13.5. Next config pins 16.3.6; other frontend dependencies use declared compatible ranges. A complete audited lockfile is not generated because registry network/DNS was unavailable. The web Dockerfile therefore uses npm install, with an explicit release gate to replace it with npm ci after resolving and reviewing the lockfile.

Full Compose startup, Docker image builds, Next dependency-resolved TypeScript checks, SSR/build behavior, browser end-to-end tests, PostgreSQL concurrency and Redis operation must be run before production. The tests/commands exist where feasible; skipped checks are not passes.
