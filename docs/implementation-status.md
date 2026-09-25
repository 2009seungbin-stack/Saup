# Implementation status · Phase 10 · 2026-09-25

## Current repository truth

The complete foundation is present on main at `b1f1f15ac3b6a396fe9f14e549f11721f49bfb7f`. Phase 10 is developed on `feat/phase10-supplier-operations`. Old empty-repository/ZIP-only claims are historical, preserved under `docs/history/`. Code and migration history outrank prose. This document does not claim main merge, deployment, or production readiness.

## IMPLEMENTED

Explicit supplier intent and batch membership; immutable frozen Excel content and profile version; separate export/send/acknowledgement; complete per-batch line accounting with mixed acceptance/rejection; changed terms review; original-term revalidation; guarded legacy adoption; existing finance handoff; immutable manual evidence plus separate admin confirmation; supplier-specific deposits and balanced ledger; strict shipment eligibility; conservative cancellation; typed review resolution; audited human interventions; separated supplier/auth routers and supplier console components; migration 0002; frontend lockfile and npm ci; reproducible verification runner and CI definitions.

Existing catalogue, cash/risk/reservation, demo API provider, claims/refunds/settlement, job idempotency and rate-limiter architecture remains. No undocumented marketplace API or live banking automation was introduced.

## TESTED / NOT TESTED

See `phase10-verification.md` and source-bound CI artifacts for exact commands/counts/coverage. Unit tests are not proof of PostgreSQL concurrency or a browser session. A committed workflow is not evidence that it ran. The synthetic script exercises both manual-evidence and demo-provider paths with no real money.

## BLOCKED

Certified live payment connector; authorized marketplace APIs; actual supplier onboarding/profile validation and verified destination/deposit evidence. `REAL_PAYMENTS_ENABLED=true` still fails configuration. Unknown external payment outcomes remain unretried until reconciled.

## FUTURE / internal unfinished work

Full browser E2E and Docker restart/restore; retained secure evidence objects instead of references; evidence correction and refund/cancellation financial reconciliation; supplier file retention/key rotation; complex corrected pricing/new order workflows; broad Review Resolution Engine; parent/multi-line orders, split/reship, settlement batch; worker lease renewal; provider contracts/observability. No production automation percentage is claimed.
