# 공유 스테이션 근거 설명

Ops의 ops.station.evidence/1을 별도 입력으로 읽는다. 기존 Incident Bundle·진단 계약을 바꾸지 않는다. 상태·자원 해제·재시도는 Ops의 권위이며 설명은 실행을 호출하지 않는다.

순서: 새 시험 6개 실패 확인 → receiver.station 구현 → 6개 및 전체 회귀 검증. 기존 385개에 6개를 추가한 기대치는 391개이며 temporalio 미설치 시 385 passed, 1 skipped다. 실제 수가 다르면 그대로 기록한다.

검증: 스키마 거절, 원본 불변·필드 전달, 단일 설명 질의·검증 인용, 미검증 인용 가림, 생성 실패 분류, 같은 근거 파일 재처리 멱등성. 외부 Nexus 실측이나 현장 인증을 주장하지 않는다.

## 구현 및 검증 결과

receiver.station 파일 입력 경로와 CLI를 구현했다. 별도 시험 6개가 통과했고 전체 회귀는 `391 passed, 10 deselected`였다. Ops 명령 실행이나 자동 자원 해제 경로는 추가하지 않았다. 외부 Nexus는 호출하지 않았으며 실제 Ops E2E 산출물 `station-orchestration.json`을 입력해 COMPLETED·revision 전달과 같은 파일 재처리 시 추가 질의 없음도 확인했다. 응답 대역은 근거 없음(NO_EVIDENCE)을 반환했다.
