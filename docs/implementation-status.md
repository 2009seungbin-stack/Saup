# Implementation status · Phase 10 · 2026-09-26

## Current repository truth

Phase 10 PR #2 was merged into main on 2026-09-26 at integration checkpoint `3983ca576d63eccd47d722457d1245c3e20c0fd6`. Its Git tree matches verified feature head `afe7a488af12e16bb284f9e9ea28f297359d9bbc`. See `phase10-main-merge.md` for separate pre-merge acceptance and post-merge CI evidence. This is a fixed integration checkpoint, not a promise that main never advances. Old empty-repository/ZIP-only claims and the foundation base `b1f1f15ac3b6a396fe9f14e549f11721f49bfb7f` are historical. Code and migration history outrank prose. No production deployment, live payment enablement or production readiness is claimed.

## IMPLEMENTED

Explicit supplier intent and batch membership; immutable frozen Excel content and profile version; separate export/send/acknowledgement; complete per-batch line accounting with mixed acceptance/rejection; changed terms review; original-term revalidation; guarded legacy adoption; existing finance handoff; immutable manual evidence plus separate admin confirmation; supplier-specific deposits and balanced ledger; strict shipment eligibility; conservative cancellation; typed review resolution; audited human interventions; separated supplier/auth routers and supplier console components; migration 0002; frontend lockfile and npm ci; reproducible verification runner and CI definitions.

Follow-up acceptance adds guarded synthetic fixture setup, 21 fixture/verifier safety tests, seven browser cases, replay/restart evidence, a corrected confirmed-evidence UI message and a deterministic minute-window login test. No new migration or financial API was needed. Existing catalogue, cash/risk/reservation, demo API provider, claims/refunds/settlement, job idempotency and rate-limiter architecture remains. No undocumented marketplace API or live banking automation was introduced.

## TESTED — dated source-bound checkpoint

Checkpoint `b6dae8c1bdf4491b00c18d4e83aed49de2549693`: ordinary/API/migration 204 + PostgreSQL 3 + Redis 2 + real Chromium acceptance 7 = 216 distinct cases, with no failed/error/skipped cases. Verification run 36207399192 and application Docker/browser run 36207399204 both passed. Actual backend/frontend images, Compose startup and PostgreSQL/Redis/application restart persistence were exercised. Statement coverage is 90.60379918588873% (2,671 / 2,948 statements). The acceptance workflow used real HTTP, the worker, PostgreSQL and Redis; only supplier/marketplace/payment-provider responses were synthetic/DEMO. Later commits require new source-matched evidence. See `phase10-verification.md` and `phase10-acceptance.md`.

## BLOCKED

Certified live payment connector; authorized marketplace APIs; actual supplier onboarding/profile validation and verified destination/deposit evidence. `REAL_PAYMENTS_ENABLED=true` still fails configuration. Unknown external payment outcomes remain unretried until reconciled.

## FUTURE / internal unfinished work

Cross-browser/mobile and production HTTPS acceptance; load/chaos/backup-restore drills; retained secure evidence objects instead of references; evidence correction and refund/cancellation financial reconciliation; supplier file retention/key rotation; complex corrected pricing/new order workflows; broad Review Resolution Engine; parent/multi-line orders, split/reship, settlement batch; worker lease renewal; provider contracts/observability. No production automation percentage is claimed.
