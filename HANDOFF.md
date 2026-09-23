# Saup 인수인계

최종 갱신: **2026-09-23 (KST)**  
저장소: **`2009seungbin-stack/Saup`**  
기본 브랜치: **`main`**  
작업 브랜치: **`feat/commerce-foundation`**

> 다음 개발자는 이 문서를 먼저 읽는다. 현재 원격 GitHub에는 전체 구현 코드가 올라가 있지 않다.

## 1. 목표와 불변 원칙

Saup는 한국 국내 식품/농산물 위탁판매를 시작점으로 하는 다중 마켓 커머스 자동화 운영 기반이다. 초기 대상은 Coupang, Temu Korea Local Seller, AliExpress Korea Local Seller/K-Venue이며, 공급사가 API를 제공하지 않는 경우 Excel 가격표·발주서·송장 파일을 사용한다.

절대 원칙:

- 운영 데이터의 source of truth는 PostgreSQL이다.
- 외부 시스템은 포트/어댑터를 통해서만 연결한다.
- 공식 문서로 확인되지 않은 마켓 API endpoint를 추측하거나 만들지 않는다.
- 권한/문서/계정 승인이 없으면 `BLOCKED_BY_CREDENTIALS` 또는 `BLOCKED_BY_PROVIDER_ACCESS`로 명시한다.
- 인터넷뱅킹 UI 자동화, 비밀번호/OTP 입력, 브라우저 클릭 송금을 구현하지 않는다.
- 가격/지급액/환불액/재고량은 deterministic rule로 결정하고 LLM이 결정하지 않는다.
- 원본 고객 주소를 임의 수정하지 않는다.
- 미정산 마켓 매출을 사용 가능한 현금으로 계산하지 않는다.
- 주문/발주/결제/환불/배송/정산 외부 작업은 idempotent해야 한다.
- `REAL_PAYMENTS_ENABLED=false`가 기본이다. 현재 공식 지급 커넥터가 없으므로 flag만 바꿔 실결제를 허용하면 안 된다.
- **95%+ 자동화는 목표이며 현재 측정된 운영 성과가 아니다.**

## 2. 현재 원격 GitHub 상태

2026-09-23 확인 기준:

- default branch: `main`
- architecture commit: `2a68351ff06ad8450c6d84f8978c3e2a4aff55db`
- feature branch: `feat/commerce-foundation`
- 원격에 확인된 핵심 구현 파일: `ARCHITECTURE.md`
- 전체 구현 코드 commit: **없음**
- 구현 PR: **없음**
- remote CI/deployment: **없음**

이전 세션에서 대량 GitHub tree write가 도구 보안 확인 단계에서 차단됐다. 차단을 우회하지 않았다.

**따라서 GitHub를 clone한 것만으로는 아래 구현본이 복원되지 않는다.**

## 3. 전달 구현 아티팩트

원본 구현 패키지:

- `Saup_Commerce_Foundation.zip`
- SHA-256: `8bbe0cc864ac1e250c9c7a30655e0558ad5178670ef2e870d7c140b5a901e0ec`

작업 보고서:

- `Saup_Work_Report.md`
- SHA-256: `01b981a08961f951114fc3ccc0278535dc8396c44a6c28cd78db113cb20469fc`

ZIP을 확보한 뒤 hash를 확인하고, `feat/commerce-foundation`에서 기존 원격 파일과 diff한 후 정상적인 리뷰/커밋 절차로 복원한다. 무조건 덮어쓰지 않는다.

ZIP의 주요 경로:

- `apps/api` — FastAPI 운영 API
- `apps/worker` — DB 작업 큐 워커
- `apps/web` — Next.js 운영 콘솔
- `packages/domain` — 순수 도메인 규칙
- `packages/application` — 주문/금융/위험/클레임/정산 오케스트레이션
- `packages/infrastructure` — DB/설정/보안
- `packages/integrations` — 포트/모의 어댑터/Excel
- `migrations` — Alembic
- `tests`, `fixtures`, `reports`, `docs`

## 4. 마지막 구현 범위

전달 ZIP 기준이며 실운영 완료를 의미하지 않는다.

- FastAPI, SQLAlchemy 2, Alembic
- 28개 DB 테이블
- 세션 인증/RBAC/CSRF/요청 제한
- 주소 암호화, 감사 로그, 검토 큐
- DB 작업 큐, bounded retry, 격리/replay
- 상품/variant/공급사/listing/가격 이력
- 공급사별 Excel profile
- 가격표 import / 발주서 export / 송장 import
- malformed/duplicate/formula 행 격리
- 명시적 주문 상태 전이
- 주문/발주/결제 중복 방지
- integer KRW + Decimal rate
- 공급사별 예치금/현금 예약
- 미정산 매출 제외
- margin guard / price spike / stock / cash / claim kill switch
- 수동 지급 승인 한도
- 내부 balanced ledger
- 클레임 evidence/deadline
- 공급사 부분 보상 / 제한 고객 환불
- expected vs actual settlement reconciliation
- manual discovery score / contribution-based experiment
- 실제 API 데이터를 읽도록 작성한 Next.js console source

