# Automation coverage by workflow

**This is implementation-path coverage, not an observed business automation percentage.** A workflow with working code is not the same as a production transaction completed without operator effort.

| Workflow | Local implemented automation | Human / integration boundary |
|---|---|---|
| Supplier price intake | Encrypted queued XLSX import, row validation, normalization, price history | Supplier must provide/upload file; template/onboarding configuration is manual |
| Pricing and margin | Deterministic price solve, rounded fees, accepted-order guard | Actual marketplace tariffs/tax and target policy must be verified |
| Price/inventory safety | Local pause, outbox sync, separate remote acknowledgment, stale stock/cash/claim guards | Real market update/stop API is blocked; outage cannot guarantee external sales stopped |
| Order intake | Duplicate external-line prevention, preserved address, durable job | Authenticated demo injection only; real marketplace polling/webhooks not connected |
| Supplier fulfillment | Intent, reservation, rechecks, unique supplier order, persistent simulated acceptance | Excel export is not supplier acceptance; manual acknowledgement flow incomplete |
| Supplier payment | Thresholds, whitelist snapshot, stable key, separate simulated receipt, unknown-result reconciliation | Live payment disabled; real funding/deposit/billing integration absent |
| Tracking | Supplier-specific XLSX validation, duplicate handling, simulated marketplace notification | File sourcing/manual upload and live shipment API remain external |
| Claims | Category/evidence-kind/deadline checks, supplier submission/response, bounded refund path | Real messages/evidence/media and ambiguous/high-value resolution need people/integration |
| Supplier recovery | Separate accepted amount and confirmed supplier credit | Actual receipt verification is not automated |
| Settlement | Expected/actual comparison, balanced ledger, anomaly queue, separate cash confirmation | Real statements/bank confirmation and mismatch resolution not connected |
| Discovery/probes | Separate demand/competition + margin checks, contribution-based experiment evaluation | Authorized market metrics/manual collection; no automatic live scaling |
| Review/notification | Unified exception queue, audited acknowledgment, console notifications | Acknowledgment is not resolution; email/webhook delivery and escalation unfinished |

`production_rate` is explicitly null/NOT_MEASURED. The demo result has `real_money_transferred=false`. An ordinary-transaction automation target of 95% requires a real observation cohort, all operational handoffs/interventions, supported live adapters and resolved production gates. Python line coverage must never be labelled an automation rate.


## Phase 10 measurement infrastructure

OperationalIntervention records category, actor, time and linked order/batch/supplier with a unique business key. Manual file creation/export/send, acknowledgement, payment approval, evidence recording/confirmation, supplier cancellation/recovery, claim response/refund approval and settlement reconciliation/cash confirmation are accounted for. Metrics return completed orders with/without recorded interventions plus per-category counts. `production_automation_percentage` is null; historical missing instrumentation is not evidence of zero human work. Defining an ordinary transaction cohort and externally verified completion remains future measurement work.
