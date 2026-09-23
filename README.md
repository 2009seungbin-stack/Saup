# Saup · 위탁판매 운영 기반

**상태: 로컬 검증용 MVP 기반 / 실제 마켓 판매·실결제 미승인.**

첨부 명세를 바탕으로 작성한 Python/FastAPI + PostgreSQL 설계 + Next.js 운영 콘솔입니다. 화면에 하드코딩한 매출을 보여주는 데모가 아니라, DB에 주문·발주·결제 의도·원장·클레임·정산을 기록하고 워커가 처리합니다. 외부 공급사와 마켓은 **명시적인 모의 어댑터**입니다. 운영 자동화율 95%는 측정하지 않았습니다.

## 이번 전달본의 위치

GitHub `2009seungbin-stack/Saup`에는 설계 문서가 커밋됐고 `feat/commerce-foundation` 브랜치가 생성됐습니다. 이후 일괄 코드 쓰기는 도구의 보안 확인 단계에서 차단됐습니다. **이 ZIP의 구현 코드는 GitHub에 반영되지 않았습니다.** 차단을 우회하거나 원격 CI/배포가 실행됐다고 주장하지 않습니다.

## 빠른 시작: Docker 로컬 데모

Python 3.12 이상으로 비밀값을 생성하고, Docker Compose를 실행합니다.

```bash
python scripts/bootstrap.py
docker compose up --build
```

`bootstrap.py`가 출력한 관리자 비밀번호로 `http://localhost:3000`에 로그인합니다. API는 `http://localhost:8000`, 개발용 OpenAPI는 `/docs`입니다. DB와 Redis는 호스트에 포트를 공개하지 않습니다. 최초 실행 시 마이그레이션·관리자 생성·합성 농산물 5종 등록이 진행됩니다.

**검증 구분:** 이 실행 환경에는 Docker, PostgreSQL, Redis와 Next.js 설치 의존성이 없어 Compose 전체 기동 및 Next 프로덕션 빌드는 실행하지 못했습니다. Docker 설정은 제공하지만 성공했다고 단정하지 않습니다. 먼저 `docs/production-gates.md`를 확인하세요.

## Python만으로 검증

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[test]"
python -m pytest -q
```

테스트는 일회용 SQLite DB와 합성 개인정보를 사용합니다. 실제 금융 API를 호출하지 않습니다. PostgreSQL 동시성 및 Redis 분산 제한 테스트는 서비스 연결 변수가 없으면 **SKIP**됩니다. SQLite 통과를 PostgreSQL 통과로 해석하면 안 됩니다.

```bash
# 일회용 테스트 서비스에만 지정하세요. 실제 운영 DB를 사용하지 마세요.
export TEST_POSTGRES_URL='postgresql+psycopg://test_user:test_password@localhost:5432/test_database'
export TEST_REDIS_URL='redis://localhost:6379/15'
python -m pytest -m 'postgres or redis' -q
```

## 모의 거래 전체 시연

새로운 데모 DB에서 다음 명령을 실행합니다. 기존 데모 데이터는 자동 삭제하거나 초기화하지 않습니다.

```bash
docker compose exec api python -m scripts.demo --output /app/demo-results
```

시연 과정: 가격표 가져오기 → 동일 주문 2회 수신 → 위험/현금 검증 → 공급사 발주 → 모의 지급 → 발주서 내보내기 → 송장 파일 가져오기 → 배송 완료 → 품질 클레임 → 공급사 부분 보상 → 고객 환불 → 정산 대사 → 입금 확인 → 거래 종료 → 잘못된 파일 격리 → 가격 급등 판매중지.

이 명령은 마지막에 가격 급등을 주입해 해당 상품을 중지합니다. **다시 실행하려면 별도의 새 데모 DB를 사용하세요.** 기존 운영 데이터를 지우도록 설계하지 않았습니다. `reports/demo-result.json`은 이번 환경에서 실제로 실행한 결과입니다.

## 로컬 API/워커 직접 실행

`.env`의 `DATABASE_URL`을 `sqlite:///./saup.db`, `RATE_LIMIT_BACKEND`를 `memory`로 바꾸고, 다른 비밀값은 유지합니다. SQLite는 **단일 워커 개발·테스트용**입니다.

