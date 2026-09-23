# picasso-narrator — 로봇 미들웨어 사건의 원인 설명 및 근거 인용 계층

이기종 로봇 미들웨어 [`picasso`](https://github.com/LivingLikeKrillin/picasso)가 내보내는 **사건 번들(Incident Bundle)**을 읽어 원인 후보의 정렬과 **코드 검증된 근거 인용(Verified Citation)**을 생성하는 LLM 기반 설명 계층 PoC 프로젝트입니다. 판정은 결정론적 미들웨어의 몫으로 남기고 본 계층은 설명만 담당하며, 설명의 실패·지연이 사건 처리를 막지 않도록 **별도 저장소 · 사건당 단일 호출**로 경계를 강제합니다. 골든셋 기반 자동 지표와 판독을 병기하는 **평가 체계**를 함께 제공합니다.

**사건 번들을 읽어 원인 설명과 검증된 근거 인용을 내놓는 층.** `picasso` 의 소비자이며, **`picasso` 는 이 저장소의 존재를 모른다.**

저장소가 갈린 것이 설계의 일부다. `picasso` 는 결정적으로 남고 LLM 의존이 0 이다. **경계를 코드 배치로 증명하는 것이 목적이므로, 이 저장소의 어떤 코드도 `picasso` 를 수정하지 않는다.**

## 먼저 읽을 것

| 문서 | 무엇 |
|---|---|
| [`STATE.md`](STATE.md) | **지금 어디까지 왔나.** 실물 스택·넘긴 것·반복해 틀린 것 |
| [`BOUNDARY.md`](BOUNDARY.md) | **규칙 정본.** 무엇을 하고 하지 않는가 · 권한 · 자격 · 계보 · 알림 · 적재 규약 |
| [`SEQUENCES.md`](SEQUENCES.md) | 여섯 운영 경로의 시퀀스와 세 불변식 |
| [`adr/0001`](adr/0001-LLM-층을-별도-저장소로-둔다.md) | **왜 저장소를 갈랐나.** 치르는 값과 이 결정이 틀렸다는 신호까지 |
| [`adr/0002`](adr/0002-자격은-선언으로만-생긴다.md) | **왜 밖에 있는 LLM 층이 승인 버튼을 눌러도 되나.** 자격을 계산하지 않는 이유 |
| [`eval/RESULTS.md`](eval/RESULTS.md) | 평가 결과. **한 판의 비율이 아니라 여러 판의 분포다** |
| [`correspondence/`](correspondence/) | 다른 두 저장소에 보낸 요청과 **그것이 드러낸 내 결함들** |

`BOUNDARY.md` 를 코드보다 먼저 썼다. 나중에 쓰면 이미 넘은 선을 정당화하는 문서가 된다.

## 조각은 넷이고 LLM 은 하나다

| 디렉터리 | 하는 일 | LLM |
|---|---|---|
| `receiver/` | 한 벌을 읽고 미처리분을 고른다. 멱등·재시도·실패 기록 | 없음 |
| `composer/` | 번들 필드에서 질의와 입력을 만든다 | 없음 |
| `explainer/` | Nexus 에 **한 번** 묻고 답과 인용을 받는다 | **여기만** |
| `recorder/` | 설명·인용 / 「인용 없는 답」 / 「근거 없음」 / 「생성 실패」를 갈라 붙인다 | 없음 |
| `corpus/` | 적재 스크립트와 합성 표시 규칙 | — |
| `eval/` | 골든셋과 지표 산출. **채점은 순수 함수다** — 기록만 있으면 스택 없이 다시 센다 | — |

**자율 루프가 아니다.** LLM 이 하는 일은 사건당 한 번의 질의-응답이고, 도구 호출은 Nexus 내부 검색뿐이다. `tests/test_explainer_once.py` 가 그것을 고정한다.

## 이 층이 기대는 두 저장소

| | 무엇을 받나 | 지금 상태 |
|---|---|---|
| `picasso` | 사건 번들과 탐색 대장 — **파일 내보내기**(`incidents.jsonl` · `remedy-searches.jsonl` · `manifest.json`) | **실물로 받았다.** 네 벌이 `tests/fixtures/picasso/` 에 있다 — run-1·run-2 는 같은 시나리오의 두 구동(2026-09-18, 번들 30칸), run-3 은 재발이 있는 한 벌(2026-09-20), run-4 는 사건 → 사람의 재작업 → 탐색이 서는 한 벌(2026-09-22). 적재 규약은 판 5(`resolution` 칸, 2026-09-23). 인계 지점은 저쪽 저장소의 `handoff/narrator/` 다 |
| Khala/Nexus | 하이브리드 검색과 **인용의 코드 검증** — `POST /search/answer`, Bearer | 라이브. picasso 문서와 합성 SOP 여섯이 테넌트 `picasso` 에, 이 층의 설명 다섯이 테넌트 `narrator` 에 적재돼 있다(등급 `machine_written`. 사건 바퀴는 못 읽고 운영자 질의만 읽는다 — `corpus/README.md`). 토큰은 `NEXUS_TOKEN` 환경 변수이고 값은 `.secrets/` 에만 있다. 합성 지연은 `eval/RESULTS.md` |

## 시험

```
python -m pytest
```

Windows 콘솔에서 한글 시험 이름이 깨지면 `PYTHONIOENCODING=utf-8` 을 앞에 둔다.

## 돌리는 법

한 바퀴는 명령 한 줄이다. 승인 시도는 깃발이고 기본은 끔이다(`BOUNDARY.md` §6.7).

```
python -m receiver tests/fixtures/picasso/run-1 --out out
python -m receiver tests/fixtures/picasso/run-1 --out out --approve http://127.0.0.1:8770/approvals
```

실물 스택이 있어야 한다(`STATE.md`). 없으면 마지막 판의 기록을 스택 없이 되감는다 — 새로 만드는 수는 없다.

```
python eval/replay.py --show G3 S1 Q3
```

설명 기록을 khala 가 받을 모양으로 내보내는 것은 이것이다. 문서 종류는 소유자 결정이라 기본값이 없다(`corpus/README.md`).

```
python -m corpus.export out/explanations.jsonl --out corpus/out --doc-type <이름>
```

## 평가

| # | 지표 |
|---|---|
| 1 | 1순위 원인 일치율 — **2026-09-19 부터 잰다.** picasso 가 원인이 번들에 없는 사건 넷을 내면서 열렸다. 정답을 세 번 잘못 짰던 기록도 `eval/RESULTS.md` 에 남아 있다 |
| 2 | 번들과 어긋나지 않은 비율 |
| 3 | 인용 검증 통과율 |
| 4 | **근거 없을 때 모른다고 답하는 비율** — 가장 중요하다 |
| 5 | 절차 적중 — 답이 그 사건의 절차 문서를 인용했는가. **2026-09-20 부터 잰다.** 기존 넷은 안전을 재고 이것은 쓸모를 잰다 |

그리고 비율에 안 섞이는 둘을 **수로 드러낸다** — 「설명 안 섬」과 「인용 없는 답」.
조용히 빼면 비율이 부푼다.

**수치는 작아도 되고, 낮게 나오면 낮은 채로 적는다.** 평가 체계가 있다는 것이 산출물이다.

⚠ **한 판의 비율을 품질로 읽으면 안 된다.** 같은 질의가 같은 벽 아래에서 성공도 하고
실패도 한다(상류 합성 편차 ±60초). 세 판을 겹친 표가 `eval/RESULTS.md` 맨 앞에 있다.
