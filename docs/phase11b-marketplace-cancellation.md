# Phase 11B — customer / marketplace cancellation reconciliation

Base: Phase 11A head `713929a46f81bc566f3d753cdce0877a60d64aac` (tree `ff6bed3839caa1f5dbcf208561912d7b8fd06123`), 2026-09-26.
Branch: `feat/phase11b-marketplace-cancellation`. This is a feature increment, not a claim that Phase 11 is deployed or production-ready.

## Provenance

A Phase 11B implementation was reportedly completed on another machine but never reached GitHub: the remote branch
`feat/phase11b-marketplace-cancellation` pointed at the Phase 11A head with no additional commits, and no
`Saup_Phase11B.patch`/report/package existed on this machine. This increment is therefore a **reconstruction from the written
Phase 11B specification**, not a port of that patch. The earlier local results (Python 3.13.5, 291 tests, 91.30%) belong to
that unpublished source and are not evidence for this one.

## What the path does — and does not do

Supported flow (single fulfillment line, pre-shipment, full amounts only):

```
supplier payment SUCCEEDED
→ supplier cancellation confirmed (FINANCIAL_REVIEW)
→ Phase 11A full supplier recovery (FINANCIALLY_RECONCILED; customer review opened)
→ record marketplace customer FULL refund evidence           (admin, evidence only)
→ record final marketplace cancellation statement            (admin, evidence only)
→ completion re-checks every invariant under the treasury lock
→ customer review RESOLVED, Order CANCEL_REQUESTED → CANCELLED
```

It **does not send money**. It records evidence that the marketplace already refunded the customer. It never calls a
marketplace or bank, enqueues `refund.execute`, marks the Payment CANCELLED, releases the SPENT reservation, restores stock,
marks the Order CLOSED/SETTLED, changes the supplier recovery, or deletes/edits a journal.

## Implemented

### Entities (schema_v4, migration 0004; runtime metadata 43 tables)

All three are append-only (ORM `before_update/before_delete` guards and PostgreSQL/SQLite triggers).

| Table | Key constraints |
|---|---|
| `marketplace_refund_evidence` | unique per review, per order, per supplier recovery; unique `evidence_hash`; unique `(marketplace, reference)`; amount > 0 |
| `marketplace_cancellation_statements` | unique per review/order/refund evidence; unique hash and `(marketplace, reference)`; all amounts ≥ 0; `classification ∈ {ZERO_SELLER_SETTLEMENT, UNSUPPORTED_RESIDUAL_SETTLEMENT}` |
| `marketplace_cancellation_reconciliations` | unique per review/order/refund/statement/recovery/payment; check `CANCEL_REQUESTED → CANCELLED` |

Each record stores the marketplace line identity, the `snapshot_hash` it was recorded under, a business `payload_hash`
(payload without idempotency key), actor and timestamp. `schema_v1/v2/v3` and migrations 0001–0003 are unchanged.

### Commands and API (admin only; existing session, CSRF and exact-Origin checks)

| Method/path | Meaning |
|---|---|
| POST `/v1/review-resolutions/{id}/record-marketplace-refund` | Record the external full customer refund receipt |
| POST `/v1/review-resolutions/{id}/record-marketplace-statement` | Record the final cancellation statement (all fields explicit) |
| POST `/v1/review-resolutions/{id}/complete-marketplace-cancellation` | Re-check everything, resolve review, Order → CANCELLED |

`GET /v1/review-resolutions` (viewer) still returns status/IDs only. `GET /v1/review-resolutions/{id}` (operator) adds
`stage`, `next_action`, a safe snapshot and the recorded evidence; no PII, ciphertext or free text.

Inputs are strict Pydantic models (`extra=forbid`, strict integers). Attestations (`confirmed_customer_refunded`,
`confirmed_final_statement`, `confirmed_marketplace_cancelled`, `confirmed_reconciliation`) accept only literal JSON `true`.
Statement amounts `customer_refund_amount, seller_payout_amount, seller_debit_amount, retained_fee_amount,
outstanding_balance` have no defaults: omission is a 422, never zero.

