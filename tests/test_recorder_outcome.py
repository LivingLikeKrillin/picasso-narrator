"""설명이 없는 이유를 구별해 기록한다 — `BOUNDARY.md` §3.4.

응답의 모양은 2026-09-18 에 라이브 Nexus 에서 실측한 것이다(`AGENT-05` 인계).
"""

from recorder.outcome import Outcome, classify


def test_abstained_는_근거_없음이고_실패가_아니다():
    """근거 0건이면 Nexus 가 LLM 을 아예 부르지 않고 `abstained` 로 답한다.

    이것을 실패로 접으면 수신기가 재시도하고, 상한을 넘겨 「생성 실패」로 기록된다 —
    운영자가 「근거가 없는 것」과 「시스템이 고장난 것」을 구별하지 못하게 된다.
    """
    response = {
        "abstained": True,
        "abstain_reason": "no_evidence",
        "llm_failed": False,
        "citations": [],
    }

    assert classify(response) is Outcome.NO_EVIDENCE


def test_인용이_하나도_없으면_근거_없음이다():
    """`abstained` 가 거짓이어도 인용이 0 이면 근거에 닿지 않은 답이다.

    2026-09-18 실측 — 코퍼스가 커지자 「근거 0건」이 사실상 안 나온다. 벡터 경로가
    언제나 최근접을 돌려주므로 스니펫은 수십 건이 오고 `abstained` 는 거짓인데,
    모델은 「찾을 수 없습니다」라고 답하고 인용은 0 이다. `abstained` 로만 세면
    지표 3(근거 없을 때 모른다고 답하는 비율)이 거의 0 으로 나오고,
    **시스템이 모른다고 말한 적이 없다는 거짓 결론에 닿는다.**
    """
    response = {
        "abstained": False,
        "abstain_reason": "",
        "llm_failed": False,
        "weak_evidence": True,
        "evidence_snippets": [{}] * 47,
        "citations": [],
    }

    assert classify(response) is Outcome.NO_EVIDENCE


def test_생성_실패는_인용이_0_이어도_근거_없음이_아니다():
    """실패한 호출은 인용을 낼 수 없다. 그 0 을 「근거 없음」으로 읽으면
    고장이 정상 출력으로 기록되고, 코퍼스가 낡았다는 신호(§7)가 오염된다."""
    response = {
        "abstained": False,
        "llm_failed": True,
        "llm_failure_reason": "timeout",
        "citations": [],
    }

    assert classify(response) is Outcome.GENERATION_FAILED


def test_검증된_인용이_붙은_답만_설명이다():
    """인용이 있고 실패도 기권도 아니면 그것이 설명이다."""
    response = {
        "abstained": False,
        "llm_failed": False,
        "citations": [
            {"title": "ADR 40", "section": "§2.2", "verified": True},
        ],
    }

    assert classify(response) is Outcome.GIVEN


def test_근거가_맞는데_인용이_없으면_근거_없음이_아니다():
    """**「코퍼스에 없다」와 「못 댔다」는 다른 사실이다.**

    2026-09-19 실측 — 한 건이 `근거 2 §15.89` 를 인용부호까지 붙여 그대로 옮기고
    상황표 행과 `failureClass`·`unresolved`·`reachedEvidence` 를 맞춘 2,510자짜리
    인과 분석을 냈는데 `citations` 배열이 비어 있었다. 같은 시각 도메인 밖 질의는
    90자로 「검색된 문서에 없다」고 답했다. **정반대인데 같은 칸에 들어가 있었다.**

    「근거 없음」으로 적으면 **코퍼스에 대해 거짓을 말하는 것**이다. §3.4 가 그
    갈래를 「코퍼스에 관련 문서가 없다」로 정의하고 §7 이 그 비율을 「코퍼스가
    낡았다」로 읽으므로, **멀쩡한 코퍼스를 다시 적재하러 사람을 보낸다.**

    가르는 값은 Nexus 의 `weak_evidence` 다 — 근거 적합도 판정이고 「막는 판정이
    아니라 서술 계약」이라고 저쪽이 적어 뒀다(`nexus/llm/answer.py`). 실물에서
    도메인 밖 질의는 True, 근거가 맞는 사건은 False 였다.
    """
    response = {
        "abstained": False,
        "llm_failed": False,
        "weak_evidence": False,
        "evidence_snippets": [{}] * 15,
        "answer": "근거 2 §15.89 상황표 두 번째 행이 이 케이스를 정확히 기술한다 …",
        "citations": [],
    }

    assert classify(response) is Outcome.UNCITED


def test_적합도를_모르면_코퍼스가_비었다고_말하지_않는다():
    """**키가 없는 것은 「약하다」도 「튼튼하다」도 아니다**(§4.1 — null 과 키 부재).

    모를 때 「근거 없음」으로 기울면 **코퍼스에 대한 주장**을 지어내게 된다.
    「인용이 없다」는 답에 대한 주장뿐이라 더 적게 말한다 — 모를 때는 적게 말한다.
    """
    response = {"abstained": False, "llm_failed": False, "citations": []}

    assert classify(response) is Outcome.UNCITED


def test_근거가_약하면_인용이_붙어도_근거_없음이다():
    """⛔ **인용이 하나라도 있으면 `weak_evidence` 를 아예 안 봤다** (2026-09-22 에 고침).

    T0 판에서 도메인 밖 질의 셋 중 둘이 여기서 `GIVEN` 으로 떨어져 **「모른다 비율」이
    3/3 에서 1/3 로 내려갔다.** 그런데 답 셋은 산문으로 전부 모른다고 했다.

    **고치는 근거는 내 수치가 아니라 khala 의 계약이다** — 수치가 내려간 것을 보고
    분류를 넓히면 함정 1 이므로 그 자리를 밖에서 받아 왔다.

    - `weak_evidence` 는 **검색 점수**에서 나온다(`top_distance > 0.48` **그리고**
      `top_bm25 < 1.5`). **생성 전에 정해져 프롬프트에 들어가고**, 인용은 생성의
      **산출**이다. **뒤에 나온 것으로 앞의 것을 가리고 있었다**
    - 그 값이 참이면 프롬프트에 규칙이 붙고, 그 2항이 **「관련 있어 보이는 문서가 있으면
      제목만 한 줄로 알리라」**다. 제목을 한 줄 알리면 **인용이 하나 생긴다.**
      `weak=참 · 인용 1` 은 예외가 아니라 **규칙이 시킨 모양**이다

    ⚠ **뜻을 좁혀 둔다.** 이 값은 「**이번 검색이 잘 안 맞았다**」이지 「코퍼스에 없다」가
    아니다. 저쪽이 지은 질문 여섯을 돌려 보니 **둘은 코퍼스가 답을 갖고 있었고** 낱말만
    어긋나 있었다 — 「내 정규식이 못 찾은 것은 부재가 아니다」가 그쪽 머리말에 있다.
    """
    response = {
        "abstained": False,
        "llm_failed": False,
        "weak_evidence": True,
        # 규칙 2항이 시킨 「제목만 한 줄」이 인용 하나로 남는다.
        "citations": [{"doc_title": "picasso — 이기종 로봇 표준 I/F 계약과 운영 변경 체계"}],
    }

    assert classify(response) is Outcome.NO_EVIDENCE
