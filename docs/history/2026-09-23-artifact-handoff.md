> HISTORICAL ARTIFACT SNAPSHOT — not current repository or verification status.
> Remote source restoration occurred after this handoff was originally written.

# Saup 인수인계 문서

최종 갱신: **2026-09-23 (KST)**  
대상 저장소: **`2009seungbin-stack/Saup`**  
기본 브랜치: **`main`**  
작업 브랜치: **`feat/commerce-foundation`**

> 이 문서는 다음 개발자가 이전 대화 기록을 읽지 않아도 현재 상태를 정확히 파악하고 안전하게 작업을 이어가기 위한 문서다.
>
> **중요:** 현재 GitHub 원격 저장소에는 전체 구현 코드가 올라가 있지 않다. 아래 “원격 저장소와 전달 ZIP의 차이”를 먼저 읽어야 한다.

---

## 1. 프로젝트 목표

Saup는 한국 국내 식품/농산물 위탁판매를 시작점으로 하는 다중 마켓 커머스 자동화 운영 기반이다.

초기 대상 채널:

- Temu Korea Local Seller
- Coupang Marketplace
- AliExpress Korea Local Seller / K-Venue (실제 계정에서 지원되는 범위만)

공급사는 API가 없을 수 있으므로 다음 두 경로를 모두 지원해야 한다.

1. 공식 API 어댑터
2. Excel/파일 기반 대체 어댑터

핵심 목표는 일반 거래의 높은 자동화율이지만, **95%+ 자동화는 목표값이며 현재 측정된 성과가 아니다.** 금융 안전, 추적 가능성, 중복 실행 방지, 예외 격리가 자동화율보다 우선한다.

---

## 2. 절대 변경하면 안 되는 안전 원칙

다음 원칙은 구현 편의를 위해 완화하지 않는다.

- PostgreSQL이 운영 데이터의 source of truth다. Excel, 마켓 API, 공급사 포털 자체를 원장으로 취급하지 않는다.
- 외부 시스템은 포트/어댑터를 통해서만 연결한다.
- 공식 문서로 확인되지 않은 Coupang/Temu/AliExpress API endpoint를 추측하거나 만들어내지 않는다.
- 권한·문서·계정 승인이 없으면 `BLOCKED_BY_CREDENTIALS` 또는 `BLOCKED_BY_PROVIDER_ACCESS`로 명시한다.
- 인터넷뱅킹 화면 자동 로그인, 비밀번호/OTP 자동 입력, 브라우저 클릭 송금을 구현하지 않는다.
- 실제 지급은 공식 결제/은행/공급사 결제 API가 있을 때만 구현한다.
- 가격, 지급액, 환불액, 재고량 같은 금전·수량 결정은 deterministic rule로 처리한다. LLM이 결정하지 않는다.
- 원본 배송주소를 LLM이나 휴리스틱으로 임의 수정하지 않는다. 원본을 보존하고 검증만 한다.
- 미정산 마켓 매출을 사용 가능한 현금으로 계산하지 않는다.
- 외부 호출 재시도 때문에 공급사 발주/결제/환불이 두 번 실행되지 않도록 idempotency를 유지한다.
- `REAL_PAYMENTS_ENABLED=false`가 기본이다. 현재 구현은 공식 지급 커넥터가 없으므로 단순히 이 값을 `true`로 바꿔도 실결제가 실행되어서는 안 된다.
- 테스트 커버리지와 실제 사업 자동화율을 혼동하지 않는다.

---

## 3. 현재 원격 GitHub 상태 — 매우 중요

2026-09-23 확인 기준:

- 저장소: `2009seungbin-stack/Saup`
- 기본 브랜치: `main`
- 아키텍처 커밋: `2a68351ff06ad8450c6d84f8978c3e2a4aff55db`
- 작업 브랜치: `feat/commerce-foundation`
- 원격에 확인된 핵심 구현 파일: **`ARCHITECTURE.md`**
- 전체 구현 코드 커밋: **없음**
- 구현 PR: **없음**
- 원격 CI 실행 증거: **없음**
- 배포: **없음**

이전 세션에서 대량 GitHub tree write가 도구 보안 확인 단계에서 차단됐다. 차단을 우회하지 않았고, 따라서 로컬에서 작성·검증한 구현 패키지는 GitHub에 반영되지 않았다.

### 결론

**GitHub를 clone한 것만으로는 아래 구현본이 복원되지 않는다.**

