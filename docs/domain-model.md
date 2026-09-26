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


## Phase 10 additions (runtime: 36 tables; initial snapshot: 28)

`SupplierOrderIntent` is append-only and freezes supplier/economics/SKU/quantity/address hash/destination hash; it does not store plaintext PII. `SupplierOrderBatch` freezes profile version/mapping and an encrypted XLSX plus SHA-256, generation/export/send/ack timestamps and actors. `SupplierOrderBatchItem` joins supplier orders through same-supplier composite FKs and a partial unique active membership index; historical invalidated memberships remain relational.

`SupplierBatchAcknowledgement` is an immutable complete response bound to a payload hash. Items separately retain accepted/rejected/changed-term decisions. `SupplierPaymentEvidence` is immutable exact allocation/destination/reference/hash evidence, unique per payment and supplier receipt reference. `SupplierPaymentConfirmation` is a separate immutable admin attestation, unique per evidence/payment. Neither is a live payment connector. `SupplierCancellation` records request, origin state, confirmation reference/hash and financial-review state. `OperationalIntervention` is immutable, unique by business key and categorized for future measurement.

Review now supports OPEN/ACKNOWLEDGED/RESOLVED plus resolution_code/resolved_by/resolved_at. Typed commands resolve only their satisfied issue; audit history preserves reopening and previous resolution. Acknowledgement remains "seen", not business resolution. The global treasury lock is acquired before supplier/order/payment changes; database unique constraints prevent duplicate memberships, payments, receipts, confirmations, shipments and jobs.

Migration 0002 never edits frozen schema_v1 or 0001. Existing Excel supplier orders are explicitly held for legacy review; populated downgrade is blocked. See supplier-excel/payment-safety for recovery and privacy behavior.


## Phase 11A bounded review resolution

Phase 11A raises runtime metadata to 40 tables and adds four immutable history entities in schema_v3/migration 0003: SupplierEvidenceRevision, SupplierEvidenceConfirmationBinding, SupplierCancellationRecovery and ReviewResolution. Old schemas and journals remain unchanged. See phase11-review-resolution.md.