Refund evidence must bind the current `snapshot_hash`, the exact supplier recovery, marketplace, external order and line,
and the exact full customer amount `gross_sale − discount` (supplier cost is never accepted as the customer refund).
Evidence hashes cannot be reused across refund evidence, statements, supplier recoveries, payment proofs or proof
revisions; references are unique per marketplace; a supplier receipt/outgoing payment reference is rejected as customer
refund evidence.

### Invariants re-derived on every command (under `lock_treasury`)

Customer review category and OPEN/ACKNOWLEDGED; supplier recovery present and bound to this order/payment/supplier order;
supplier cancellation FINANCIALLY_RECONCILED; supplier order CANCELLED; payment SUCCEEDED; reservation SPENT and equal to
payment; full recovery with unchanged frozen economics; recovery journal present; Order `CANCEL_REQUESTED` with
`cancel_requested`; no delivery, shipment, claim, customer refund row or settlement; the order carries **only**
SUPPLIER_PAYMENT and SUPPLIER_RECOVERY journals; no other line for the same marketplace order; no other unresolved review on
the order, supplier order, payment, cancellation, recovery or payment proofs (except `CANCELLATION_AFTER_PAYMENT`, which this
completion resolves). Recorded refund evidence and statement must still match the current snapshot hash, identity and
amount. The detail view evaluates the same checks, so a stale page shows BLOCKED rather than READY.

### Residual seller-side settlement

A statement with any nonzero seller payout, seller debit, retained fee or outstanding balance is still recorded (it is
real external evidence) as `UNSUPPORTED_RESIDUAL_SETTLEMENT`. An explicit `MARKETPLACE_CANCELLATION_RESIDUAL_SETTLEMENT`
review is opened, the customer review stays OPEN, the stage is `BLOCKED_UNSUPPORTED_RESIDUAL_SETTLEMENT` and completion is
refused. A mistyped residual therefore blocks the automated path permanently; it needs a future dedicated reconciliation
command, not a silent overwrite.

### Accounting

No journal is posted. Sale/receivable recognition (`sale:{order}` → MARKETPLACE_RECEIVABLE) happens only at delivery, so in
this pre-shipment path the receivable never contained the order and the marketplace reversed the customer charge before any
seller payout. Reusing the delivered-order `CUSTOMER_REFUND` journal (REFUND_EXPENSE / −MARKETPLACE_RECEIVABLE) would make the
receivable negative and double count an external refund. Orders with any other journal kind are rejected rather than
interpreted. Existing journals stay balanced and untouched.

### Idempotency and concurrency

Command keys (`scope + idempotency_key + full payload hash`) replay exact results and conflict on changed payloads. Business
uniqueness adds a second layer: an identical payload with a new idempotency key (reopened browser) returns the existing
effect, a different payload for the same review is a deterministic `*_CONFLICT`. Failed commands roll back all effects in a
savepoint and keep a `REVIEW_COMMAND_BLOCKED` audit.

### Cross-line safety (single line only)

Recording and completion fail closed with `MULTI_LINE_MARKETPLACE_ORDER_UNSUPPORTED` if another line of the same marketplace
order exists. `Commerce.ingest` holds any new line for a marketplace order that already has refund evidence in
`MANUAL_REVIEW` with a `MARKETPLACE_LINE_AFTER_CANCELLATION_EVIDENCE` review and does not enqueue processing. A completed
reconciliation is not rewritten. Parent-order/multi-line reconciliation is future architecture work.

### UI

`apps/web/components/reviews/MarketplaceCancellationPanel.tsx`, embedded in **검토 해결** for the customer review category.
It shows the stage (supplier recovery complete / refund evidence missing / statement missing / ready / resolved / blocked),
states "이 화면은 송금하지 않습니다 (this does not send money)", uses separate attested forms, requires every statement amount
to be typed (even 0), lists unsupported cases and never shows a completion button when blocked. Operators see the detail
without forms; viewers cannot open detail.