다음 개발자는 먼저 전달 ZIP을 확보해 원격 코드와 비교한 뒤, 테스트를 다시 실행하고 정상적인 코드 리뷰/커밋 절차로 브랜치에 반영해야 한다.

---

## 4. 전달 구현 아티팩트

이전 세션에서 생성한 원본 구현 패키지:

- `Saup_Commerce_Foundation.zip`
- SHA-256: `8bbe0cc864ac1e250c9c7a30655e0558ad5178670ef2e870d7c140b5a901e0ec`

작업 보고서:

- `Saup_Work_Report.md`
- SHA-256: `01b981a08961f951114fc3ccc0278535dc8396c44a6c28cd78db113cb20469fc`

ZIP 내부에는 `Saup/` 프로젝트 전체가 있으며 주요 구성은 다음과 같다.

- `apps/api` — FastAPI 운영 API
- `apps/worker` — DB 기반 작업 큐 워커
- `apps/web` — Next.js 운영 콘솔 소스
- `packages/domain` — 가격/마진/주문 상태/발견 점수 등 순수 도메인 규칙
- `packages/application` — 주문, 자금, 위험, 파일, 클레임, 정산 오케스트레이션
- `packages/infrastructure` — 설정, SQLAlchemy 모델, 스키마, 보안
- `packages/integrations` — 포트, 모의 어댑터, 공급사 Excel
- `migrations` — Alembic 초기 스키마와 PostgreSQL 제약
- `tests` — 단위/워크플로/API/안전/외부 인프라 게이트 테스트
- `fixtures` — 합성 공급사 가격표와 프로필
- `docs` — 도메인/지급/Excel/마켓/클레임/정산/보안/배포/검증 문서
- `reports` — 실제 실행 당시의 pytest, coverage, demo, verification 증거

### 복원할 때

ZIP을 받은 뒤 SHA-256을 먼저 확인한다. 파일이 다르면 “같은 구현본”이라고 가정하지 않는다.

```bash
sha256sum Saup_Commerce_Foundation.zip
```

Windows PowerShell:

```powershell
Get-FileHash .\Saup_Commerce_Foundation.zip -Algorithm SHA256
```

ZIP의 `Saup/`를 작업 디렉터리로 복원한 뒤 **기존 GitHub 파일을 무조건 덮어쓰지 말고 diff를 먼저 확인**한다.

---

## 5. 마지막으로 검증된 구현 범위

전달 ZIP 기준으로 구현된 범위다. “실운영 완료”를 의미하지 않는다.

### Foundation / 보안

- FastAPI
- SQLAlchemy 2 / Alembic
- 28개 DB 테이블
- 세션 인증
- 역할 기반 접근 제어
- CSRF 검사
- 요청/파일 제한
- 주소 암호화
- 감사 로그
- 검토 큐
- DB 작업 큐/재시도/격리
- Docker/Next.js 소스

### 상품 / 공급사 / Excel

- 상품/variant/공급사/공급사 상품/마켓 listing 모델
- 공급사 가격 이력
- 공급사별 Excel mapping profile
- 가격표 import
- 공급사 주문서 export
- 송장/배송 import
- malformed row, 중복, 수식 등 오류 격리

### 주문 / 금융 / 위험

- 명시적 주문 상태 전이
- 주문 중복 방지
- 공급사 주문 중복 방지
- 결제 중복 방지
- integer KRW + Decimal 비율 계산
- 공급사별 예치금 분리
- 운영 현금 예약
- 미정산 매출 제외
- 마진 guard
- 공급사 가격 급등 kill switch
- 재고/현금/클레임 위험 중지 규칙
- 수동 지급 승인 한도
- 이중분개 방식 내부 원장

### 클레임 / 정산

- 증빙 종류/기한 검사
- 공급사 클레임 응답
- 부분 공급사 보상
- 제한된 고객 환불
- 예상/실제 settlement 대사
- statement와 실제 현금 확인 분리
- settlement mismatch 검토 큐

### Discovery / Dashboard

- 수동 입력 기반 demand/competition/supplier economics 점수
- 공헌이익 기반 experiment 상태 평가
- 실제 API를 읽도록 작성된 Next.js 운영 콘솔

---

## 6. 마지막 실제 검증 결과

기준 파일: ZIP 내부 `reports/verification.json` 및 `reports/test-results.txt`.

