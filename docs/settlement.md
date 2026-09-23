# Settlement and internal ledger

## Example accounting sequence

All examples are integer KRW, internal operational accounting and **not a certified statutory accounting system**.

1. Initial confirmed funding: BANK +, EQUITY −.
2. Supplier payment: SUPPLIER_EXPENSE +, BANK and/or supplier-specific DEPOSIT −. Reservation becomes SPENT.
3. Delivery: MARKETPLACE_RECEIVABLE + net expected proceeds, MARKETPLACE_FEES/PROMOTION_EXPENSE +, REVENUE −.
4. Customer marketplace refund: REFUND_EXPENSE +, MARKETPLACE_RECEIVABLE −.
5. Confirmed supplier recovery: supplier DEPOSIT +, SUPPLIER_RECOVERY −.
6. Statement: SETTLEMENT_CLEARING + actual amount, MARKETPLACE_RECEIVABLE − expected, SETTLEMENT_VARIANCE balances the difference.
7. Confirmed deposit to bank: BANK +, SETTLEMENT_CLEARING −.

Supplier acceptance and marketplace statement records do not create spendable bank money. Entries are atomic with state changes, payload-bound idempotent and balanced. PostgreSQL migration adds deferred balance/nonempty triggers; SQLite tests enforce balance through the service and test immutable record triggers, not PostgreSQL transaction semantics.

## Expected versus actual

`expected = gross_sale - discount - marketplace_fee - promotion_cost - succeeded_refunds + adjustment`.

`difference = actual - expected`. A difference outside tolerance creates SETTLEMENT_ANOMALY. Bank confirmation is separate. A transaction closes only after confirmation, exact reconciliation and no unresolved claim. Mismatches remain SETTLED rather than silently CLOSED. The default tolerance is a method parameter; an account-specific statement policy/config UI is not implemented.

The demo's actual contribution calculation is `actual_settlement - supplier_paid + confirmed_supplier_recovery`. Customer refund is already included in net settlement and must not be subtracted twice. Tax liabilities and statutory financial reporting require separately verified accounting policy; the tax reserve here is a configurable cash restriction, not tax computation.

## Boundaries

One final statement per fulfillment line. No multi-period installments, pooled statement allocation, fee reversals after full refunds, negative payouts/chargebacks, or late post-settlement refund automation. Those cases are manual/blocking until new models, reconciliation commands and tests exist. Never edit immutable journals to force agreement; add a documented correcting journal through a future audited reconciliation operation.
