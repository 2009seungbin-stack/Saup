# Saup 인수인계 · Phase 10 기반 / Phase 11A·11B 개발

## 1.0 기능 마감 후속

기준 main `0c1cb07912c178ec136dd33514c14da2d503eba2`에서 기존 서비스에 운영 설정,
배송·환불·정산 외부 증빙, 부분 환불 상태 수정과 제한된 정산서 정정을 추가했습니다.
마이그레이션 0005/46개 테이블이며 이전 스키마는 동결 유지합니다. 최신 구현 범위와
검증 절차는 `docs/functional-closeout.md`가 우선합니다. 아래 수치는 과거 소스에만 해당합니다.

## Functional-closure development checkpoint

This change starts from verified main `c7fd4f0` and adds operational XLSX order
preview/import plus explicitly verified manual-source validation. It reuses the
existing supplier workflow without new tables/migrations. It is **not** a full
Saup 1.0 completion or live marketplace/payment enablement. The unmerged Phase 12A
draft remains separate. Scope: `docs/release-closure.md`; operation and tests:
`docs/order-intake.md`. For this source use its exact commit/Actions artifacts;
historical counts below are not current-source verification.


## Phase 11B 후속 작업 · 2026-09-26

Phase 11A head `713929a46f81bc566f3d753cdce0877a60d64aac` 위에 마켓 고객 취소 대사를 추가합니다. 다른 컴퓨터의 Phase 11B 패치는 GitHub에 올라가지 않았고 이 컴퓨터에도 없었으므로, 명세를 기준으로 재구성했습니다. 이전 로컬 결과(Python 3.13.5, 291개)는 이 소스의 증거가 아닙니다.

migration 0004/schema_v4(43개 테이블)가 append-only `marketplace_refund_evidence`, `marketplace_cancellation_statements`, `marketplace_cancellation_reconciliations`를 추가합니다. 관리자만 (1) 마켓이 이미 완료한 고객 전액 환불 증빙, (2) 모든 금액을 명시한 최종 취소 정산서를 기록하고, (3) 완료 명령이 잠금 아래 모든 불변식을 다시 읽은 뒤에만 주문을 `CANCEL_REQUESTED → CANCELLED`로 바꿉니다. 지급은 SUCCEEDED, 예약은 SPENT, 공급사 주문은 CANCELLED, 공급사 취소는 FINANCIALLY_RECONCILED로 유지합니다. 송금·환불 작업·원장 이동·재고 복원은 없습니다(배송 전에는 매출채권이 인식되지 않았기 때문). 판매자 잔여 정산이 있으면 증빙을 보존하고 별도 검토를 열며 자동 완료를 차단합니다. 같은 마켓 주문의 다른 주문행은 fail-closed로 보류합니다. 상세와 IMPLEMENTED/TESTED/NOT TESTED/BLOCKED/FUTURE 구분은 `docs/phase11b-marketplace-cancellation.md`, SHA별 실행 결과는 `docs/phase11b-verification.md`를 기준으로 하세요.

갱신 기준: 2026-09-26 병합 후. 저장소 `2009seungbin-stack/Saup`, 기본 브랜치 `main`. Phase 10 기능 PR #2는 병합되었습니다.

## Phase 11A 후속 작업 · 2026-09-26

이 브랜치는 기본 커밋 `77f5589c3ed4473cc8bca315e9e416cde162e7a0` 위에 증빙 정정·공급사 환급 대사의 제한된 해결 명령을 추가합니다. migration 0003과 전용 콘솔/API/검증을 포함하며 운영 배포는 하지 않습니다. 상세 인수인계와 미구현 범위는 `docs/phase11-review-resolution.md`를 기준으로 하세요. 아래 Phase 10 검증은 역사적 체크포인트입니다.

## 현재 소스의 기준

Phase 10의 main 통합 체크포인트는 `3983ca576d63eccd47d722457d1245c3e20c0fd6`입니다. PR #2의 검증된 head `afe7a488af12e16bb284f9e9ea28f297359d9bbc`와 파일 tree가 같습니다. 병합은 완료되었지만 운영 배포와 실결제 활성화는 하지 않았습니다. 통합 이후 문서 커밋을 포함한 최신 head는 Git과 해당 SHA의 Actions로 확인합니다. 병합 후 검증은 `docs/phase10-main-merge.md`를 기준으로 하며 아래 체크포인트는 날짜가 있는 과거 검증 기록입니다. `docs/history/`의 초기 ZIP 인수인계는 날짜가 표시된 과거 기록입니다.

## Phase 10 구현 범위 · 아래는 기반 기능 기록

`SupplierOrderIntent`, `SupplierOrderBatch`, `SupplierOrderBatchItem`, `SupplierBatchAcknowledgement`, `SupplierPaymentEvidence`, `SupplierPaymentConfirmation`, `SupplierCancellation`, `OperationalIntervention`의 8개 테이블을 추가했습니다. 기존 28개 테이블과 금융 불변식을 유지합니다. `schema_v1.py`와 migration 0001은 수정하지 않았습니다. migration 0002는 기존 Excel 주문의 외부 상태를 추정하지 않고 `LEGACY_SUPPLIER_STATE_UNVERIFIED` 검토로 격리합니다.

