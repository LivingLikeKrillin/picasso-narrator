"""사건에 붙는 한 건 — `BOUNDARY.md` §3.4."""

from recorder.outcome import Outcome
from recorder.record import from_answer, from_failure

KEY = ("run-1", "9760fe546d")


def test_생성_실패는_몇_번_해봤는지와_함께_적힌다():
    """「실패」만 적으면 한 번 튄 것과 계속 죽어 있는 것이 같아 보인다."""
    record = from_failure(KEY, attempts=3, limit=3)

    assert record.outcome is Outcome.GENERATION_FAILED
    assert (record.attempts, record.limit) == (3, 3)
    assert record.citations == []


def test_근거_없음은_인용이_비어도_실패가_아니다(nexus):
    """**정상 출력이다.** 실패로 적으면 「코퍼스가 낡았다」는 신호(§7)가 고장 건수로
    오염되고, 운영자는 다시 눌러 보게 된다."""
    _, body = nexus("06-answer-no-evidence")

    record = from_answer(KEY, body["data"])

    assert record.outcome is Outcome.NO_EVIDENCE
    assert record.citations == []
    assert (record.attempts, record.limit) == (0, 0)


def test_설명에는_답과_검증된_인용이_함께_붙는다(nexus):
    """인용 없이 문장만 남기면 근거를 못 대는 설명이 되고, 그것이 이 층이
    막으려던 실패다."""
    _, body = nexus("05-answer-with-citations")

    record = from_answer(KEY, body["data"])

    assert record.outcome is Outcome.GIVEN
    assert len(record.citations) == 7
    assert all(c["verified"] for c in record.citations)
    assert record.answer.strip()


def test_성공한_기록은_재시도_수를_들지_않는다(nexus):
    """「재시도 n/n」은 **생성 실패의 표지다.** 성공에 붙으면 셋의 구별이 흐려지고,
    운영자가 「됐는데 세 번 걸렸나」를 읽게 된다."""
    _, body = nexus("05-answer-with-citations")

    record = from_answer(KEY, body["data"], attempts=3, limit=3)

    assert record.outcome is Outcome.GIVEN
    assert (record.attempts, record.limit) == (0, 0)


def test_근거_없음도_재시도_수를_들지_않는다(nexus):
    """정상 출력이다. 재시도 수가 붙으면 실패처럼 보인다."""
    _, body = nexus("06-answer-no-evidence")

    record = from_answer(KEY, body["data"], attempts=2, limit=2)

    assert (record.attempts, record.limit) == (0, 0)


def test_얼마나_걸렸는지가_기록에_남는다(nexus):
    """**타임아웃을 올리면 느림이 가려진다 — 지연을 적으면 안 가려진다.**

    올리는 것 자체는 필요하다. 상류 편차가 100~180초를 오가는데 그 한가운데를
    자르면 절반이 버려진다. 다만 값이 안 남으면 「3분 걸리는 설명」이 정상으로
    굳고, §7 의 패턴 감시가 볼 것이 없어진다.
    """
    _, body = nexus("05-answer-with-citations")

    record = from_answer(KEY, body["data"], elapsed=176.3)

    assert record.elapsed == 176.3


def test_실패에도_얼마나_기다렸는지가_남는다():
    """「빨리 죽었다」와 「오래 매달렸다」는 다른 고장이다."""
    record = from_failure(KEY, attempts=2, limit=2, reason="timeout", elapsed=361.2)

    assert record.elapsed == 361.2


