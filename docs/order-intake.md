# Operational order-file intake

This increment connects an authorised file source to the existing supplier Excel
workflow. It does not certify live provider integration or complete Saup 1.0.

## Operator workflow

1. Open **주문 가져오기**, select the marketplace, download the blank order
   workbook and the listing-ID catalogue. The supplier/product/listing must
   already exist and be mapped to an Excel supplier.
2. Populate the single `주문` sheet using the exact provided headers. This is
   **SAUP_ORDER_XLSX_V1**, an internal canonical template, not a claimed official
   Coupang/Temu/AliExpress export format. There are at most 500 data rows. IDs,
   phone and postal code must be text; money is integer KRW; discount must be
   explicit (zero when applicable). Preserve the original address.
3. Preview errors and safe order/product/amount fields. Addresses/phones are not
   displayed. Nothing is persisted by preview. Correct every error and repeat
   preview: the file commits atomically, never silently imports just valid rows.
4. Supply the authorised original reference and tick the explicit attestation.
   Import creates encrypted Orders and a source-verification review, **not**
   SupplierOrders, reservations, payments or provider-processing jobs.
5. Read the current seller source (not just the previously downloaded workbook).
   Record a fresh reference/hash and confirm that this exact row is currently
   open/not cancelled. The explicit manual path checks the current snapshot and
   existing hold, address, supplier, stock/freshness, cutoff, margin and cash
   rules. A passed order becomes `SUPPLIER_ORDER_PENDING`, with its existing
   reservation and supplier intent. A failed order remains a visible review.
6. Continue in the unchanged supplier operations console: batch, download, actual
   send, supplier response, separate payment evidence/admin confirmation, tracking.
   Real marketplace shipment reporting still requires its own approved connector
   or future explicit manual external-confirmation flow; a demo result is not live.

## Persistence, audit and retry

No new table or migration. Existing unique `Order`, `Command`, `AuditEvent`,
`Review`, outbox and `OperationalIntervention` infrastructure is reused.

- Original workbook bytes are parsed in memory, not stored in a new plaintext
  upload store. The existing encrypted Order address is the only persisted
  customer address. Audit/command results store only safe IDs, hashes and counts.
- Preview tickets are authenticated/encrypted using the existing application
  cipher and bind file bytes, marketplace, actor, safe preview and 10-minute
  expiry. No PII is placed in them. First commit rechecks the preview under the
  treasury lock; an altered file or stale preview is rejected.
- Same file/market/template uses a stable command key. Same successful command
  replays even after response loss; different source-reference metadata conflicts.
  An exact duplicate order in another file is observed, not relabelled/recreated.
- Current-order verification binds order/supplier/listing/review snapshot,
  explicit literal boolean true, source hash/reference and an observation within
  the last 15 minutes. That is a human attestation, never `api_verified=true`.
- Revalidation here is limited to file-origin RECEIVED/MANUAL_REVIEW orders with
  no SupplierOrder, Payment or Reservation. Only specified pre-work risk reviews
  may be retried. Existing cancellation evidence, unknown/unrelated review or any
  financial/fulfillment history blocks this entry path. No review ACK bypass.
- A savepoint rolls back partially failed internal validation/reservation work
  before preserving the review. Stock cannot be consumed on a failed attempt.
- A stray `order.process` invocation cannot bypass the file-source gate. Normal
  API/demo ingestion still uses its original provider status check.

Important events: `MARKETPLACE_ORDER_FILE_IMPORTED`, `ORDER_IMPORTED_FROM_FILE`,
`MARKETPLACE_ORDER_STATUS_VERIFIED_MANUALLY`, existing Order transitions,
`REVIEW_RESOLVED`; intervention categories record import and human verification.

## API and RBAC

| Method | Path | Minimum role |
|---|---|---|
| GET | `/v1/order-imports` | viewer; counts/history only |
| GET | `/v1/order-imports/template` | operator |
| GET | `/v1/order-imports/catalog?marketplace=...` | operator |
| POST | `/v1/order-imports/preview` | operator; multipart marketplace/file |
| POST | `/v1/order-imports/commit` | operator; same file + strict JSON command form field |
| GET | `/v1/order-intake/pending` | operator |
| GET | `/v1/order-intake/{id}` | operator; safe snapshot, no customer PII |
| POST | `/v1/order-intake/{id}/verify-and-validate` | operator; strict typed command |

Existing session/CSRF/Origin/body-size boundaries apply. Admin remains required
for payment confirmation; no new financial authority is delegated to operators.

## Verification and operational limitations

Tests cover real workbook parsing, false dimensions/ambiguous cells, changed
inputs, no-PII output, atomic commits, replay, fresh evidence, normal validations,
partial rollback, existing cancellation/unknown guards and API security. Real
PostgreSQL cases cover competing import/verification/cancellation. The two new
Chromium scenarios exercise operational file input through the console and
status-only viewer access. Collecting those tests is not executing them.
The acceptance workflow compares the safe command receipts across restart.

The source-specific report/Actions artifacts, not historical counts, determine
which checks actually ran. A missing PostgreSQL/Redis service is BLOCKED; a failed
npm install is not a passed build. No new runtime dependency, migration, external
payment call or official marketplace endpoint is introduced.

Limitations: canonical template only; existing setup must be provisioned; individual
current-source verification remains manual; bulk source verification, row-level
customer correction, custom marketplace mappings and empty-install onboarding are
not implemented. Hashes identify evidence but do not independently verify it.
Files and customer data still require authorised processing/retention policies.
Treasury-lock contention and existing single-line cancellation restrictions remain.
The separately preserved Phase 12 draft is not included in this patch.

## First current-source execution and accessibility fix

Initial remote head `a4dfa1794c38ad970bcf3ca37514c7d9bf749ac1`: normal CI
`36254267034` passed Python 3.12.14 compile, 379 ordinary / 14 real PostgreSQL /
2 real Redis cases, both synthetic flows and npm ci/typecheck/build. Downloaded
backend/frontend artifact hashes, JUnit and source SHA were checked.

Separate acceptance `36254267115` built and started real containers but returned
**11 passed / 2 failed**. The new select's implicit label included its option text
and did not match the exact accessible name used by the UI test. The new order
scenario stopped before import; the subsequent viewer-history scenario then had
no imported history. All three restart/assertion steps were skipped, not passed.
The select now explicitly declares its accessible name. No financial check,
authentication rule or test assertion is removed. The updated source requires
fresh normal and browser runs; earlier success does not certify this follow-up.
