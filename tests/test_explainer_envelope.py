"""소비 표면의 봉투 — 실물 응답으로 고정한다."""

import pytest

from explainer.ask import NexusUnavailable, ask_once


def test_오류_응답은_답이_아니다(nexus):
    """오류에는 `data` 봉투가 없고 `detail` 만 온다. 답으로 다루면 그 뒤 전부가
    키 부재로 무너지고, 무너진 자리가 「근거 없음」과 구별되지 않는다."""
    status, body = nexus("08-error-unknown-route")

    with pytest.raises(NexusUnavailable):
        ask_once("아무 질의", search=lambda q: (status, body))


def test_봉투를_한_겹_벗겨_알맹이를_준다(nexus):
    """최상위는 `{success, data, error, meta}` 이고 답은 `data` 안에 있다.

    인계 문서의 「응답 최상위 키 전수」가 실제로는 `data` 의 키였다(2026-09-18 대조).
    봉투째 넘기면 `citations` 도 `abstained` 도 한 겹 아래라 전부 부재로 읽힌다.
    """
    status, body = nexus("05-answer-with-citations")

    data = ask_once("깊이 상한은 왜 셋인가", search=lambda q: (status, body))

    assert "citations" in data
    assert len(data["citations"]) == 7
