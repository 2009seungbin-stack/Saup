# Verification guide — historical foundation record (2026-09-23)

The paths and limitations below describe the original foundation ZIP, not the current Phase 10 branch. Current source-bound CI and Docker/Chromium evidence are in `phase10-verification.md` and `phase10-acceptance.md`. Do not read the historical lack of browser/PG/Redis execution as the current gate status.

Historical measured evidence in the original package:

- `reports/test-results.txt`: complete latest pytest/coverage output, including skipped infrastructure gates.
- `reports/pytest.xml`: machine-readable testcase results.
- `reports/coverage.json`: Python statement coverage only, not frontend, financial correctness probability or business automation.
- `reports/demo-result.json`: actual fresh-database synthetic workflow result.
- `reports/verification.json`: environment, build/infra distinctions and summary.
- `reports/source-manifest.json`: SHA-256 of implementation/config/test files used for this verification.

## Reproduce

```bash
python -m pytest --cov=packages --cov=apps/api --cov=apps/worker --cov-report=term-missing --cov-report=json:reports/coverage.json --junitxml=reports/pytest.xml -q
python -m compileall -q apps packages scripts migrations
alembic upgrade head --sql
node --check apps/web/next.config.mjs
# Requires resolved frontend dependencies:
cd apps/web
npm run typecheck
npm run build
```

TypeScript `transpileModule` syntax success is weaker than dependency-resolved type checking and a Next build. It cannot prove routing, hydration, cookies through proxy or browser behavior. No browser screenshot/E2E was run. SQLite migration round trips/append-only triggers were tested; PostgreSQL concurrency/deferred constraints and Redis limits have real opt-in tests but were not executed here.

The source manifest excludes runtime caches, output reports, generated XLSX, .env and dependency folders. Changing source invalidates prior results until tests are rerun. Never present a stale report as evidence for modified code.
