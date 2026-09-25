# Saup Phase 10 인수인계

갱신 기준: 2026-09-25. 저장소 `2009seungbin-stack/Saup`, 기본 브랜치 `main`, 작업 브랜치 `feat/phase10-supplier-operations`.

## 현재 소스의 기준

main 기준 커밋은 `b1f1f15ac3b6a396fe9f14e549f11721f49bfb7f`이며 전체 구현은 원격에 존재합니다. Phase 10 변경은 작업 브랜치/PR에서 검증 후 병합할 대상이며, 이 문서가 main 병합이나 운영 배포를 주장하지 않습니다. `docs/history/`의 초기 ZIP 인수인계는 날짜가 표시된 과거 기록입니다.

## 구현 범위

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

정확한 실행 결과는 `docs/phase10-verification.md`와 소스 SHA가 일치하는 CI 아티팩트를 우선합니다. Python 3.13 로컬 결과를 Python 3.12/PG/Redis/브라우저 통과로 대체하지 않습니다. 현재 CI 성공 여부는 해당 실행을 확인해야 합니다. 재현 명령은 README와 `scripts/verify_phase10.py`에 있습니다.

내부 후속 검증: 브라우저 역할별 E2E, Docker clean build/start/restart, 부하/장애/복구, 증빙 저장소/보존 정책, 최소권한 DB/키 회전/MFA, 실제 공급사 템플릿 검수. 외부 차단: 공급사 계약·실제 파일 프로필·지급처/예치금 근거, 공식 마켓/지급 API 접근권한. `REAL_PAYMENTS_ENABLED`는 계속 차단입니다.

다음 대형 기능은 Phase 10 검증을 끝낸 뒤 결정합니다. 우선 후보는 기존 차단 상태를 안전하게 푸는 Review Resolution Engine입니다. 다중 주문행, 분할배송/재배송, 정산 배치, worker lease renewal, 실마켓 연동은 이번 변경에서 시작하지 않았습니다.