def test_생성이_실패하면_답을_담지_않는다():
    """**강등 응답의 본문은 설명이 아니라 근거 더미다.**

    합성이 실패하면 Nexus 가 「아래 근거를 직접 확인해주세요」와 함께 검색된 근거를
    통째로 싣는다 — 2026-09-19 실측으로 근거 블록 17개, 35KB. 사람에게는 쓸모가
    있지만 **이 층의 「설명」 칸에 들어갈 것은 아니다.** 담으면 셋이 흐려진다 —
    「생성 실패」인데 답이 있는 것처럼 보이고, 기록이 실패마다 35KB 씩 불어난다.
    """
    degraded = {
        "llm_failed": True,
        "llm_failure_reason": "timeout",
        "answer": "답변을 생성할 수 없습니다. 아래 근거를 직접 확인해주세요.\n" + "근거 " * 9000,
        "citations": [],
    }

    record = from_answer(KEY, degraded, attempts=2, limit=2)

    assert record.outcome is Outcome.GENERATION_FAILED
    assert record.answer == ""
    assert record.reason == "timeout"


def test_저쪽이_잰_값을_버리지_않는다(nexus):
    """**밖에서 초시계로 재던 것을 저쪽이 이미 재서 보내고 있었다.**

    `elapsed` 는 벽시계라 검색과 합성이 한 덩어리로 섞인다. 응답의 `timing_ms` 가
    그 둘을 갈라 놓는다 — 2026-09-19 실측으로 검색 0.1~1.8초, 합성 7~45초.
    합치면 「느리다」뿐이고, 가르면 **어디가 느린지**가 남는다.

    근거 조각은 **개수와 문서 제목만** 적는다. 본문은 35KB 라 기록에 들어갈 것이 아니고,
    「몇 개를 넣어 몇 개를 인용했나」는 개수로 이미 답이 된다. **제목은 따로 필요하다** —
    답이 어떤 문서를 안 짚었을 때 검색이 안 줬는지 답이 빠뜨렸는지는 제목이라야 갈린다
    (2026-09-20 J 판에서 그것을 못 갈랐다).
    """
    _, body = nexus("05-answer-with-citations")

    record = from_answer(KEY, body["data"], elapsed=45.5)

    assert record.diagnostics["timing"]["llm_ms"] == 45407
    assert record.diagnostics["evidence"] == 35
    docs = record.diagnostics["evidenceDocs"]
    assert docs == sorted(set(docs)), "제목은 중복 없이 정렬돼 있다"
    assert any("SOP" in d for d in docs), f"검색이 준 문서 제목이 남는다 — {docs[:3]}"


def test_실패해도_저쪽이_잰_값은_남는다():
    """**벽에 닿기까지 합성이 몇 초를 썼는지는 잘린 건에서만 보인다.**

    성공한 것만 모으면 벽 아래 분포만 남고 벽 자체는 안 보인다. 잘린 건의
    `llm_ms` 가 남아야 「벽이 어디냐」를 **저쪽 단위로** 말할 수 있다 —
    내 초시계로는 망 왕복과 재시도가 섞여 그 말을 할 수 없다.
    """
    degraded = {
        "llm_failed": True,
        "llm_failure_reason": "timeout",
        "answer": "답변을 생성할 수 없습니다.",
        "citations": [],
        "timing_ms": {"total_ms": 168, "bm25_ms": 160, "llm_ms": 180002},
        "evidence_snippets": [{"text": "근거"}] * 17,
    }

    record = from_answer(KEY, degraded, attempts=2, limit=2)

    assert record.diagnostics["timing"]["llm_ms"] == 180002
    assert record.diagnostics["evidence"] == 17


def test_갈래를_가른_값이_기록에_남는다():
    """**판정만 적고 근거를 안 적으면 다시 셀 수 없다.**

    채점은 순수 함수이고 「기록만 있으면 스택 없이 다시 센다」가 이 층의 약속이다
    (`eval/score.py`). 그런데 `UNCITED` 와 `NO_EVIDENCE` 를 가르는 값이 기록에 없으면
    **규칙을 고쳤을 때 옛 기록을 다시 판정할 수 없다** — 다시 물어야 하고, 그건
    같은 답이 온다는 보장이 없다(실물 편차 ±60초, 같은 질의가 실패도 성공도 한다).
    """
    uncited = {
        "llm_failed": False,
        "abstained": False,
        "weak_evidence": False,
        "answer": "근거 2 §15.89 가 이 경우를 적고 있다 …",
        "citations": [],
    }

    record = from_answer(KEY, uncited)

    assert record.outcome is Outcome.UNCITED
    assert record.diagnostics["weak_evidence"] is False