| 항목 | 마지막 기록 |
|---|---|
| Python | 3.13.5에서 실행, 선언 지원은 `>=3.12` |
| pytest | **107개 중 105 PASS / 0 FAIL / 2 SKIP** |
| Python statement coverage | **90.65238558909445%** |
| `commerce.py` | 94.40789473684211% |
| `finance.py` | 90.1639344262295% |
| `after_sales.py` | 84.29319371727749% |
| `suppliers/excel.py` | 86.9047619047619% |
| Python compile | PASS |
| SQLite migration upgrade→downgrade→upgrade | PASS |
| SQLite append-only 검사 | PASS |
| 합성 E2E | PASS |
| TSX syntax transpilation | PASS |
| Next.js production build | **미검증** (`next` executable 미설치) |
| Docker Compose 전체 기동 | **미실행** (환경에 Docker 없음) |
| PostgreSQL concurrency/deferred trigger | **SKIP** |
| Redis distributed rate limiter | **SKIP** |
| Browser E2E | **미실행** |
| Live provider contract | **BLOCKED** |
| 실제 지급 | **DISABLED** |
| 실제 운영 자동화율 | **미측정** |
| production ready | **false** |

### 합성 전체 거래에서 마지막으로 확인한 값

- 최종 주문 상태: `CLOSED`
- 같은 주문을 다시 넣어도 동일 내부 주문으로 처리
- 같은 공급사 지급 요청의 모의 외부 실행: 1회
- 고객 환불: ₩5,000
- 공급사 확정 부분 보상: ₩2,000
- 모의 실제 정산액: ₩14,620
- 보상 반영 후 공헌이익: ₩320
- 7개 journal 모두 내부 합계 0
- malformed file은 `FAILED`로 격리
- 가격 급등 상품은 내부/모의 마켓에서 `PAUSED`

위 금액은 합성 fixture 결과이며 실제 매출/송금이 아니다.

---

## 7. 재현 명령

### Python 회귀 테스트

```bash
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows
# .venv\Scripts\activate

python -m pip install -e ".[test]"
python -m pytest -q
```

### PostgreSQL / Redis 게이트

**실제 운영 DB/Redis에 테스트를 절대 연결하지 않는다.**

```bash
export TEST_POSTGRES_URL='postgresql+psycopg://test_user:test_password@localhost:5432/test_database'
export TEST_REDIS_URL='redis://localhost:6379/15'
python -m pytest -m 'postgres or redis' -q
```

해당 테스트는:

- 동시 주문/지급 idempotency
- PostgreSQL append-only 제약
- deferred balanced-journal 제약
- 여러 RateLimiter 인스턴스에서 Redis 분산 제한

을 확인한다.

### Frontend

현재 ZIP에는 npm lockfile이 없다. 재현성 향상을 위해 정상 install 후 lockfile을 커밋하는 것이 좋다.

```bash
cd apps/web
npm install
npm run typecheck
npm run build
```

그 뒤 인증 포함 browser E2E를 추가/실행한다.

### Docker 전체 기동

```bash
python scripts/bootstrap.py
docker compose up --build
```

구성상:

- Web: `http://localhost:3000`
- API: `http://localhost:8000`

이 명령은 전달본에 존재하지만 이전 환경에서는 Docker 자체가 없어 성공 여부를 확인하지 못했다.

### 합성 전체 시연

Docker 환경이라면:

```bash
docker compose exec api python -m scripts.demo --output /app/demo-results
```

---

## 8. 가장 먼저 해야 할 다음 작업

우선순위는 아래 순서를 권장한다.

### P0 — 전달 코드를 원격에 정상 복원

1. 원본 ZIP hash 확인
2. `feat/commerce-foundation` checkout
3. ZIP 소스와 원격 `ARCHITECTURE.md` diff 확인
4. 비밀값/.env/개인정보가 포함되지 않았는지 확인
5. 로컬 pytest 재실행
6. 작은 논리 단위로 commit하거나 검토 가능한 PR 생성
7. GitHub CI에서 동일 테스트를 재현

**대형 한 번짜리 커밋보다는 foundation/domain/integrations/web/docs 식으로 검토 가능한 단위가 낫다.**

### P1 — PostgreSQL/Redis 실환경 게이트

- 동시 주문 ingest
- 동시 supplier order
- 동시 payment
- deferred balanced journal
- append-only DB trigger
- transaction retry/deadlock/restart
- Redis 분산 rate limit
- Redis 장애 시 fail-safe 동작

SQLite 통과 결과만으로 이 항목들을 완료 처리하지 않는다.

### P2 — Frontend/Docker 완전 재현

- `npm run typecheck`
- `npm run build`
- dependency audit
- lockfile 추가
- `docker compose up --build` clean start
- 재시작 후 상태 복구
- 로그인/CSRF/RBAC browser E2E

