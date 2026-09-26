# Phase 11A — bounded Review Resolution Engine

Base: main `77f5589c3ed4473cc8bca315e9e416cde162e7a0`, tree `97eef1d5cdde25405c7fe02ee715672ceb07e977` (2026-09-26).
This is an additive feature-branch increment, not a statement that Phase 11 is merged, deployed or production-ready. Consult the PR and the exact head SHA's Actions artifacts for executed results. Phase 10's historical test counts are not results for this source.

## Implemented boundaries

Two domain commands, no force-state/force-paid endpoint:

1. **Correct unconfirmed supplier payment evidence.** An operator/admin requests correction of the current proof version. That unresolved review blocks payment confirmation, including a concurrent old browser request. Admin can append a revision of the reference/hash only. The immutable original and every revision remain. Amount, supplier, SKU, quantity, destination, payment method and bank/deposit allocation cannot change. Confirmation explicitly names the current revision; a separate immutable binding links that revision to the original payment confirmation. A stale page cannot confirm a newer proof implicitly. Original version-0 confirmations retain their pre-0003 idempotency hashes.
2. **Confirm already-received full supplier cancellation recovery.** Admin records receipt reference/hash and an explicit true attestation. Only a confirmed-paid, confirmed-cancelled Excel order before any shipment, delivery, claim, refund or settlement is eligible. The command checks the frozen intent, SPENT reservation and original SUPPLIER_PAYMENT journal, and requires exact original bank/deposit allocations. One new balanced recovery journal is posted. The original payment remains SUCCEEDED; reservation remains SPENT; stock is not restored. Supplier cancellation becomes FINANCIALLY_RECONCILED. The marketplace order remains CANCEL_REQUESTED and a separate customer/marketplace reconciliation review remains OPEN.

Corrected outgoing evidence is **not** independently verified banking data. A hash is evidence identity, not proof of money movement. Admin remains responsible for checking the actual receipt. No transfer or external provider call occurs in these commands. REAL_PAYMENTS_ENABLED remains blocked.

## Persisted entities and migration

Alembic `0003_review_resolution` adds four append-only tables, raising runtime metadata to 40 tables:

- `supplier_payment_evidence_revisions`: versioned metadata, predecessor, review, actor and payload hash.
- `supplier_evidence_confirmation_bindings`: exact proof revision used by confirmation.
- `supplier_cancellation_recoveries`: payment, supplier, original allocations, receipt identity and balanced journal.
- `review_resolutions`: typed action, actor/time, payload hash and safe resulting IDs.

`schema_v3.py` copies v2. `schema_v1.py`, `schema_v2.py`, migration 0001 and migration 0002 are unchanged. PostgreSQL/SQLite migrated databases reject UPDATE/DELETE on new history tables; ORM guards also apply. Downgrade is refused when Phase 11 rows **or even a correction-request safety hold** exist. No existing evidence is rewritten/backfilled as accepted or refunded.

All application processes must be upgraded together after migration in a controlled maintenance window: an older binary does not understand the correction hold. Do not roll back application code to Phase 10 while these holds/history exist. Test upgrade and restore on a disposable copy; there is no automated production rollback/backup-restore claim.

## Concurrency and idempotency

Acquire the existing treasury row lock before reading state. Command keys bind target + full validated payload. A successful exact replay returns the recorded result; a changed payload conflicts. Review/version checks and database uniqueness provide additional protection. Failed business changes roll back inside a savepoint; a safe rejection audit survives outside it.

A correction preserves all old payment references as reserved against other payments, including references in superseded revisions. Incoming recovery shares the existing `supplier-recovery:{supplier_id}:{reference}` journal namespace with legacy claim recovery, so the same reference cannot be posted through both paths. A recovery evidence hash cannot be reused for another cancellation, even with a different reference. Multi-order receipt allocation is deliberately unsupported. The older claim API does not store evidence hashes; matching real-world receipts assigned different references across old/manual systems still requires operator reconciliation.

Legacy claim recovery's total bound now includes cancellation recoveries. The new path rejects orders with claims/shipments/settlements rather than trying to allocate overlapping accounting. It never releases paid reservations or borrows another supplier's deposit.

## API and roles

| Method/path | Minimum role | Meaning |
|---|---|---|
| GET `/v1/review-resolutions` | viewer | Bounded queue; status/IDs only |
| GET `/v1/review-resolutions/{id}` | operator | Current eligibility, immutable resolution history, safe payment snapshot |
| POST `/v1/supplier-payment-evidence/{id}/correction-request` | operator | Open a version-bound correction hold |
| POST `/v1/review-resolutions/{id}/correct-payment-evidence` | admin | Append proof revision; do not confirm payment |
| POST `/v1/review-resolutions/{id}/confirm-supplier-recovery` | admin | Record actual received funds; do not refund customer or close order |

Existing `/v1/reviews/{id}/acknowledge` remains 'seen', not 'resolved'. Existing confirmation accepts optional `evidence_revision_id`; it is mandatory when a revision exists. Role, session, CSRF and exact-Origin checks remain enforced server-side. No new PII, raw documents, bank screenshots or unbounded notes are returned/stored. General queue entries never expose the evidence snapshot to viewers.

The console adds **검토 해결** as a separate component. The supplier payment pane requests correction and shows the confirmation hold. Admin sees only an eligible typed form, immutable amount/allocation and explicit attestation. Unsupported customer reconciliation shows a blocked reason, not a completion button. UI state is advisory; each command revalidates under lock.

## Verification contract

New ordinary tests cover correction chains/stale confirmation, legacy replay compatibility, immutable originals, reference reuse, strict true attestations, snapshot mismatch, preserved limits, role/CSRF/Origin, cancellation guards, original journal checks, rollback after posting, deposit isolation, receipt replay and migration/downgrade restrictions.

Three new real PostgreSQL cases cover duplicate correction/confirmation/recovery, a correction-request versus payment-confirmation race, and one receipt competing across two cancelled orders. Missing services are not counted as passing.

Two new Chromium cases exercise actual UI correction, confirmation, cancelled-order recovery and status-only viewer access, alongside existing seven supplier cases. Acceptance records all four new history tables and compares them across PostgreSQL/Redis/API/worker/web restart. The acceptance fixture requires schema 0003. No financial state is directly changed in browser setup.

Use the existing `scripts.verify_phase10` entrypoint and CI to retain command exits, JUnit, coverage, source SHA and frontend build logs. Its historic filename is retained for compatibility; it selects the complete current test suite. Acceptance is a separate workflow. Source-specific actual results belong in PR comments/release evidence; an unexecuted check is NOT TESTED or BLOCKED, not PASS.

## Deliberately unfinished / external blockers

Not implemented: correction of already-confirmed payments, explicit proof-of-no-money-moved for cancelled unconfirmed evidence, partial/net-fee refund or allocation changes, post-shipment recovery, customer cancellation/refund/settlement completion, reopened arbitrary-review resolution, broad new-term repricing, universal manual closure, or live bank/provider reconciliation. Those remain blocked/manual until dedicated commands and accounting exist.

External supplier approval, real receipts, verified account/deposit identities, official marketplace access, certified live payments, operational security, retention/key rotation, multi-browser/mobile, load/chaos and backup restore remain gates. This increment introduces more receipt references and immutable history to retain, the same treasury lock contention, and a deployment version-coordination requirement. It does not measure production automation percentage.
