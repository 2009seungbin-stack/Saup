# Saup · 위탁판매 운영 기반

**Phase 10 — Real Supplier Operations. 실제 마켓·실결제 커넥터는 미승인 상태입니다.**

Python 3.12+, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, Redis와 Next.js 운영 콘솔을 사용합니다. 기존 아키텍처를 유지하면서 Excel 공급사의 발주 묶음·전송·접수·증빙 지급·배송 대기를 연결합니다. PostgreSQL이 운영 데이터의 기준이며 Excel·메신저·운영자 메모는 외부 증거입니다.

## 소스와 검증의 기준

기본 브랜치는 `main`입니다. Phase 10의 기준 main 커밋은 `b1f1f15ac3b6a396fe9f14e549f11721f49bfb7f`이며 변경은 `feat/phase10-supplier-operations`에서 리뷰합니다. main에 전체 소스가 없다는 과거 인수인계 문구는 더 이상 현재 상태가 아닙니다. 과거 ZIP은 provenance 자료이며 현재 source of truth는 Git 저장소입니다. 과거 기록은 `docs/history/`에 보존했습니다.

실행된 검사와 미실행 검사를 구분한 최신 기록은 `docs/phase10-verification.md`와 해당 커밋의 GitHub Actions 아티팩트에 있습니다. 첫 전체 GitHub Actions 실행 `36151766961`에서 188개 테스트(일반 183 + PostgreSQL 3 + Redis 2), 커버리지 90.60%, 프런트엔드 설치·타입 검사·프로덕션 빌드가 실제 통과했습니다. 검증 커밋은 `bdf716666ccb3261b4d7ba188733b0bb7c6947f7`이며 이후 변경은 새 실행 결과를 확인해야 합니다. 현재 자동화율은 측정하지 않았고 production-ready라고 선언하지 않습니다.

## 새 공급사 Excel 경로

```text
마켓/합성 주문 → 주소·재고·마진·현금·마감·위험 검증 → SupplierOrder(PENDING)
→ 발주 배치 생성(FILE_READY) → 권한 있는 파일 다운로드(EXPORTED)
→ 운영자가 실제 전송 기록(SENT) → 공급사 행별 접수/거절
→ 접수된 행의 지급 준비 → 모의 지급 또는 별도 증빙 + 관리자 확인
→ SHIPMENT_PENDING → 송장 XLSX 가져오기 → 마켓 배송 갱신 작업
```

다운로드는 전송이 아니고 전송은 접수가 아닙니다. 증빙 등록은 지급 완료가 아닙니다. 금액·운임·수량·SKU·주소 변경은 자동 지급을 중지합니다. 전송 후 취소는 공급사 확인 전 자금/재고를 임의로 해제하지 않습니다.

## 로컬 실행

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -e '.[test]'
python scripts/bootstrap.py
docker compose up --build
```

관리자 비밀번호는 bootstrap 출력으로 확인합니다. Web은 `http://localhost:3000`, API는 `http://localhost:8000`입니다. Docker 설정 제공은 Docker 기동 검증을 뜻하지 않습니다. 직접 실행, 환경 변수와 배포 주의점은 `docs/deployment.md`를 참고하세요. 마이그레이션 시 `DATABASE_URL`을 명시하고 `alembic upgrade head`를 실행합니다. 운영 마이그레이션은 `.env` 자동 로딩에 의존하지 않습니다.

## 재현 가능한 검증

```bash
python -m scripts.verify_phase10 --mode backend --output reports/phase10/local
# PostgreSQL/Redis 서비스가 없으면 BLOCKED로 기록됩니다. SQLite 통과로 대체하지 않습니다.

# 반드시 일회용 테스트 서비스에만 지정합니다.
export TEST_POSTGRES_URL='postgresql+psycopg://test_user:test_password@localhost:5432/test_database'
export TEST_REDIS_URL='redis://localhost:6379/15'
python -m scripts.verify_phase10 --mode backend --require-services --output reports/phase10/backend
python -m scripts.verify_phase10 --mode frontend --output reports/phase10/frontend

# 두 가지 지급 경로를 별도의 임시 DB에서 재현합니다. 실제 송금/마켓 호출 없음.
python -m scripts.demo_supplier_operations --output reports/phase10/synthetic.json
```

프런트엔드 잠금 파일은 커밋되어 있으며 CI와 Docker는 `npm ci`를 사용합니다. 로컬 개발은 `cd apps/web && npm ci && npm run dev`입니다. CI는 Python 3.12, PostgreSQL 16, Redis 7, Node 22를 사용하고 각 명령의 종료 코드·JUnit·coverage·소스 SHA·빌드 로그를 보존합니다.

## 주요 경로

| 경로 | 역할 |
|---|---|
| `packages/application/supplier_operations.py` | 배치·접수·증빙·취소·가드가 있는 복구 명령 |
| `packages/domain/supplier_operations.py` | 공급사 상태 전이와 엄격한 입력 계약 |
| `packages/infrastructure/schema_v2.py` | v1을 수정하지 않고 확장한 36개 런타임 테이블 |
| `migrations/versions/0002_supplier_operations.py` | 신규 8개 테이블, Review 해결 이력, 기존 Excel 주문 격리 |
| `apps/api/routers/` | 분리된 인증 및 공급사 운영 라우터 |
| `apps/web/components/suppliers/` | 배치·접수·지급 증빙 운영 화면 |
| `.github/workflows/ci.yml` | 단위/통합/프런트엔드 검증 및 실행 증거 |

## 안전성과 남은 차단 요인

`REAL_PAYMENTS_ENABLED=true`는 인증된 실지급 커넥터가 없어 여전히 시작을 거부합니다. 수동 확인은 이미 외부에서 처리된 지급에 대한 명시적 관리자 증거 기록이며 은행 API가 아닙니다. `UNKNOWN` 지급은 자동 재송금하지 않습니다. 공급사별 예치금은 서로 섞지 않습니다. 일반 JSON 목록에는 고객 주소·전화나 암호문을 내보내지 않으며, 발주 파일 자체는 암호화 보관·권한 확인·PII 반출 감사를 적용합니다.

실제 공급사 템플릿/승인된 지급처/잔액 증거와 실제 마켓 권한, Docker·브라우저 E2E, 보안/복구/운영 부하 검증은 별도 production gate입니다. 자세한 범위는 `HANDOFF.md`, `docs/supplier-excel.md`, `docs/payment-safety.md`, `docs/production-gates.md`에 있습니다.