## 5. 마지막 검증 결과

권위 있는 기록은 전달 ZIP의 `reports/verification.json`이다.

| 항목 | 결과 |
|---|---|
| Python | 3.13.5에서 검증, 지원 선언은 >=3.12 |
| pytest | **107개 중 105 PASS / 0 FAIL / 2 SKIP** |
| Python statement coverage | **90.65238558909445%** |
| commerce.py | 94.40789473684211% |
| finance.py | 90.1639344262295% |
| after_sales.py | 84.29319371727749% |
| suppliers/excel.py | 86.9047619047619% |
| Python compile | PASS |
| SQLite migration round-trip | PASS |
| SQLite append-only 검사 | PASS |
| 합성 vertical E2E | PASS |
| TSX syntax transpilation | PASS |
| Next production build | **미검증** — dependencies 미설치 |
| Docker Compose 전체 기동 | **미실행** |
| PostgreSQL concurrency/deferred trigger | **SKIP** |
| Redis distributed limiter | **SKIP** |
| Browser E2E | **미실행** |
| Live providers | **BLOCKED** |
| Real payment | **DISABLED** |
| Production automation rate | **미측정** |
| Production ready | **false** |

합성 E2E에서 마지막으로 확인한 결과:

- final order state: `CLOSED`
- duplicate marketplace order -> 동일 내부 주문
- duplicate supplier payment request -> 모의 외부 실행 1회
- customer refund: ₩5,000
- supplier partial recovery: ₩2,000
- simulated actual settlement: ₩14,620
- contribution after recovery: ₩320
- 7 journals balanced
- malformed file -> `FAILED`
- price-spike SKU -> internal/mock marketplace `PAUSED`

위 숫자는 합성 fixture이며 실제 매출/송금이 아니다.

## 6. 재현 명령

### Python

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install -e ".[test]"
python -m pytest -q
```

### PostgreSQL / Redis

**운영 DB/Redis에는 절대 연결하지 않는다.**

```bash
export TEST_POSTGRES_URL='postgresql+psycopg://test_user:test_password@localhost:5432/test_database'
export TEST_REDIS_URL='redis://localhost:6379/15'
python -m pytest -m 'postgres or redis' -q
```

### Frontend

전달본에는 npm lockfile이 없다. 정상 install 후 lockfile을 커밋해 재현성을 높인다.

```bash
cd apps/web
npm install
npm run typecheck
npm run build
```

### Docker

```bash
python scripts/bootstrap.py
docker compose up --build
```

구성상 Web은 `http://localhost:3000`, API는 `http://localhost:8000`이다. 이전 검증 환경에는 Docker가 없어 전체 기동 성공을 확인하지 못했다.

## 7. 다음 우선순위

### P0 — 구현본을 정상적으로 원격 복원

1. ZIP SHA-256 확인
2. `feat/commerce-foundation` checkout
3. ZIP과 원격 `ARCHITECTURE.md` diff
4. `.env`, secret, 고객 PII가 commit 대상에 없는지 확인
5. pytest 재실행
6. foundation/domain/integrations/web/docs처럼 검토 가능한 단위로 commit
7. GitHub CI에서 동일 검증 재현

### P1 — PostgreSQL/Redis 공백 닫기

- concurrent order ingest
- concurrent supplier order/payment
- deferred balanced journal
- DB append-only trigger
- deadlock/restart/recovery
- Redis distributed rate limit
- Redis outage fail-safe

SQLite 통과만으로 완료 처리하지 않는다.

### P2 — Frontend/Docker 검증

- `npm run typecheck`
- `npm run build`
- lockfile/dependency audit
- Docker clean start/restart
- 로그인/CSRF/RBAC browser E2E

### P3 — 공급사 한 곳의 실제 파일 운영 흐름

1. supplier onboarding
2. 실제 profile/version
3. 가격 import
4. 발주서 생성
5. **공급사 접수 acknowledgement**
6. 예치금/지급 증빙
7. 송장 import
8. 취소/누락/오류 해결
9. 클레임/부분보상 대사

**발주서를 export한 사실을 공급사 접수 성공으로 간주하지 않는다.**

### P4 — 복잡 실거래

- multi-line aggregate
- split shipment
- partial fulfillment
- reshipment
- partial supplier failure
- post-settlement refund
- negative settlement
- uncertain payment/refund reconciliation

### P5 — 실제 provider

