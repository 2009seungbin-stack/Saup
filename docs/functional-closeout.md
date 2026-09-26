# Saup 1.0 file-based operational closure

Base main: `0c1cb07912c178ec136dd33514c14da2d503eba2`. This increment completes
bounded operator handoffs, not live marketplace/payment automation. Verification
must be tied to the exact feature or merged SHA and downloaded CI artifacts.

## IMPLEMENTED

`초기 설정` guides accounts, Excel suppliers, editable column mappings/defaults,
existing price-file imports, local listings, two-admin destination approval,
confirmed opening bank cash and supplier deposits, then canonical order intake.
Passwords are request-only and hashed; usernames cannot be overwritten. Supplier
creation never accepts demo mode or preapproves a destination. Listing creation
starts PAUSED/UNKNOWN and performs no remote API call. Explicit external listing
activation rechecks stock freshness, margin, product risk, destination and funds.

Opening cash is one BANK+/EQUITY- journal on an empty ledger. Supplier deposits
reclassify verified completed bank funding as BANK-/DEPOSIT:supplier+. They do not
create money. References, SHA-256 and explicit external verification attestations
are mandatory. No bank balance is assigned directly, and committed/reserved bank
cash cannot fund a deposit. All money commands serialize on the existing treasury
row lock and use payload-bound replay.

`외부 처리 확인` distinguishes an internal shipment, provider result and immutable
manual marketplace confirmation. File-origin orders cannot acquire a fake
marketplace success through a demo adapter. Their job remains explicitly blocked;
the separate manual receipt is the operator completion evidence. Delivery requires
that receipt and separate actual delivery evidence, then recognizes the existing
sale ledger. No provider receipt is manufactured.

`클레임` exposes supported claims, actual supplier response, supplier recovery,
refund preparation and external customer refund confirmation. Manual refunds stay
EVIDENCE_PENDING and never enqueue or dispatch a money operation. Admin confirmation
rechecks exact order/claim/amount/market, ceilings, eligibility and settlement state.
Partial refunds remain PARTIALLY_REFUNDED; only the exact requested total becomes
REFUNDED. Supplier recovery is separately evidenced and supplier-specific.

`정산` records a statement separately from actual cash receipt. The comparison
includes completed customer refunds and explicit admin adjustments. Nonzero
differences open a review and cannot automatically CLOSE. Open claims also prevent
CLOSED. Before bank confirmation, an admin can correct a statement with a typed
reason and expected revision. Old values remain in immutable history; explicit
inverse and replacement journals correct the accounting. Confirmed statements
cannot use this correction path.

The existing paid-cancellation flow remains: confirmed supplier cancellation,
full supplier recovery, external full customer refund, zero-residual marketplace
statement, then invariant-checked CANCELLED. An unresolved mistaken statement can
be corrected by appending a version, bound to the same review/order and expected
revision. The original row is never modified. Remaining residuals stay blocked.

## Schema and API

Migration `0005_functional_closure.py` / `schema_v5.py` adds only three tables
(runtime 46): operational_receipts, settlement_revisions and
cancellation_statement_revisions. ORM guards and PostgreSQL/SQLite triggers reject
UPDATE/DELETE. Populated downgrade fails. Frozen schemas/migrations 0001–0004 are
unchanged. Deploy API and worker together after migration; old applications do not
understand the new evidence and correction paths.

New dedicated routes under `/v1`:

| Route | Authority |
|---|---|
| GET setup, operations, claims/{id} | viewer |
| GET/POST users | admin |
| POST suppliers; PUT suppliers/{id} | admin |
| POST listings, listings/{id}/external-activation | operator |
| POST funds/opening-bank, suppliers/{id}/deposit | admin |
| POST shipments/{id}/external-confirmation, orders/{id}/delivery-confirmation | operator |
| POST orders/{id}/claims, claims/{id}/supplier-response | operator |
| POST claims/{id}/supplier-recovery, claims/{id}/refunds, refunds/{id}/external-confirmation | admin |
| POST orders/{id}/settlement | operator; adjustment requires admin |
| POST settlements/{id}/cash-confirmation, settlements/{id}/corrections | admin |
| POST reviews/{id}/marketplace-statement-corrections | admin |

Existing profile/import/batch/11A/11B routes are reused. Every mutation retains
session, CSRF and Origin guards. Generic projections exclude customer PII and
ciphertext. Hashes/references are operator attestations, not independent bank or
marketplace verification. Reviews acknowledged by operators are not resolved.

## TESTED / NOT TESTED

Run ordinary tests, real PostgreSQL/Redis and frontend gates with the existing
verification runner. New tests cover blank configuration and three transactions,
replay, refund states/ceilings, RBAC, evidence conflicts, correction history and
database immutability. New real-PostgreSQL races cover opening cash, manual refund,
shipment evidence, settlement cash and competing statement corrections.

`.github/workflows/closure.yml` starts with only bootstrap admin and treasury
accounts using `docker/compose.blank.yml`; no demo product/order seed, SQL writes
or business-state edits. Actual Chromium signs in, exercises console forms and
screens, and uses ordinary APIs for the complete three-transaction scenario.
`scripts/closure_scenario.py` is shared with the serial API test. The blank workflow
asserts complete-row hashes/counts for 28 durable business/evidence/ledger tables
before/after PostgreSQL, Redis, API, worker and web restart. This is a **normal
restart test, not backup restoration**. Logs, JUnit, exact source and screenshots
are preserved, including on failure. Green badges alone are insufficient evidence.

This document does not assert unexecuted checks. See the exact SHA's Actions
artifacts and final handoff report for counts, hashes and actual results.

## BLOCKED / FUTURE

Live marketplace/payment providers, actual supplier credentials/contracts and
external evidence remain external gates. REAL_PAYMENTS_ENABLED still refuses
startup without a certified connector. UNKNOWN financial operations are not manual
retry candidates. Complex multi-line reconciliation, post-settlement refunds,
confirmed-statement reversal, refund fee credits that would require negative
receivables, split/reship and nonzero cancellation residuals remain manual/blocked.
There is no force paid/closed/delete-journal endpoint.

After functional gates pass, stop business expansion. Remaining work is security,
backup/restore, load/failure testing, deployment hardening and a real supplier pilot.
