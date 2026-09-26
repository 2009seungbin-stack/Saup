# Phase 10 main integration — 2026-09-26

## Integration checkpoint

PR #2 was merged into `main` at **`3983ca576d63eccd47d722457d1245c3e20c0fd6`** on 2026-09-26 at 02:14:28 UTC (11:14:28 Asia/Seoul). The merge preserves both the foundation parent `b1f1f15ac3b6a396fe9f14e549f11721f49bfb7f` and the verified feature parent `afe7a488af12e16bb284f9e9ea28f297359d9bbc`.

The feature and integration commits share tree **`631986c35a98d6d51d90c68293100aa6300ca44c`**. The supplied acceptance source archive was reconstructed as a Git tree and matched this tree before merging. The merge used an expected-head-SHA guard. A focused owner-authorized pre-merge check was recorded on the PR; it is not an independent third-party review. No existing review requests or unresolved threads were returned.

This is a fixed checkpoint, not a claim that main will never advance. Later commits require their own Actions evidence. This documentation update does not itself have a known final commit SHA or CI result until committed and executed. Consult its PR and Actions rather than assigning older results to it.

## TESTED — newly executed main CI

Run **[36211055007](https://github.com/2009seungbin-stack/Saup/actions/runs/36211055007)** checked out integration commit `3983ca576d63eccd47d722457d1245c3e20c0fd6` on a main push. Backend and frontend jobs and their substantive steps completed successfully.

| Gate | Executed result |
|---|---|
| Python 3.12.14 compileall | PASS |
| Ordinary application/API/migration/fixture tests | 204 passed |
| Real PostgreSQL 16 tests | 3 passed |
| Real Redis 7 tests | 2 passed |
| Distinct selected pytest cases in this main run | 209 passed; 0 failures/errors/skips |
| Ordinary statement coverage | 90.60379918588873%, 2,671 / 2,948 statements |
| Temporary SQLite synthetic manual-evidence transaction | PASS |
| Temporary SQLite synthetic demo-provider transaction | PASS |
| npm ci / TypeScript / Next production build | PASS / PASS / PASS |

The five service cases are excluded from the ordinary selection and executed in their separate real-service gates, not silently skipped. Synthetic results are explicit DEMO, with no real money movement. Coverage is statement coverage, not an automation rate or probability of financial correctness.

Downloaded artifacts were inspected for JUnit case counts, exit codes, source SHA and frontend changes. Archive digests matched GitHub metadata:

| Artifact | ID | SHA-256 |
|---|---|---|
| Backend | 10896130653 | `d04dedd1df38076b5965696e8f2e1cfa4650e7627bc45000f9fc0d638ae9bd52` |
| Frontend | 10895627116 | `3e290533942e8679c649d268a9b4d45b5e2aacabb742a06b767c7cf3057258ba` |

Backend source was clean before/after. The frontend build generated the recorded `apps/web/next-env.d.ts` imports/comments; the artifact retains that diff and truthfully reports a dirty post-build tree. This is not an application source or configuration change committed by the build.

## TESTED — separate pre-merge acceptance, not rerun on the integration SHA

Feature source `afe7a488af12e16bb284f9e9ea28f297359d9bbc` passed verification run **36207717815** and Docker/Chromium acceptance run **36207717819**. The latter included seven browser cases, actual application Docker builds, Compose startup/migration, and PostgreSQL/Redis/application normal restart persistence.

The integration commit has identical file content, but its push workflow does not rerun Docker/browser acceptance. `acceptance.yml` is triggered by pull requests or manual dispatch. Therefore the main CI above is **209 newly executed pytest cases**, not 216 newly executed cases. Do not alter the base verifier's `docker: NOT_TESTED` / `browser_e2e: NOT_TESTED` fields or present the seven earlier cases as new executions. See `phase10-verification.md` for earlier dated checkpoints and failed-run history.

## NOT TESTED / BLOCKED

No production deployment, production database migration, real payment, live marketplace request, or actual supplier onboarding was performed by this merge. Certified live payment and authorized marketplace/supplier access remain blocked; `REAL_PAYMENTS_ENABLED=true` still fails its gate. Production HTTPS/MFA, other browsers/mobile, load/chaos, backup restore, least-privilege DB, retention and key rotation remain separate gates.

## Repository controls and next bounded work

Main was reported unprotected during the pre-merge check. Repository permissions/settings were not changed. Configure required successful checks and review/branch rules separately; absence of protection is not evidence that checks may be skipped.

No Review Resolution Engine code, migration, provider connector or new financial command was added during integration. The next functional scope should be bounded evidence correction and paid-cancellation/refund reconciliation, preserving append-only records, exact frozen economics, admin authority, UNKNOWN handling, supplier deposit isolation and idempotency. It must not introduce a universal force-paid/state command.
