"""소비 표면의 회귀 방벽.

**행동을 모는 시험이 아니라 바깥이 바뀐 것을 잡는 시험이다.** 픽스처는 2026-09-18
라이브 스택에서 뜬 전문이고, Nexus 의 응답 모양이 바뀌면 여기가 먼저 빨개진다.
"""

import pytest

from explainer.ask import NexusUnavailable, ask_once
from recorder.outcome import Outcome, classify


@pytest.mark.parametrize(
    "name, expected",
    [
        ("05-answer-with-citations", Outcome.GIVEN),
        ("06-answer-no-evidence", Outcome.NO_EVIDENCE),
        ("07-answer-nonsense", Outcome.NO_EVIDENCE),
    ],
)
def test_실물_응답이_갈래로_갈린다(nexus, name, expected):
    status, body = nexus(name)

    data = ask_once("질의", search=lambda q: (status, body))

    assert classify(data) is expected


def test_셋_중_둘은_abstained_가_거짓이다(nexus):
    """**`abstained` 로는 지표 3 을 못 센다.** 근거 없음 둘 다 `abstained` 가 거짓이고
    스니펫도 넉넉히 온다 — 코퍼스가 커지면 벡터 경로가 언제나 최근접을 돌려주기
    때문이다. 이 시험이 그 사실을 고정한다. 깨지면 셈법을 다시 본다."""
    for name in ("06-answer-no-evidence", "07-answer-nonsense"):
        _, body = nexus(name)
        data = body["data"]

        assert data["abstained"] is False
        assert data["citations"] == []


@pytest.mark.parametrize("name", ["08-error-unknown-route", "09-error-unauthorized"])
def test_오류는_봉투가_없다(nexus, name):
    """`{success, data, error, meta}` 가 아니라 `detail` 만 온다."""
    status, body = nexus(name)

    assert status != 200
    assert "data" not in body
    with pytest.raises(NexusUnavailable):
        ask_once("질의", search=lambda q: (status, body))


@pytest.mark.parametrize("name", ["05-answer-with-citations",
                                  "06-answer-no-evidence",
                                  "07-answer-nonsense"])
def test_인용을_세는_두_값이_어긋나지_않는다(nexus, name):
    """**내 대표 수치가 저쪽 값과 같은 것을 세는지 고정한다.**

    지표 3(인용 검증 통과율)은 내가 `citations[].verified` 를 세서 낸다. 저쪽도 따로
    `unverified_citations` 를 센다. 둘은 같은 사실의 앞뒤면이라 **반드시 합이 맞아야**
    한다 — `len(citations) - 검증된 수 == unverified_citations`.

    갈리면 둘 중 하나다. 저쪽이 검증 실패한 인용을 **배열에서 빼고** 보내기 시작했거나
    (그러면 내 비율은 **구조적으로 언제나 1.0** 이고 아무것도 안 재는 수가 된다),
    세는 대상이 달라진 것이다. 어느 쪽이든 **내가 그 수치를 계속 인용하면 안 된다.**

    지금은 안 빼는 것을 확인했다(`nexus/llm/citations.py` 가 `verified=False` 도 담는다).

    ⚠ **이 시험이 무엇을 못 하는지도 적는다.** 실물 픽스처 셋이 전부 `unverified=0` 이고
    둘은 인용이 0 이라, 지금 고정되는 것은 **필드가 있다는 것**과 **전부 검증된 경우의
    산수**뿐이다. 「빼고 보낸다」로 바뀌는 것은 **실물 응답에 검증 실패 인용이 처음
    나타나는 날** 걸린다 — 그 전에는 못 걸린다. 검증 실패 인용을 담은 픽스처가 생기면
    여기에 넣는다.
    """
    _, body = nexus(name)
    data = body["data"]
    citations = data["citations"]

    내가_센_검증 = sum(1 for c in citations if c.get("verified"))

    assert len(citations) - 내가_센_검증 == data["unverified_citations"]
