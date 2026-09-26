# Supplier Excel operations · Phase 10

PostgreSQL is authoritative. Files, messages and operator statements are external inputs; none silently advances acceptance or moves money.

## Profiles and imports

`SupplierExcelProfile` retains supplier, version and deterministic mapping. Price and tracking imports retain their original profile/version snapshots and existing duplicate/formula/quarantine behavior. Identifiers remain text; lost leading zeroes are not guessed. Address validation never rewrites the original address. The sample fixture profile is synthetic, not approval of a real supplier format.

## Batch creation and export

`SupplierOrder` PENDING plus `SupplierOrderIntent` holds validated/reserved frozen economics, quantity, SKU and original-address hash. One `SupplierOrderBatch` contains one supplier/profile/version, 1–500 eligible orders, deterministic sorted membership and an encrypted frozen XLSX payload. Relational items have composite supplier FKs and a partial unique index on active supplier-order membership. A payload-bound idempotency key is required for creation.

Creation produces FILE_READY; download sets EXPORTED once and audits every PII access. Workbook text cells preserve leading zeroes and neutralize formula interpretation. Repeated download returns exactly the same bytes and SHA-256 even after a profile is edited. Plaintext files are not written to persistent application storage. General JSON responses contain neither address/phone nor ciphertext.

The legacy profile-wide Excel-mode exporter now returns `SUPPLIER_BATCH_REQUIRED`: create and export a batch instead. The demo-mode legacy exporter remains for existing demonstrations. This intentional compatibility change avoids an unauditable second supplier handoff path.

## Delivery and acknowledgement

`mark-sent` requires channel, bounded reference and the generated file hash. FILE_READY or EXPORTED can become SENT; downloading is not required to claim a false delivery. The operator must actually have delivered the file. Same metadata replay is idempotent; conflicting metadata is rejected.

A single final acknowledgement classifies **every batch member exactly once** as accepted or rejected. Mixed line outcomes are supported; incremental incomplete response fragments are deliberately rejected rather than guessed. The reference and immutable payload hash bind replay. Unknown/cross-batch/duplicate IDs fail. Reasons are typed: OUT_OF_STOCK, PRICE_CHANGED, SKU_NOT_FOUND, ORDER_NOT_ACCEPTED, DELIVERY_UNAVAILABLE, CUTOFF_EXCEEDED, OTHER.

Reported price/shipping/quantity/SKU/destination changes never overwrite the intent. Changed lines enter MANUAL_REVIEW and cannot pay. Relevant stock/SKU/terms failures pause internal listing intent with UNCONFIRMED remote status. Accepted same-SKU lines are rechecked after all decisions, so a relevant risk pause can block their payment too. Rejected lines do not pay and do not assume inventory is restocked.

## Payment and tracking

Batch policy is MANUAL_EVIDENCE or explicitly test/demo-only DEMO_PROVIDER. Accepted lines reuse existing validation, reservation, destination and limits. Manual evidence records exact payment/supplier/amount/bank-deposit allocation/destination/reference/hash. Separate admin confirmation, explicit money-moved attestation and a full recheck are required before accounting payment success. Evidence alone never pays. UNKNOWN cannot be converted into a manual retry.

Tracking XLSX can create shipment only for an accepted, paid, SHIPMENT_PENDING supplier order and an eligible noncancelled marketplace order. Creation updates the supplier state to SHIPPED and enqueues exactly one existing marketplace shipment update. Existing duplicate/conflicting tracking protections remain.

## Cancellation and recovery

Before batch: local cancellation releases reservation. Before send: invalidate the complete frozen file, retain historical membership and re-batch surviving orders; never silently rewrite a downloaded file. After send/acceptance: record CANCEL_PENDING and require explicit supplier cancellation. Money exposed by evidence, UNKNOWN/SENDING or success remains reserved/spent pending financial review, including after supplier cancellation is confirmed.

`revalidate` is admin-only original-term revalidation; it cannot change economics, revive cancelled orders, override unrelated risk pauses or clear UNKNOWN. `adopt-verified-unsent` is admin-only migration recovery with explicit verified-never-sent evidence and no payment/cancellation history. Legacy FILE_READY is not proof of being unsent.

## APIs and UI

Supplier batch POST/list/detail/file/mark-sent/acknowledge/cancel/resolve; order cancel/cancellation-confirm/revalidate/adopt; payment detail/evidence/evidence-confirm; metrics and sanitized audit trail. Exact schemas are in `apps/api/routers/supplier_operations.py`. Viewer reads state, operator handles files/handoffs/evidence, admin confirms payment and sensitive recovery. CSRF/origin checks apply through the existing identity dependency. Console code is split under `apps/web/components/suppliers/`.

## Measurement and remaining limits

Operational intervention events are deduplicated by business key, retain actor/time/category and optionally order/batch/supplier. They include manual send/ack/payment approval/evidence, cancellation/review recovery and manual claims/settlements. No production automation percentage is emitted. Legacy transactions with no recorded interventions are not proof of automation.

Actual delivery transport remains manual; this phase does not send email or manipulate supplier portals. Real profile validation, secure evidence object storage, file retention, financial corrections/refund reconciliation and production/cross-browser/load validation remain explicit production work. Synthetic Docker/Chromium acceptance is separately documented in `phase10-acceptance.md` and source-bound `phase10-verification.md`; it is not actual supplier acceptance.
