# Phase 10 verification record

## Source identity

Foundation main: `b1f1f15ac3b6a396fe9f14e549f11721f49bfb7f`. Feature: `feat/phase10-supplier-operations`. The 49-file implementation publication is commit `4deb09b938c62c7e1556dc1a9f496747a2a32700`; all 49 published hashes matched the locally tested source. The first full CI checked out `bdf716666ccb3261b4d7ba188733b0bb7c6947f7`, not a mock or uncommitted reconstruction. This document does not claim main merge or production deployment.

## TESTED: actual GitHub Actions checkpoint

Run **36151766961**, workflow **Phase 10 verification**, executed on **2026-09-25 UTC** against `bdf716666ccb3261b4d7ba188733b0bb7c6947f7`. Backend and frontend jobs both completed successfully. Backend completed at 15:06:36 UTC. The backend artifact reports Python **3.12.14**, a clean checked-out source tree, and the following executed results:

| Check | Measured result |
|---|---|
| Python compileall | PASS; exit 0 |
| Unit/application/API/migration suite | **183 passed**, 0 failed, 0 errors, 0 skipped; 5 service tests selected separately |
| PostgreSQL 16 integration | **3 passed**, 0 failed, 0 errors, 0 skipped |
| Redis 7 integration | **2 passed**, 0 failed, 0 errors, 0 skipped |
| Combined distinct pytest cases | **188 passed** |
| Statement coverage, ordinary suite | **90.60379918588873%**: 2,671/2,948 statements; 277 missing |
| Synthetic manual-evidence supplier transaction | PASS; accepted line SHIPPED, rejected line REJECTED |
| Synthetic demo-provider supplier transaction | PASS; accepted line SHIPPED, rejected line REJECTED |
| npm ci | PASS; exit 0; committed lockfile used |
| npm run typecheck | PASS; exit 0 |
| npm run build | PASS; exit 0; Next.js 16.3.6 production build |

Each synthetic path created exactly one Payment, one Shipment and one marketplace shipment job despite replay. The manual path created one evidence record and one confirmation; the demo path created neither. Both paths used temporary SQLite and explicitly demo marketplace responses: **no real money moved**. Separate real PostgreSQL tests exercised identical/conflicting acknowledgement races, payment preparation, evidence/confirmation uniqueness, balanced journals, shipment/job uniqueness and SQL immutability triggers. Redis tests used the actual CI service rather than an in-memory substitute.

Original artifacts: `phase10-backend-36151766961` (artifact 10871089880) and `phase10-frontend-36151766961` (artifact 10871488098). They retain JUnit XML, command exit codes/logs, coverage JSON/XML, synthetic results, source SHA and pre-check source hash manifests. The frontend checkpoint reports a dirty tree after Next generated its type/config updates; it is not described as a byte-unchanged checkout. The known `.next/dev/types/**/*.ts` include is now committed, and subsequent verifier runs also save pre/post tracked status and the exact tracked diff. Inspect the latest source-matched run after any later commit rather than reusing this checkpoint as proof for changed code.

## Measured local checkpoint (2026-09-25)

Python 3.13.5: **183 passed**, 5 service cases deliberately deselected; statement coverage **90.60%**. Compile and both synthetic transactions passed. The local working tree was a dirty source reconstruction, not the remote commit. Local PostgreSQL/Redis services and drivers were unavailable. Local npm ci failed with network/DNS access unavailable; frontend build/typecheck were not executed locally. Those local limitations are superseded only for the checks actually executed in the source-bound CI checkpoint above.

## NOT TESTED / BLOCKED

Application Docker image builds, Docker Compose startup/restart, browser E2E, load/failure/restore drills, real supplier files, live marketplace credentials and live bank/payment connectors were not verified. CI service containers do not constitute application Docker testing. Production readiness remains false and no production automation percentage is reported. Missing certified live payments continue to block `REAL_PAYMENTS_ENABLED=true`.

## Reproduction and interpretation

Run `python -m scripts.verify_phase10 --mode backend --require-services --output reports/phase10/backend` against disposable PostgreSQL/Redis and `--mode frontend` for the locked frontend build. Missing configured-service drivers fail rather than skip; the runner rejects zero or skipped selected tests as a completed gate. Command logs preserve exit codes and verification.json distinguishes FAIL, BLOCKED and PASS. Source artifacts include the exact checked-out SHA and a hash manifest; later runs additionally record tracked-source status before/after and the generated-file diff.

The lockfile preparation runs 36120258872 and 36147122117 were successful provenance steps, not application verification. Their temporary write-enabled workflows and the verified-source importer are removed from the final feature tree; normal CI has read-only repository permissions. Historical reports from the original ZIP are not Phase 10 results. Do not infer a newer run's status, main merge, browser acceptance or provider certification from this dated record.