### Migration 0004

Creates the three tables and append-only triggers (PostgreSQL `saup_append_only()`, SQLite RAISE triggers). Downgrade is
refused when any Phase 11B row exists (`PHASE11B_DATA_PRESENT_DOWNGRADE_BLOCKED`) or when a residual/late-line review exists
(`PHASE11B_REVIEW_PRESENT_DOWNGRADE_BLOCKED`), because an older binary would ignore those holds. Roll out all processes
together after migrating; do not roll application code back below 0004 once such data exists.

## Tests added

- `tests/test_marketplace_cancellation.py`: happy path with final-state assertions (Order CANCELLED, SupplierOrder CANCELLED,
  Payment SUCCEEDED, Reservation SPENT, cancellation FINANCIALLY_RECONCILED, no shipment, no new jobs, identical account
  balances/journal count, stock unchanged, balanced ledger); refund replay/conflict and every rejection (marketplace, order,
  line, amount, supplier cost, snapshot, recovery, reused supplier/payment reference, reused hash, cross-order reuse, literal
  `true`, missing attestation, non-admin, wrong category); statement replay/conflict, each residual field, omitted fields,
  wrong refund amount/snapshot/refund evidence/hash, negative/bool amounts, statement before refund; completion before
  evidence, fourteen corrupted invariants, duplicate/conflicting completion, exact evidence binding, rollback on failure,
  `CANCELLATION_AFTER_PAYMENT` resolution; second-line and late-line holds; ORM and SQL append-only; populated and
  review-only downgrade refusal; empty 0001→0004→0001 migration chain with frozen snapshot sizes 28/36/40/43.
- `tests/test_marketplace_cancellation_api.py`: viewer/operator 403 on all three commands, viewer list shape, CSRF and foreign
  Origin 403, non-literal booleans/strings/extra fields 422, 409 codes, idempotent replay, omitted statement field 422, PII
  absent, residual block over HTTP.
- `tests/test_marketplace_cancellation_postgres.py` (real PostgreSQL only): duplicate refund/statement/completion (including a
  reopened-browser key) → one effect each; one marketplace receipt competing across two orders → one winner; statement racing
  completion → completion never succeeds without the statement; completion racing a late marketplace line → the line is
  always held and completion either wins or fails with the multi-line code; conflicting completions → one reconciliation and
  one resolution.
- `tests_browser/test_zz_marketplace_cancellation_console.py` (real Chromium, real Docker API/DB/Redis): full UI happy path
  with before/after business snapshots; viewer/operator RBAC, CSRF, foreign Origin and nonzero-residual block.
- Acceptance snapshot requires schema `0004`, records safe projections of all resolution tables, per-order reconciliation IDs
  and job counts; the restart comparison covers them. Minimum browser cases raised from 9 to 11.
- Changed 11A assertions: the customer review now reports stage `CUSTOMER_REFUND_EVIDENCE_MISSING` and the Phase 11B action
  instead of "no automated resolution"; it still remains OPEN and the order remains CANCEL_REQUESTED after supplier recovery.

## Verification record

Results are recorded per exact SHA in `phase11b-verification.md` and in the PR. Local runs on an uncommitted tree are not CI
evidence.

## Not tested / blocked / future

- NOT TESTED: real marketplace refund or statement documents; Firefox/WebKit/mobile; load, chaos, backup/restore; production
  HTTPS deployment.
- BLOCKED (external): official marketplace API access and real statement formats, real refund receipts, certified live
  payments (`REAL_PAYMENTS_ENABLED` remains blocked).
- FUTURE: parent marketplace order / multi-line reconciliation; partial or fee-adjusted cancellation and a dedicated residual
  settlement command with accounting; post-shipment cancellation; settlement batches; evidence object storage, retention and
  key rotation.
