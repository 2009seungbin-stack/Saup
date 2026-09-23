# Payment safety

## Hard gate

Real supplier money movement is disabled. Setting `REAL_PAYMENTS_ENABLED=true` raises a configuration error because no approved official payment connector is implemented. `MockPaymentAdapter` behavior is provided by the persistent demo adapter; `ManualApprovalPaymentAdapter` does not pretend a manual bank transfer succeeded.

Production enablement requires an official provider contract, account-authorized API, verified destination binding, timeout/status lookup/idempotency behavior, validated credentials and audited code changes. Never automate bank web login, passwords, OTPs or click transfers. Never place secrets in Git or frontend variables.

## Money invariants

All money is a bounded integer in KRW. Rates are Decimal and percentage fees round upward to whole won. Required sale price solves `(supplier + shipping + claim allowance + promotions)/(1-fee-target margin)` and verifies the result after fee rounding.

Spendable money excludes marketplace receivables and settlement clearing. Reserve refund, tax and safety amounts, and subtract existing supplier commitments. Supplier deposits are restricted to that supplier. Missing liquid reserves cannot be filled with another supplier's deposit or unconfirmed proceeds.

Global `CONTROL` account row locking serializes financial decisions on PostgreSQL. This conservative initial design trades throughput for a simpler lock order. The concurrency gate must be run on PostgreSQL; SQLite does not prove row locking.

## Dispatch, retry and approval

Supplier-order, payment and refund business identities are unique. Provider requests use stable keys bound to exact request hashes. Demo receipts commit separately from application finalization, permitting crash/retry tests.

A payment moves PENDING → SENDING → SUCCEEDED. An uncertain result becomes UNKNOWN. Retrying an UNKNOWN payment does not dispatch money again; explicit transaction lookup may confirm an existing receipt. NOT_FOUND is not automatic permission to resend. Pending/uncertain commitments from prior days remain conservatively counted against the limit; completed payments use dispatch date in Korea time.

Single/daily thresholds are configuration, not universal rules. Manual approval pins amount/destination, records actor/time and still rechecks order/address/stock/margin/cutoff/destination. A changed supplier destination requires a different administrator to approve and a hashed verification reference. This does not perform actual bank identity verification.

## Known gates

Live account mapping, provider idempotency expiry, partial execution semantics, provider refunds/chargebacks, approval separation under an external identity provider and real deposit/bank reconciliation remain unfinished. Acknowledging a review is not approval. Never repair uncertainty by deleting unique keys, ledger rows or receipt records.