배치별 파일 바이트·프로필 버전·매핑·주문 조건을 고정합니다. 파일은 암호화된 DB 필드에 보관하며 다운로드만으로 접수/지급 상태가 바뀌지 않습니다. 접수 명령은 배치 전체 행을 정확히 한 번 분류하되 수락·거절을 혼합할 수 있습니다. 금액/운임/수량/SKU/주소 변경은 별도 검토로 차단합니다. 거절은 지급하지 않으며 재고를 추정해서 복구하지 않습니다.

지급 준비는 기존 주문 유효성·현금/예치금 예약·지급처·한도 가드를 재사용합니다. 운영자는 증빙 hash/reference를 등록할 수 있지만 관리자만 고정 금액/지급처/참조와 실제 지급 확인을 입력하여 확정합니다. 증빙과 확인은 별도 append-only 레코드입니다. 기존 승인 한도와 일일 한도, `UNKNOWN` 대사 규칙을 우회하지 않습니다.

전송 전 취소는 다운로드된 파일을 무효화하고 살아 있는 행만 새 배치에 넣습니다. 전송 후에는 공급사 취소 요구를 기록하며 증거 없는 외부 취소·환불·재고 복원을 하지 않습니다. 지급/증빙 노출 후 공급사 취소 확인은 금융 정산 완료가 아니고 `FINANCIAL_REVIEW`를 유지합니다.

## 운영 순서

1. 가격표/프로필과 공급사 지급처·잔액을 검증한 상태에서 주문을 검증합니다.
2. 공급사 운영 화면에서 한 공급사/한 프로필의 적격 주문을 배치로 생성합니다.
3. 발주 파일을 내려받아 실제로 전달한 뒤 채널·참조·파일 hash를 기록합니다.
4. 공급사 응답에 따라 모든 행을 접수/거절/조건변경으로 분류합니다.
5. 접수된 행만 지급 준비합니다. 수동 증빙 등록과 관리자 확인을 구분합니다.
6. 지급 완료 후 기존 송장 파일 가져오기를 사용합니다. 배송 중복/충돌 보호는 유지됩니다.
7. 취소/거절은 행 단위 상태와 검토 큐를 함께 확인합니다. 검토 ACK는 해결이 아닙니다.

## 복구 명령과 한계

`revalidate`는 관리자와 원래 조건 재확인 참조가 필요합니다. 원래 스냅샷을 바꾸지 않고 검증을 다시 수행합니다. 이 주문의 조건변경으로만 중지된 listing은 다른 위험 가드가 모두 통과할 때만 재개 요청하며 원격 상태는 UNCONFIRMED입니다. 별도 위험 사유, 취소, UNKNOWN/SENDING/지급 완료를 임의로 되돌릴 수 없습니다.

`adopt-verified-unsent`는 migration 후 기존 Excel 주문 중 실제 미전송이 외부에서 확인되고 지급/취소 이력이 없는 주문만 관리자가 PENDING으로 편입합니다. 기존 파일 상태만 보고 미전송으로 추정하지 않습니다. 주문 조건을 바꾸는 수정 발주, 잘못 등록된 증빙의 정정/보상, 지급 후 취소의 환급 대사는 범용 force-state가 아니라 후속 전용 해결 명령이 필요합니다.

## 검증과 남은 사항

검증 체크포인트 `b6dae8c1bdf4491b00c18d4e83aed49de2549693`에서 일반 204개·PostgreSQL 3개·Redis 2개와 실제 Chromium 브라우저 7개, 총 216개가 통과했습니다. 일반 CI `36207399192`와 Docker/브라우저 CI `36207399204`가 모두 성공했으며 이미지 빌드·Compose 기동·DB/Redis 포함 재시작 전후 거래 보존도 확인했습니다. 전체 원시 증거와 이전 실패·수정 기록은 `docs/phase10-verification.md`에 구분했습니다. 로컬 Python 3.13 결과를 CI Python 3.12 결과로 대체하지 않습니다. 이후 커밋은 해당 SHA의 새 검증이 필요합니다.

이전 Phase 10 인수 검증 변경은 검증 인프라와 실제 완료된 증빙의 UI 상태 표시 수정에 한정했습니다. 그때는 금융 로직·DB 마이그레이션·실결제 가드를 변경하지 않았습니다. 로그인 제한 테스트는 제한 로직을 바꾸지 않고 시계만 고정해 분 경계의 오검출을 제거했습니다.

내부 후속 검증: Firefox/WebKit·모바일, 운영 HTTPS, 부하/장애/백업 복원, 증빙 저장소/보존 정책, 최소권한 DB/키 회전/MFA, 실제 공급사 템플릿 검수. 외부 차단: 공급사 계약·실제 파일 프로필·지급처/예치금 근거, 공식 마켓/지급 API 접근권한. `REAL_PAYMENTS_ENABLED`는 계속 차단입니다.

Phase 11A는 위에 명시한 제한된 검토 해결부터 시작했습니다. 나머지 해결 범위는 전용 명령과 별도 검증이 필요합니다. 다중 주문행, 분할배송/재배송, 정산 배치, worker lease renewal, 실마켓 연동은 이번 변경에서 시작하지 않았습니다.
