# Required scenario mapping

The source requirement's twenty scenarios map to actual tests, not claimed live-provider runs:

| Required scenario | Executed test evidence |
|---|---|
| Duplicate marketplace webhook/order | `test_duplicate_order_supplier_and_payment` (order injection, not signed live webhook) |
| Duplicate supplier order | `test_duplicate_order_supplier_and_payment` |
| Duplicate payment | `test_duplicate_order_supplier_and_payment`, `test_sql_unique_order_and_payment_keys` |
| Supplier price spike | `test_price_spike_retains_history_and_pauses` |
| Margin below threshold | `test_invalid_orders_enter_review[price-MARGIN_BELOW_THRESHOLD]` |
| Out of stock | `test_invalid_orders_enter_review[stock-OUT_OF_STOCK]` |
| Cancellation before supplier order | `test_cancel_before_supplier`, `test_cancellation_detected_at_provider_recheck` |
| Cancellation after supplier order | `test_cancel_after_supplier_before_payment`, `test_cancel_after_payment_not_silently_refunded` |
| Invalid address | `test_invalid_orders_enter_review[address-ADDRESS_ERROR]` |
| Malformed supplier Excel | `test_invalid_excel_is_durable_error`, `test_partial_rows_imported_but_bad_rows_queued` |
| Duplicate shipment rows | `test_duplicate_shipment_rows_are_all_quarantined`, `test_duplicate_shipment_no_second_update` |
| Customer quality claim | `test_quality_claim_evidence_required` |
| Supplier claim rejection | `test_supplier_rejection_requires_review` |
| Partial supplier refund | `test_partial_supplier_recovery_full_customer_refund` |
| Full customer refund | `test_partial_supplier_recovery_full_customer_refund` |
| Settlement mismatch | `test_settlement_statement_is_not_cash_and_mismatch_flagged` |
| Insufficient cash | `test_invalid_orders_enter_review[cash-INSUFFICIENT_CASH]`, `test_low_cash_proactively_pauses_active_listings` |
| Payment above approval threshold | `test_large_payment_manual_approval` |
| Integration timeout | `test_payment_timeout_after_remote_commit_reconciles_without_duplicate`, `test_outbox_retry_backoff_then_dead_letter` |
| Failed marketplace price update | `test_price_sync_timeout_fails_closed_but_remote_unconfirmed` (simulated listing-sync fault) |

Additional tests cover roles/session/CSRF/origin/rate limits/redaction, formula/ZIP/header/text-ID rules, payload conflicts, money bounds, balanced ledgers, stale inventory, changed destinations, safe replay, supplier deposit isolation, claim sample windows, audits, provider configuration and discovery/probe API. Consult actual output for latest count; infrastructure skips are not included in the passed count.