### P3 — 공급사 1곳의 실제 파일 운영 흐름 완성

실제 마켓 API보다 먼저 한 공급사의 아래 end-to-end를 완성하는 것이 가치가 높다.

1. 공급사 onboarding
2. 실제 가격표 profile/version
3. 가격 import
4. 발주서 생성
5. **공급사가 발주를 접수했다는 명시적 acknowledgement**
6. 공급사 예치금/지급 증빙
7. 송장 import
8. 오류/누락/취소 예외 해결
9. 클레임/부분보상 대사

**파일을 export한 사실을 공급사 주문 접수 성공으로 간주하지 않는다.**

### P4 — 복잡 거래 모델

- multi-line marketplace order aggregate
- split shipment
- partial fulfillment
- reshipment
- supplier partial failure
- post-settlement refund
- negative settlement
- 미확정 지급/환불 provider reconciliation

### P5 — 실제 마켓/지급 연동

계정 권한과 공식 문서가 확보된 것부터 한다.

- Coupang
- Temu Local Seller
- AliExpress Korea
- 공급사 API/예치금 API
- 공식 payment/banking/billing provider

문서가 없거나 권한이 없으면 mock/contract 테스트까지만 유지한다.

---

## 9. 외부 차단 요소

현재 확인된 외부 blocker:

- Coupang seller credentials + 공식 API 승인
- Temu Local Seller/Partner whitelist + 실제 계정에서 허용된 API 범위
- AliExpress Korea seller/OAuth 권한
- 실제 공급사별 파일 양식/접수 규칙/API/잔액 조회 방식
- 승인된 결제/은행/공급사 billing/deposit provider

이 blocker들은 내부 미완료 항목을 숨기는 이유로 사용하면 안 된다.

---

## 10. 내부 미완료 — credentials와 무관하게 개발해야 하는 것

다음은 외부 권한이 없어도 계속 개발 가능한 미완료 영역이다.

- 공급사 수동 acknowledgement workflow
- 지급 증빙/예치금 statement 대사
- 복잡 Excel template/version 편집
- 주문 묶음/분할배송/재배송
- 부분 fulfillment
- 정산 후 환불/음수 settlement
- 수동 환불 승인 및 불일치 해결 UI
- 외부 증빙 media 저장/요청
- email/webhook notification transport
- supplier quality composite score
- 계절 상품 scheduling/orchestration
- AI draft layer (금전 결정 제외)
- data retention/legal hold
- key rotation
- SSO/MFA
- least-privilege DB roles
- 외부 append-only audit storage
- backup/restore drill
- load/failure testing
- 운영 observability/alerting

---

## 11. 구현에서 특히 조심할 동시성/금융 포인트

### Idempotency

중복 실행 방지 대상:

- marketplace order ingest
- supplier order
- payment
- refund
- shipment update
- settlement ingest

같은 idempotency key를 **다른 payload로 재사용하면 성공 처리하지 말고 충돌로 거절**해야 한다.

### 불명확한 금융 결과

결제 provider 요청 후 timeout이 났다고 바로 다시 송금하지 않는다.

1. 상태를 `UNKNOWN`/reconcile 필요 상태로 둔다.
2. provider transaction 조회 또는 statement로 실제 실행 여부 확인
3. 확정 전에는 두 번째 지급 금지

### Listing pause

- local desired state
- remote confirmed state

를 분리한다.

마켓 API 실패 중 local `PAUSED`만 보고 “실제 판매가 중지됐다”고 표시하면 안 된다.

### Treasury

사용 가능 현금에 포함하지 말 것:

- marketplace unsettled receivable
- 증거 없는 supplier refund 예정액
- 다른 supplier에 묶인 deposit

---

## 12. 운영 전 반드시 닫아야 하는 Production Gates

- PostgreSQL concurrency/deferred constraint 검증
- DB 최소권한 계정 분리
- Redis distributed limiter/outage 검증
- Next typecheck/build/browser E2E
- dependency vulnerability audit
- Docker clean build/start/restart
- Python 3.12에서도 회귀 테스트
- migration evolution 테스트
- backup/restore 실제 drill
- webhook authenticity/replay protection
- 실제 provider pagination/rate limits/timeouts/circuit breaker
- 실제 supplier acknowledgement/payment evidence
- complex order/split/reship/refund/negative settlement
- data retention + encryption key rotation
- SSO/MFA 또는 동급 운영 관리자 보호
- secrets manager
- 관측/알림/incident runbook

