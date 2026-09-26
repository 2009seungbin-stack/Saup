# Order state machine

Normal flow:

```text
RECEIVED → VALIDATING → VALIDATED → RISK_CHECKED → PAYMENT_RESERVED
→ SUPPLIER_ORDER_PENDING → SUPPLIER_ORDERED → SUPPLIER_PAID
→ SHIPMENT_PENDING → SHIPPED → DELIVERED → SETTLEMENT_PENDING
→ SETTLED → CLOSED
```

Transitions are checked by `packages/domain/state_machine.py` and recorded in the audit trail. A repeat transition to the same valid state is harmless; arbitrary jumps are rejected.

Invalid addresses, margin/cash/stock/freshness/cutoff problems create review entries. Some holds retain a reservation because external fulfillment may already exist. Such reservations must not be released by simply changing a status field.

Cancellation before external dispatch cancels locally and releases the reservation. Cancellation during/after supplier dispatch first requires supplier cancellation confirmation. Cancellation during uncertain or completed payment is an exception requiring reconciliation/claim handling, not automatic money reversal. External order status is rechecked before supplier dispatch and again before payment; a cancellation that occurs during an external request cannot be prevented atomically and needs compensation. Live-provider guarantees are not yet verified.

The schema and transition module include `CLAIM_OPEN`, `SUPPLIER_CLAIM_OPEN`, `REFUND_PENDING`, `REFUNDED`, `PAYMENT_FAILED`, `SUPPLIER_FAILED`, `MANUAL_REVIEW` and `FAILED`. Current after-sales processing primarily uses the orthogonal Claim/Refund status records so delivery history is not overwritten. Not every exceptional order-state path is exposed as an operator command.

One line supports one shipment and one final statement. After-settlement refunds, reshipments and split fulfillment are blocked/manual until explicitly implemented. Direct SQL state edits are not supported operational recovery.


## Excel supplier lifecycle — distinct from Order.state

```text
PENDING → BATCHED → FILE_READY → EXPORTED → SENT → ACKNOWLEDGED
→ PAYMENT_PENDING → PAID → SHIPMENT_PENDING → SHIPPED
```

FILE_READY can also move directly to SENT with explicit actual-delivery metadata. Every step is a validated supplier transition, not a new marketplace Order state. Acceptance may instead become REJECTED or MANUAL_REVIEW. Batch status summarizes FILE_READY/EXPORTED/SENT/ACKNOWLEDGED/PARTIAL/REJECTED, plus INVALIDATED/CANCEL_PENDING/RESOLVED. Items retain their own acknowledgement outcome independent of subsequent payment/shipment state.

Pre-send cancellation can end locally. An exported but unsent batch is invalidated; surviving members return to PENDING and can form a new immutable file. Post-send/acceptance/payment requires CANCEL_PENDING and explicit supplier cancellation. Confirmation of supplier cancellation does not confirm money recovery. After money exposure the order stays CANCEL_REQUESTED with financial review.

MANUAL_REVIEW→SUPPLIER_ORDERED is allowed only through guarded original-term revalidation: unchanged intent, active supplier/listing, current address/margin/inventory/reservation/cash/destination, no cancellation or UNKNOWN payment. Supplier MANUAL_REVIEW→PENDING is limited to admin-verified unsent legacy adoption. No general force-state API exists. Rejected lines never transition directly to payment. Identical command replay does not repeat business effects.
