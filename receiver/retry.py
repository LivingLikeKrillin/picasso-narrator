"""재시도와 그 상한 — `BOUNDARY.md` §3.4.

**explainer 가 아니라 여기가 든다.** 거기서 돌면 「사건당 한 번」이 규율이 아니라
의도가 되고, 상한을 세는 자리가 둘로 갈린다.
"""

from explainer.ask import NexusUnavailable


_NOTHING = object()


class Exhausted(Exception):
    """상한까지 해봤고 안 됐다. **몇 번인지와 왜인지가 값으로 남는다.**

    「생성 실패」만 적으면 운영자가 한 번 튄 것과 계속 죽어 있는 것을 구별하지
    못한다. 기록에 「재시도 n/n」이 들어가는 이유이고, 사유가 함께 가는 이유는
    다시 누를 일인지 사람이 갈 일인지가 거기서 갈리기 때문이다.
    """

    def __init__(self, attempts, limit, reason=""):
        super().__init__(f"{attempts}/{limit}")
        self.attempts = attempts
        self.limit = limit
        self.reason = reason


def with_retries(call, limit, again=None):
    """[limit] 번까지 해본다. 되면 그 자리에서 멈춘다.

    **답이 왔어도 다시 할 만하면 다시 한다.** 합성 실패는 예외가 아니라 200 의
    강등된 답으로 오므로, 예외만 잡으면 일시적 타임아웃도 한 번에 포기한다.
    무엇을 다시 할 만한지는 부르는 쪽이 [again] 으로 준다 — 이 조각은 사유를
    해석하지 않는다.

    **기다리지 않는다.** 설명은 사건 처리의 옆이라 늦어도 막는 것이 없고, 대기를
    넣으면 이 층이 느려진 만큼 화면이 늦어진다고 오해할 자리가 생긴다. 간격이
    필요해지면 그때 부르는 쪽이 준다.
    """
    attempts = 0
    last = _NOTHING
    reason = ""
    while attempts < limit:
        attempts += 1
        try:
            value = call()
        except NexusUnavailable as unavailable:
            reason = unavailable.reason
            continue
        if again is None or not again(value):
            return value
        last = value
    if last is _NOTHING:
        raise Exhausted(attempts, limit, reason)
    return last
