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


## Phase 10 manual evidence is not an API transfer

Batch acknowledgement does not pay. Only unchanged accepted rows may prepare payment. Excel manual batches use EVIDENCE_PENDING (or MANUAL_APPROVAL for limits); no payment.execute job is enqueued. DEMO_PROVIDER batches are permitted only in test/demo and remain labelled synthetic.

Operators register immutable SupplierPaymentEvidence with exact payment/supplier/amount/bank/deposit allocation/destination snapshot/reference/hash. Admin confirmation is a separate immutable SupplierPaymentConfirmation and requires an explicit true money-moved attestation and matching frozen amount/reference/destination. It rechecks supplier/order/accepted terms/HELD reservation/cash/limits. Wrong metadata creates durable review even when the HTTP response is a conflict. Registration alone never changes Payment to SUCCEEDED.

Manual approval does not override DAILY_PAYMENT_LIMIT. A higher-than-AUTO amount still requires the existing admin approval path. Supplier deposits cannot fund another supplier and remain nonnegative; confirmation posts balanced supplier-specific entries and spends the existing reservation. Only confirmed credits are spendable. Duplicate evidence/confirmation is idempotent; differing metadata conflicts. UNKNOWN/SENDING cannot become a manual evidence retry. The old REAL_PAYMENTS_ENABLED startup gate is unchanged.

Proof or a completed/ambiguous payment means money exposure during cancellation. A supplier cancellation confirmation retains FINANCIAL_REVIEW and does not release money, invent a supplier refund, or restore inventory. Correcting mistaken evidence and reconciling actual refunds require dedicated follow-up commands; there is no force paid button. Audit events use IDs, amounts and hashes, not customer PII.


## Phase 11A bounded review resolution

Phase 11A correction holds block manual confirmation. Only unconfirmed proof reference/hash can be versioned; every later confirmation binds the effective revision. Full pre-shipment supplier recovery requires actual receipt evidence, original payment journal and exact supplier/bank allocation; it never marks the customer refunded. Shared receipt namespace and unique recovery hash prevent duplicate credits. See phase11-review-resolution.md for unsupported cases.

## Phase 11B marketplace cancellation reconciliation

Phase 11B moves no money: no bank/marketplace call, refund job, payment mutation, reservation release or journal. It records that the marketplace already refunded the customer in full; that record is not proof of any seller-side cash and supplier receipts/outgoing payment references cannot be reused as customer refund evidence. Because receivable is recognized only at delivery, the pre-shipment path posts nothing; posting CUSTOMER_REFUND would make MARKETPLACE_RECEIVABLE negative. Orders already carrying sale, refund or settlement accounting are rejected. Nonzero seller payout, debit, retained fee or outstanding balance blocks completion and opens an explicit review. See phase11b-marketplace-cancellation.md.
