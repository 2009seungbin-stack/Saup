# Marketplace integration status

| Provider | Current operational adapter | Live status | Missing |
|---|---|---|---|
| Coupang | Persistent, explicitly labelled simulator | BLOCKED_BY_CREDENTIALS | Authorized seller credentials, official endpoint/permission validation, connector code and contract fixtures |
| Temu | Persistent, explicitly labelled simulator | BLOCKED_BY_PROVIDER_ACCESS | Local Seller / partner permissions, account-specific documented scopes, connector code |
| AliExpress Korea | Persistent simulator and secret-isolated OAuth/config model | BLOCKED_BY_PROVIDER_ACCESS | Verified Korea seller permissions, authorized OAuth flow and documented connector implementation |
| Supplier API | Simulator in demo; Excel otherwise | BLOCKED_BY_SUPPLIER_API | Supplier-provided documented endpoint, credentials and operational acknowledgement rules |
| Payments | Persistent simulator; manual adapter blocks | BLOCKED_BY_PROVIDER_ACCESS | Approved official payout/billing/deposit provider and verified destination binding |

No production marketplace URL, request signature, permission scope or undocumented endpoint is invented. Credentials alone do not unlock missing code. `ProviderConfig.readiness()` still returns BLOCKED_BY_CONNECTOR_IMPLEMENTATION after credentials and documentation metadata are filled in.

The port exposes capability metadata and operation names for catalog, price/stock, orders, tracking, claims and settlement. Support is not assumed equal across marketplaces. Production adapters advertise no implemented operations and fail explicitly. Simulators are not live capability evidence. The shared generic `invoke` contract is implemented; complete provider-specific typed request/response schemas are a next-step deliverable.

The demo stores only payload hashes and safe receipts in `ExternalRecord`, not plaintext provider payloads. A separate committed receipt survives an application failure. Fault injection (`timeout_before`/`timeout_after`) is test-only and never represents a production endpoint.

## Enablement procedure

Obtain official account-specific API documentation and authorization. Record exact supported operations and response schemas. Implement signed requests, timeouts, rate-limit/backoff handling, pagination, status lookups and redacted errors against those documents. Add recorded/sanitized or official sandbox fixtures and contract tests. Validate external idempotency guarantees and expiry. Start with read-only synchronization, then shadow comparison and tightly capped supervised writes. Keep REAL_PAYMENTS_ENABLED disabled until all financial gates pass.

## Verified technical references consulted

Implementation decisions were checked against FastAPI's container documentation, SQLAlchemy's versioning documentation, PostgreSQL SELECT/SKIP LOCKED documentation and openpyxl documentation. Next.js's official 2026-09-22 security update lists 16.3.6 as patched; that version is declared in `apps/web/package.json`. No claim is made that the uninstalled frontend build passed.

- https://fastapi.tiangolo.com/deployment/docker/
- https://docs.sqlalchemy.org/en/20/orm/versioning.html
- https://www.postgresql.org/docs/current/sql-select.html
- https://openpyxl.readthedocs.io/en/stable/
- https://nextjs.org/blog/nextjs-security-update-september-22-2026

These are technical references, not evidence of authorized marketplace access.
