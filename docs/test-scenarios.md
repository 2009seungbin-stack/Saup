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


## Phase 10 scenario suite

`test_supplier_operations.py`: batch eligibility/membership/idempotency, frozen profile/file/PII audit/text/formula safety, explicit send, complete/mixed/rejected/conflicting acknowledgement, changed terms, payment/evidence/admin limits/deposit safety, shipment gating/duplicates, before/after-send/ack/payment cancellation, required audits and intervention counts.

`test_supplier_api_security.py`: viewer mutation denials, operator admin-confirmation denial, CSRF/origin, privileged file download, no PII/ciphertext in lists, review acknowledgement distinct from resolution.

`test_supplier_recovery.py`: original-economics recovery, unrelated-risk pause protection, UNKNOWN payment behavior, conflicting/reused evidence, superseded batch cancellation, illegal transitions, immutable records, migration round-trip/legacy adoption/nonempty downgrade guard, manual settlement categories.

`test_supplier_postgres.py` (real service required): concurrent identical acknowledgement creates one payment; concurrent evidence and admin confirmation create one receipt/confirmation/journal; concurrent duplicate tracking creates one shipment/job; append-only DB triggers; competing incompatible acknowledgements have one winner and a deterministic conflict. PostgreSQL fixtures now migrate through 0003. Redis tests include distributed sharing and fail-closed unavailable connection.

`scripts/demo_supplier_operations.py` uses temporary synthetic SQLite databases and both payment policies, with accepted/rejected lines and repeated commands, tracking import and mock marketplace update. No browser, Docker or live provider execution is implied. `scripts/verify_phase10.py` records exact checks/source hashes/coverage/logs and fails configured infrastructure gates on skip. See phase10-verification.md for executed results.

## Actual Docker/Chromium acceptance

`tests_browser/test_supplier_console.py` is a separately selected suite of seven real browser cases, not HTTP mocks: complete UI-created mixed batch/file/export/send/ack/evidence/admin confirmation/tracking flow; viewer PII/mutation restrictions; CSRF/Origin/session contract; price-change review without payment; cancellation before/after send; and labelled demo-provider shipment. Identical commands/imports do not add financial/shipment effects.

`tests/test_acceptance_fixture.py` adds 21 ordinary cases for environment/credential/one-shot guards and rejection of incomplete, duplicate or unbalanced verification results. The existing login-rate-limit test fixes only its clock to test both the same-minute 11th-request rejection and the next-minute reset without wall-clock flakiness.

The acceptance workflow compares durable PostgreSQL order/payment/evidence/shipment IDs, counts and account/journal balances before and after DB/Redis/API/worker/web restart. It rejects zero, incomplete or skipped browser selection. See `phase10-acceptance.md` for isolation and reproduction. This does not exercise live payments, real supplier acceptance or backup restore.


## Phase 11A bounded review resolution

Phase 11A suites: test_review_resolution.py, test_review_resolution_api.py, test_review_resolution_postgres.py, tests_browser/test_z_review_resolution_console.py. Verify correction/confirmation races, refund receipt dedupe, append-only history, exact allocations, rollback and customer hold. The acceptance restart snapshot includes new resolution history and schema 0003; do not reuse Phase 10 test counts.
