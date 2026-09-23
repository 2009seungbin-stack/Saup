# Saup architecture

Based on `docs/original-requirements.md`. 95% automation is a target, not a measured result.

## Decisions before coding

PostgreSQL is authoritative; adapters isolate marketplace, supplier, payment and notification systems. Money is integer KRW, rates Decimal. Explicit state transitions, database uniqueness and business idempotency keys protect transactions. Supplier-specific deposits are not available to other suppliers. Ledger entries are balanced and append-only.

The queue is a transactional PostgreSQL outbox with SKIP LOCKED, expiring leases, bounded retries and dead letters. Redis provides distributed rate limiting. This is the selected equivalent to Celery, avoiding a database/broker dual-write gap. No marketplace synchronization runs in HTTP handlers.

Original addresses are encrypted and never changed. Session tokens are hashed in the database; cookies are HttpOnly with CSRF checks and role-based authorization. No provider credentials are shipped. No live payment connector is implemented; the live flag fails at configuration validation.

A local listing pause is distinct from a remotely confirmed pause. A failed remote pause remains an unresolved incident; an unreachable marketplace cannot be guaranteed stopped.

Orders are normalized **fulfillment lines** with `(marketplace, external_order_id, external_line_id)` identity. Combined multi-line cancellation/refund routing remains a production integration gate. Demo fixtures contain synthetic data only.

## Sequenced implementation plan

1. Foundation: monorepo, configuration, frozen schema, migrations, auth, audit, health, queue, Docker.
2. Domain: products, suppliers, listings, orders, price history, treasury and ledgers.
3. Excel: mapping profiles, bounded price/shipment imports, errors, deterministic order exports.
4. Financial/risk: margin, stock freshness, cash capacity, payment tiers, kill switches.
5. Adapters: contracts, durable mocks, provider-access blockers; never invented endpoints.
6. Claims/settlement: evidence and deadline checks, supplier response, bounded refunds, reconciliation.
7. Discovery: manually sourced scores, provenance, profitable SKU experiments.
8. Console: authenticated operational UI driven by actual database/API state.
9. Hardening: failure/replay tests, retention, deployment and backup/restore instructions.

Each increment is implemented and checked locally. See `docs/implementation-status.md` for measured results, limitations and remaining gates. The schema snapshot `schema_v1.py` is frozen at this release; future changes require a new migration rather than editing that snapshot.