공식 계정 권한과 공식 문서를 확보한 것부터 구현한다.

- Coupang
- Temu Local Seller
- AliExpress Korea
- supplier API/deposit API
- approved payment/banking/billing provider

문서/권한이 없으면 mock/contract 테스트까지만 유지한다.

## 8. External blockers

- Coupang seller credential/API authorization
- Temu Local Seller/Partner whitelist
- AliExpress Korea seller/OAuth permission
- 실제 공급사 파일 규칙/API/잔액 방식
- 승인된 payment/banking/billing/deposit provider

## 9. Internal unfinished work

credentials와 무관하게 계속 개발해야 한다.

- supplier acknowledgement workflow
- payment/deposit statement evidence
- complex Excel template/version editor
- order aggregate/split/reship
- post-settlement refund/negative settlement
- manual reconciliation UI/commands
- evidence media transport/storage
- email/webhook notification transports
- supplier quality composite score
- seasonal orchestration
- AI draft layer — 금전 결정 제외
- retention/legal hold
- key rotation
- SSO/MFA
- least-privilege DB roles
- external append-only audit
- backup/restore drill
- load/failure testing
- production observability/incident runbook

## 10. 동시성/금융 주의점

### Idempotency

중복 방지 대상:

- marketplace order ingest
- supplier order
- payment
- refund
- shipment update
- settlement ingest

같은 idempotency key를 다른 payload로 재사용하면 충돌로 거절한다.

### 불명확한 금융 결과

provider 요청 timeout 뒤 바로 재송금하지 않는다. 상태 조회/statement reconciliation으로 실행 여부를 확인하기 전에는 두 번째 지급을 금지한다.

### Listing pause

local desired state와 remote confirmed state를 분리한다. API 장애 중 local `PAUSED`를 실제 원격 판매중지 성공으로 표시하지 않는다.

### Treasury

사용 가능 현금에서 제외:

- marketplace unsettled receivable
- 증거 없는 supplier refund 예정액
- 다른 supplier에 귀속된 deposit

## 11. Production gate

다음이 닫히기 전에는 production-ready라고 표시하지 않는다.

- PostgreSQL concurrency/deferred constraints
- 최소권한 DB roles
- Redis distributed/outage tests
- Next typecheck/build/browser E2E
- dependency security audit
- Docker clean build/start/restart
- Python 3.12 regression
- migration evolution
- backup/restore drill
- webhook authenticity/replay
- provider pagination/rate limit/timeout/circuit breaker
- supplier acknowledgement/payment evidence
- complex orders/split/reship/refund/negative settlement
- retention/key rotation
- MFA/SSO or equivalent
- secrets manager
- monitoring/alerting/incident runbook

## 12. 문서 읽는 순서

구현 ZIP 복원 후:

1. `HANDOFF.md`
2. `README.md`
3. `ARCHITECTURE.md`
4. `docs/implementation-status.md`
5. `docs/production-gates.md`
6. `docs/verification.md`
7. `reports/verification.json`
8. `reports/test-results.txt`, `reports/pytest.xml`, `reports/coverage.json`
9. `reports/source-manifest.json`
10. 도메인별 문서

**대화의 숫자보다 `reports/verification.json`의 최신 값을 우선한다.**

## 13. 95% 자동화율 측정

향후 95%를 주장하려면 ordinary transaction cohort, 제외 조건, 측정 기간, 전체 denominator, 인간 개입 없는 end-to-end 거래 수를 정의한다.

사람 개입으로 포함할 것:

- 파일 수동 수집/전달
- 예치금 보충
- payment approval
- claim evidence request
- supplier 문의
- 예외 수정

**유닛 테스트 coverage를 사업 자동화율로 표현하지 않는다.**

## 14. 첫날 체크리스트

- [ ] 전달 ZIP hash 확인
- [ ] `feat/commerce-foundation` checkout
- [ ] restore 후 `git diff`
- [ ] secret/PII commit 여부 확인
- [ ] `reports/verification.json` 읽기
- [ ] Python 105 PASS / 2 SKIP 재현
- [ ] PostgreSQL/Redis를 붙여 2 SKIP 실제 실행
- [ ] Frontend typecheck/build
- [ ] Docker clean start
- [ ] browser E2E
- [ ] 실패 수정 후 구현 코드를 원격에 반영
- [ ] 공급사 1곳 acknowledgement + payment evidence 완성
- [ ] 그 뒤 live marketplace connector 추가

## 15. 한 줄 인수인계

**아키텍처는 GitHub에 남아 있지만 실제 구현은 전달 ZIP이 source artifact다. 먼저 구현본을 안전하게 원격에 복원하고 PostgreSQL/Redis/Next/Docker 검증 공백을 닫은 뒤 기능을 확장한다.**
