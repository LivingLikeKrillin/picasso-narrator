# 진단 계약 고정 예제 — 계약 0.6 §8

| 폴더 | 정본 | 무엇 |
|---|---|---|
| `requests/` | **koshei** | koshei 가 실제 투영 함수(`koshei.episode.diagnosisRequest`)로 picasso 인계본 run-1 줄에서 지은 요청 넷의 **바이트 사본**. 손으로 고치지 않는다. 새 판은 koshei 저장소 `episode/src/test/resources/contract/diagnosis/requests/` 에서 다시 복사한다 |
| `khala/` | narrator | 시나리오마다 고정한 가짜 khala 답(`/search/answer` 봉투의 `data`). **손으로 쓴 모양의 예다** — 절 이름과 옮긴 의무는 합성 절차서와 대 봤고 인용 · 수 항목의 모양은 khala 코드에 맞췄지만 모델의 실제 답이 아니다. 응답에 안 실리는 `evidence_snippets` 는 비워 뒀다 |
| `responses/` | **narrator** | 사본 요청을 진단 함수(`run_diagnosis`)에 넣고 가짜 답을 물려 **지은** 응답 넷. 손으로 쓰지 않는다. koshei 가 복사해 대조한다 |

응답이 박는 것은 **이 층의 결정적인 풀이**(표지 · 판정 · 글 칸 · 두 목록)이지 모델의 행동이 아니다. `tests/test_contract_fixtures.py` 가
지금 코드가 짓는 응답과 파일의 바이트가 같은지 본다. 의도한 변화면 다시 짓는다 — 그 판은 일부러 빨갛다:

    NARRATOR_UPDATE_FIXTURES=1 PYTHONIOENCODING=utf-8 python -m pytest tests/test_contract_fixtures.py -q
    PYTHONIOENCODING=utf-8 python -m pytest tests/test_contract_fixtures.py -q

다시 지었으면 koshei 에 알린다 — 그쪽 사본이 낡는다. koshei 가 요청을 다시 지어 알리면 사본을 다시 가져와 응답을 다시 짓고 되알린다.

| 예제 | picasso run-1 줄(첫 줄이 에피소드를 연 줄) | 후보 | 응답 |
|---|---|---|---|
| `01-recommended` | incident-1 · search-1(FOUND) | `APPROVE_REMEDY` · `ESCALATE` | `RECOMMENDED` — 두 목록이 빈 권고 |
| `02-no-grounds` | search-2(NONE) | `ESCALATE` 만 | `NO_GROUNDS` — 근거 적합도가 낮은 답(`weak_evidence`) |
| `03-out-of-candidates` | search-4(SOURCE_MISSING, 대체 자리 하나) | `CHOOSE_SOURCE` · `ESCALATE` | `OUT_OF_CANDIDATES` — 목록에 없는 자리를 고름, 검증 못 한 인용 하나 |
| `04-unknown` | incident-6(linkBroken) | `ESCALATE` · `OPERATOR_DECISION`(`CONFIRM_DONE`) · `unknowns` 에 `LINK_BROKEN` | `RECOMMENDED` — 현물 확인 |

⚠ **01 은 모양의 예다.** 줄 짝은 사람이 골랐고(koshei README) incident-1 은 search-1 이 찾은 조치가 실행되다 깨진 줄이라, 01 은 방금 실패한
조치를 다시 권한다. 절차서로 보면 이 줄 짝의 다음 걸음은 사람에게 넘기는 것이다 — SOP-01 §5.1 은 원 위치의 자재를 먼저 육안으로
확인하게 하고, 재시도도 실패하면 반복하지 않고 사람이 작업 지시를 다시 내게 한다(§5.1 은 `GRASP_FAILED` 의 절이고 incident-1 은
`PAYLOAD_LOST` 다 — §2 가 범위에 넣되 따로 절이 없다). 01 은 「깨끗한 권고의 응답 모양」을 보이는 것이지
자동 승인될 만한 권고의 예가 아니다.

요청 사본의 출처: koshei 저장소 브랜치 `feat/episode-core`, 요청 파일을 마지막으로 바꾼 커밋 `5baac54`(`2026-09-30`). 응답의 시간
칸(`elapsedSeconds`)은 시험이 시계를 고정해 박은 값이고, narrator 판(`narratorCommit`)은 계약 §4 의 예와 같은 대역 `0000000` 이다.
가짜 답의 판 칸 셋(`prompt_version` `73536dc7c9c0` · `corpus_version` `d462b22017d6` · `search_fingerprint` `b071397c854c`)은 khala
일곱 변경이 다 선 뒤(`bfc3f95`, 2026-09-30)의 라이브 값이다 — khala 가 프롬프트 코드 · 코퍼스 · 검색 설정을 바꾸면 달라진다.
