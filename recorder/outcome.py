"""설명의 갈래 — `BOUNDARY.md` §3.4."""

from enum import Enum


class Outcome(Enum):
    """설명 칸에 무엇이 들어가는가. **빈 칸 하나로 접지 않는다.**"""

    GIVEN = "GIVEN"
    #: 답은 왔는데 인용을 못 댔다. **「코퍼스에 없다」가 아니다** — 근거는 맞았고
    #: 합성이 그것을 구조화된 인용으로 못 붙인 것이다. 운영자에게는 「읽되 그대로
    #: 믿지 마라」이고, 다시 눌러 볼 일도 코퍼스를 손볼 일도 아니다.
    UNCITED = "UNCITED"
    NO_EVIDENCE = "NO_EVIDENCE"
    GENERATION_FAILED = "GENERATION_FAILED"


def classify(response):
    """Nexus 응답 하나를 갈래로 옮긴다. **새 사실을 만들지 않는다.**

    **근거에 닿았는가를 `citations` 로 본다.** `abstained` 는 근거가 0 건일 때만
    서는데, 코퍼스가 커지면 벡터 경로가 언제나 최근접을 돌려주므로 그 상태가
    사실상 안 나온다(2026-09-18 실측). 그때 오는 것은 스니펫 수십 건에 인용 0 건이고,
    그것은 **근거를 못 댄 답**이지 근거를 댄 답이 아니다.

    ⛔ **그 「못 댄 답」을 한동안 「근거 없음」으로 적었다**(2026-09-19 까지). 둘은
    정반대다 — 한쪽은 코퍼스가 못 덮은 것이고 다른 쪽은 근거가 맞았는데 합성이
    인용을 못 붙인 것이다. 접으면 §7 의 「근거 없음 비율 상승 → 코퍼스가 낡았다」가
    **멀쩡한 코퍼스를 가리킨다.** 갈래를 넷으로 나눈 이유가 바로 이것이고, 그래 놓고
    내가 접고 있었다.
    """
    # **실패를 먼저 본다.** 실패한 호출은 인용을 못 내므로, 인용 0 을 먼저 보면
    # 고장이 「근거 없음」이라는 정상 출력으로 기록된다.
    if response.get("llm_failed"):
        return Outcome.GENERATION_FAILED
    if response.get("abstained"):
        return Outcome.NO_EVIDENCE
    # **근거가 약했나를 인용보다 먼저 본다.** `weak_evidence` 는 Nexus 의 적합도
    # 판정이고 「막는 판정이 아니라 서술 계약」이다(`nexus/llm/answer.py`).
    #
    # ⛔ **전에는 인용이 0 건일 때만 이 값을 봤다**(2026-09-22 에 고침). 그 값은
    # **검색 점수에서 생성 전에** 정해져 프롬프트에 들어가고 인용은 **생성의 산출**이다 —
    # **뒤에 나온 것으로 앞의 것을 가리고 있었다.** 게다가 그 값이 참이면 프롬프트에
    # 규칙이 붙는데 그 2항이 「관련 있어 보이는 문서가 있으면 **제목만 한 줄로 알리라**」다.
    # 제목을 한 줄 알리면 **인용이 하나 생긴다.** 「약한데 인용 하나」는 예외가 아니라
    # **규칙이 시킨 모양**이다.
    #
    # ⚠ **뜻을 좁게 읽는다.** 이 값은 **「이번 검색이 잘 안 맞았다」**이지 「코퍼스에
    # 없다」가 아니다 — 저쪽이 지은 질문 여섯 중 **둘은 코퍼스가 답을 갖고 있었고**
    # 낱말만 어긋나 있었다. **「내 정규식이 못 찾은 것은 부재가 아니다.」**
    #
    # **키가 없으면 「못 댔다」로 기운다.** 모르는 채로 「근거 없음」이라 적으면 코퍼스에
    # 대한 주장을 지어내는 것이고, 「인용이 없다」는 답에 대한 주장뿐이라 더 적게 말한다.
    if response.get("weak_evidence") is True:
        return Outcome.NO_EVIDENCE
    if not response.get("citations"):
        return Outcome.UNCITED
    return Outcome.GIVEN


#: 다시 해서 될 수 있는 사유(Nexus `llm/failure.py` 의 `_TRANSIENT`).
#:
#: **나머지는 사람이 가야 한다.** `auth` 는 키가 없거나 틀린 것이고 `quota` 는 한도가
#: 찬 것이라 **설정 전까지 영원히 실패한다.** 세 번 해봐야 시간만 태우고, 기록에
#: 「재시도 3/3」이 남아 운영자가 다시 눌러 볼 일처럼 보인다.
TRANSIENT = frozenset({"rate_limit", "unavailable", "timeout"})


def retryable(response):
    """이 실패를 다시 해볼 만한가.

    **모르는 사유는 다시 하지 않는다.** 모르는 값을 일시적이라 가정하면 영원히
    실패할 것을 상한까지 태운다 — 모를 때는 덜 하는 쪽으로 기운다. 새 사유가
    생기면 여기 목록을 늘린다.
    """
    if not response.get("llm_failed"):
        return False
    return response.get("llm_failure_reason") in TRANSIENT