def test_저쪽이_잡은_미검증_수를_버리지_않는다(nexus):
    """**지어낸 숫자는 이 층이 막으려는 바로 그것이다.**

    Nexus 가 답의 유의미한 숫자가 **LLM 에게 실제로 보여준 것**에 있는지 결정론적으로
    대조해 `unverified_numbers` 로 센다(`nexus/llm/numbers.py` — 오탐보다 미탐 쪽으로
    기울여 놓은 검사다). 0 이 아니면 **답이 근거에 없는 수를 말한 것**이다.

    인용 쪽도 같이 담는다. 내 채점은 `citations[].verified` 를 세는데 저쪽도 따로
    `unverified_citations` 를 센다 — **둘이 갈리면 내 대표 수치가 틀린 것**이고,
    담아 두지 않으면 갈렸다는 사실조차 안 보인다.
    """
    _, body = nexus("05-answer-with-citations")

    record = from_answer(KEY, body["data"])

    assert record.diagnostics["unverified_citations"] == 0
    assert record.diagnostics["unverified_numbers"] == 0


def test_사건의_주체를_기록에_싣는다():
    """재발을 세려면 기록이 어느 기체·어느 분류였는지를 들어야 한다. 실패에도 든다 —
    설명이 안 섰어도 사건은 있었다."""
    from recorder.record import from_answer, from_failure

    subject = {"robotId": "hum-04", "failureClass": "GRASP_FAILED", "digest": "d1"}

    given = from_answer(("r", "d1"), {"answer": "…", "citations": [{"verified": True}]}, subject=subject)
    failed = from_failure(("r", "d1"), 3, 3, subject=subject)

    assert given.subject == subject
    assert failed.subject == subject
    assert from_answer(("r", "d2"), {"answer": "…", "citations": []}).subject == {}


def test_갈래를_가른_점수_둘도_같이_담는다():
    """⛔ **판정만 담고 그 근거가 된 점수를 안 담고 있었다** (2026-09-22).

    `weak_evidence` 는 `top_distance > 0.48` **그리고** `top_bm25 < 1.5` 일 때 선다.
    판정만 적으면 **문턱에 겨우 걸린 것과 한참 밖인 것이 같은 값으로 보인다.** 그리고
    그 문턱은 아직 가설이다 — 표본 17 이 전부 지은 것이고 중간 구간 최대(0.470)와
    문턱(0.48) 사이가 **0.010** 이다.

    **문턱을 옮길 트리거를 볼 수 있는 쪽은 질의를 지은 이쪽**이지 서버가 아니다. 그래서
    저쪽이 두 값을 응답에 실었고(`#537`), 이 층은 담아 둔다.

    ⚠ **`None` 은 0 이 아니다.** 그 경로가 **못 낸 것**이고, 담을 때 그대로 둔다 —
    0 으로 접으면 「가장 가까운 것이 딱 붙어 있었다」로 읽힌다.
    """
    scored = {
        "llm_failed": False, "abstained": False, "weak_evidence": True,
        "answer": "이 질문에 대한 내용은 검색된 문서에 없는 것으로 보입니다 …",
        "citations": [],
        "top_distance": 0.502,
        "top_bm25": 0.9,
    }
    silent = {"llm_failed": False, "abstained": False, "answer": "…", "citations": []}

    record = from_answer(KEY, scored)

    assert record.diagnostics["top_distance"] == 0.502
    assert record.diagnostics["top_bm25"] == 0.9
    # 그 판에 그 칸이 없었던 응답은 `None` 으로 남는다. 0 으로 접지 않는다.
    assert from_answer(KEY, silent).diagnostics["top_distance"] is None
