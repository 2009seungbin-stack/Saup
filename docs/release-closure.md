# Saup 1.0 functional closure — bounded scope, not another architecture phase

The goal is an operator-complete file-based workflow, not a growing table/test count.
The following scope is fixed. Work outside it requires a separate decision; live
provider access does not become implemented merely by entering credentials.

| Closure area | Required operator outcome | Current status |
|---|---|---|
| Setup | Real supplier, product, listing/profile, approved destination and confirmed funds can be configured without demo seeding or SQL | OPEN: setup UI and real onboarding acceptance remain |
| Order intake | Authorised source → safe preview → explicit import → current-order verification → existing validation/reservation → supplier batch | IMPLEMENTED in this increment; service/browser gates require current-source execution |
| Supplier and shipping handoffs | Existing batch/send/ack/evidence/tracking paths; accurate real external shipment confirmation | Existing supplier path retained; live marketplace or explicit manual external-confirmation workflow remains a gate |
| Exceptions and correction | Supported cancellation/claims/evidence/statement errors can be resolved without deleting immutable history | PARTIAL: existing 11A/11B narrow commands retained; fee/partial/incorrect final statement paths remain OPEN |
| Settlement | File input, matching, explicit adjustments, confirmed receipts, expected/actual profit | OPEN: ordinary after-sales/settlement routes still demo-scoped |
| Console and recovery | No JSON/SQL for supported ordinary tasks; safe retries, reason and next action, role boundaries | PARTIAL: new intake UI is operator-addressable; full blank-install acceptance remains OPEN |

## This change deliberately starts from verified main

Base: `c7fd4f0e2328c69944c1cc02ebc16d07c11f26bf`, tree
`b2a02eb9c623ec6371c70137749c355967b573f1` (Phase 11B).
The previously delivered Phase 12A evidence/parent draft is preserved separately
in its handoff package. It has not been merged into this independent increment.
There is no new schema or migration: runtime remains 43 tables / revision 0004.
Do not silently apply both patches to Commerce/API/dashboard without reconciling
and independently testing their overlapping edits.

## Implemented intake contract

See `order-intake.md`. This is not a rename of `/demo/orders`: the import never
calls a demo marketplace adapter to manufacture a current-order response. The
operator explicitly verifies the current source, and the existing internal risk
checks still determine whether a SupplierOrder may be created.

## Closure tests, not marketing

Final acceptance must eventually start with an empty installation, configure real
approved inputs, and exercise ordinary orders, partial supplier rejection,
pre-/post-payment cancellation, supported refund/fee settlement, bad-input
correction, known multi-line identities and replay/restart recovery. A synthetic
seeded browser run is valuable but does not prove that blank-install workflow.
Do not mark the whole release complete just because the current tests pass.

## Outside 1.0 scope

No AI pricing/support/advertising, multi-supplier routing, complex warehouses,
arbitrary split/reship, multi-account money allocation, undocumented APIs or
browser banking. Complex unsupported financial cases retain a specific blocked
state, not a force-paid/force-resolved command. UNKNOWN money outcomes stay unknown.