```bash
# 마이그레이션은 환경변수 DATABASE_URL을 우선 사용합니다.
# .env만 바꾼 경우 기본 alembic.ini도 동일한 sqlite:///./saup.db 입니다.
alembic upgrade head
python -m scripts.init_db --demo
uvicorn apps.api.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
# 별도 터미널
python -m apps.worker.main
# 프론트엔드: 별도 터미널
cd apps/web
npm install
npm run dev
```

배포용 마이그레이션에서 `.env`를 자동 로드하지 않으므로 `DATABASE_URL`을 명시적으로 주입하세요. API 인증에는 세션 쿠키와 CSRF 토큰, `PUBLIC_ORIGIN` 일치가 필요합니다. 기본 프론트엔드가 이를 처리합니다.

## 주요 경로

| 경로 | 내용 |
|---|---|
| `packages/domain` | 원 단위 금액, Decimal 수수료율, 가격/마진, 주문 전이, 수요·경쟁 점수 |
| `packages/application` | 주문 오케스트레이션, 원장/자금 예약, 가격·재고/클레임 위험, 파일 처리, 환불/정산 |
| `packages/infrastructure` | 28개 테이블, 암호화, 인증 보조 함수, 환경설정 |
| `packages/integrations` | 공통 포트, 영속 모의 공급사·마켓·지급, 실연동 차단, Excel 프로필 |
| `apps/api` | 인증·권한·CSRF·제한·운영 조회·파일 업로드 API |
| `apps/worker` | DB 작업 큐, 임대, 제한된 재시도, 격리 및 재처리 |
| `apps/web` | 실제 API를 조회하는 한국어 데스크톱 운영 화면 |
| `migrations` | 동결 초기 스키마, 감사/원장 변경 방지, PostgreSQL 이연 균형 검사 |
| `tests`, `fixtures`, `reports` | 회귀 테스트, 합성 엑셀, 실행 증거 |

## 안전상 반드시 알아야 할 점

`REAL_PAYMENTS_ENABLED=false`가 기본입니다. 이 버전은 공식 지급 어댑터가 없으므로 `true`로 바꿔도 시작을 거부합니다. 미정산 채권과 정산 명세는 사용 가능한 은행 현금이 아닙니다. 공급사 예치금은 해당 공급사에만 사용할 수 있습니다. 지급 응답이 불명확하면 재송금하지 않습니다.

판매중지는 내부 희망 상태와 마켓 확인 상태를 따로 표시합니다. API 장애 중 `UNCONFIRMED`를 실제 판매중지 성공으로 표시하지 않습니다. 파일 내보내기만으로 공급사 접수·지급 완료를 기록하지 않습니다.

원본 주소는 검증만 하며 변경하지 않고 암호화해서 보관합니다. 기본 조회 응답에는 주소·전화번호가 없습니다. 발주서 다운로드는 권한 확인 및 감사 기록이 남는 개인정보 반출입니다.

## 현재 부족한 부분

공식 마켓/결제 연동, Excel 공급사 수동 접수 확인·지급 증빙의 완전한 실무 워크플로, 주문 묶음/분할배송, 분쟁·재배송 전체 처리, 환불 결과 불명확 상태의 공급자별 대사, 불일치 정산 해결 UI, AI 초안 기능, 생산용 관측/복구/성능·보안 검증은 완성되지 않았습니다. 인증·규칙·원장이 있다고 해서 즉시 실제 상거래에 투입할 수 있는 것은 아닙니다.

상세 구현 범위: `docs/implementation-status.md` · 측정 구분: `docs/automation-coverage.md` · 다음 검증: `docs/production-gates.md`.