위 항목을 닫기 전에는 production-ready라고 표기하지 않는다.

---

## 13. 문서 우선순위

전달 ZIP을 복원했다면 다음 순서로 읽는다.

1. `HANDOFF.md` — 현재 상태와 재개 순서
2. `README.md` — 실행 방법
3. `ARCHITECTURE.md` — 불변 설계 방향
4. `docs/implementation-status.md` — phase별 구현/미구현
5. `docs/production-gates.md` — 운영 투입 전 차단 조건
6. `docs/verification.md` — 검증 범위
7. `reports/verification.json` — 마지막 기계 판독 가능한 검증 요약
8. `reports/test-results.txt`, `reports/pytest.xml`, `reports/coverage.json` — 테스트 증거
9. `reports/source-manifest.json` — 전달 소스 hash
10. 도메인별 문서 (`payment-safety`, `supplier-excel`, `claims`, `settlement`, `security` 등)

**대화에서 언급된 테스트 수나 완료율보다 `reports/verification.json`의 최신 값을 우선한다.**

---

## 14. Definition of Done에 대한 현재 위치

원래 MVP가 목표로 한 로컬 시나리오는 가격표 import → 상품/가격 변경 → 마진 계산 → 비수익 SKU 중지 → 모의 주문 → 위험/현금 검증 → 공급사 발주서 → 모의 지급 → 송장 import → 배송 반영 → 품질 클레임 → 공급사 클레임 → 환불 → 정산 → 손익 대사 → 거래 이력 → idempotency → 통합 검토 큐다.

전달 ZIP은 이 흐름의 **합성 vertical slice를 로컬 SQLite에서 통과**시켰다. 그러나 다음 이유로 아직 최종 MVP 완료/실운영 완료라고 부르지 않는다.

- PostgreSQL/Redis 게이트 미검증
- Next 전체 build/browser E2E 미검증
- Docker 전체 기동 미검증
- 공급사 실파일 acknowledgement/지급증빙 미완료
- 실제 마켓/지급 provider 미연결
- 복잡한 실거래 예외 미완료
- 실제 자동화율 미측정

---

## 15. 95% 자동화율 측정 방법을 먼저 정의할 것

향후 “95% 자동화 달성”을 주장하려면 최소한 다음을 기록한다.

- ordinary transaction cohort 정의
- 제외 조건 정의
- 측정 기간
- 전체 거래 denominator
- 사람 개입이 한 번도 없었던 end-to-end 거래 수
- 파일 수동 전달/수집
- 예치금 보충
- 지급 승인
- 클레임 증빙 요청
- 예외 수정
- 공급사 문의

같은 실제 human intervention도 모두 포함한다.

**유닛 테스트 coverage 90%를 자동화율 90%로 말하면 안 된다.**

---

## 16. 다음 개발자가 첫날에 해야 할 체크리스트

- [ ] 원본 ZIP hash 확인
- [ ] `feat/commerce-foundation` clone/checkout
- [ ] ZIP 소스 restore 후 `git diff`
- [ ] `.env`, API key, 고객 PII가 commit 대상에 없는지 확인
- [ ] `reports/verification.json` 읽기
- [ ] Python 테스트 105 PASS / 2 SKIP 상태가 재현되는지 확인
- [ ] PostgreSQL/Redis를 붙여 2 SKIP을 실제 실행으로 바꾸기
- [ ] `npm install && npm run typecheck && npm run build`
- [ ] Docker Compose clean start
- [ ] browser E2E 추가/실행
- [ ] 발견된 실패를 수정한 뒤에만 원격에 구현 코드 반영
- [ ] 공급사 1곳의 실제 acknowledgement + payment evidence 흐름 구현
- [ ] 이후에만 live marketplace connector를 계정 권한 단위로 추가

---

## 17. 인수인계 요약

현재 가장 중요한 사실은 세 가지다.

1. **아키텍처 방향은 원격 GitHub에 남아 있다.**
2. **실제 구현 및 테스트 증거는 전달 ZIP에 있고 아직 원격에 커밋되지 않았다.**
3. **다음 단계는 기능을 더 늘리는 것보다 먼저 구현본을 정상적으로 원격에 복원하고 PostgreSQL/Redis/Next/Docker 검증 공백을 닫는 것이다.**

실제 돈, 실제 고객 개인정보, 실제 마켓 계정을 연결하기 전에는 `docs/production-gates.md`의 차단 조건을 다시 검토한다.
