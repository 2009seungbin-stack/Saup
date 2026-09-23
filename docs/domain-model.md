# Domain model

PostgreSQL is the intended source of truth. SQLite is a serial test/development target only. The initial schema contains 28 tables; later migrations must not silently alter the frozen `schema_v1.py` snapshot.

## Catalog and suppliers

`Product` holds internal SKU, supplier-provided category/origin/tax classification/weight/grade/unit, season state and batch/passport JSON. `ProductVariant` preserves a distinct variant identity. `SupplierProduct` maps supplier SKU to product, retains current cost/shipping/stock/freshness and links to append-only `SupplierPriceHistory`. Critical metadata changes do not overwrite approved origin/grade/tax/weight; they pause sales and create a review. Unknown tax classification blocks ordering.

`MarketplaceListing` has channel, price, configured fee rate, claim/promotion allowances, desired state, remotely confirmed state and revision. Sample marketplace fee rates are synthetic settings, not verified provider tariffs. Seasonal state is checked when accepting orders; an automatic season calendar is not implemented.

`Supplier` has active mode, cutoff, claim days and a destination fingerprint with two-person approval metadata. This is not a real bank account registry or live payout credential store. Official providers must later bind verified destination identifiers to the approved fingerprint.

## Orders and fulfillment

An `Order` is one normalized **fulfillment line**, uniquely identified by `(marketplace, external_id, external_line_id)`. A parent marketplace order may contain multiple such lines. Aggregated parent cancellations, split shipments, shipping-fee allocation and parent-level refunds remain a production gate.

An order stores original monetary inputs, frozen accepted supplier cost, fee, encrypted original/validated address, cancellation flag, correlation ID and timestamps. Source address is never rewritten. Repeated external identities require the exact same payload hash; changed payloads create a conflict instead of mutating an existing fulfillment request.

There is at most one `SupplierOrder`, `Payment`, cash `Reservation` and `Shipment` per fulfillment line in this version. This intentionally excludes reshipments and partial shipments until they receive explicit models and tests.

## Financial and operational records

`Account` balances are materialized by balanced `Journal`/`Posting` transactions. Cash reservations do not themselves create income or spend cash. Claims, refunds and settlements have separate records and business keys. Supplier accepted compensation and confirmed supplier recovery are separate fields.

`Job` is the transactional outbox/durable queue; `Command` provides a reusable payload-bound command key primitive. `ExternalRecord` stores simulated provider receipts in separate transactions. `ImportBatch` retains encrypted upload content, content hash, profile snapshot/version and counters. `Review` is the unified exception queue; acknowledgment is not a business resolution. `AuditEvent` is append-only.

`User` and hashed `AuthSession` implement local RBAC. `Heartbeat` tracks worker readiness. `Experiment` stores explicit sample/window/method and manual input metrics. No AI financial decisions or unsupported consumer quality claims are produced.
