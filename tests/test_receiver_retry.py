"""재시도와 그 상한은 수신기가 든다 — `BOUNDARY.md` §3.4.

explainer 는 사건당 한 번만 묻는다. 거기서 돌면 「한 번」이 규율이 아니라 의도가
되고, 상한을 세는 자리가 둘로 갈린다.
"""

import pytest

from explainer.ask import NexusUnavailable
from receiver.retry import Exhausted, with_retries


def test_상한을_넘기면_횟수와_함께_포기한다():
    """「생성 실패(재시도 n/n)」로 적으려면 **몇 번 해봤는지**가 있어야 한다.
    횟수 없이 「실패」만 적으면 운영자가 한 번 튄 것과 계속 죽어 있는 것을
    구별하지 못한다."""
    calls = []

    def flaky():
        calls.append(1)
        raise NexusUnavailable("timeout")

    with pytest.raises(Exhausted) as caught:
        with_retries(flaky, limit=3)

    assert len(calls) == 3
    assert caught.value.attempts == 3
    assert caught.value.limit == 3


def test_도중에_되면_거기서_멈춘다():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 2:
            raise NexusUnavailable("한 번 튀었다")
        return {"citations": [{"title": "x"}]}

    result = with_retries(flaky, limit=3)

    assert len(calls) == 2
    assert result["citations"]


def test_답이_왔어도_다시_할_만하면_다시_한다():
    """**합성 실패는 200 으로 온다.** 예외가 아니라 강등된 답이라, 예외만 잡으면
    일시적 타임아웃도 한 번에 포기한다."""
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            return {"llm_failed": True, "llm_failure_reason": "timeout"}
        return {"llm_failed": False, "citations": [{"verified": True}]}

    result = with_retries(flaky, limit=3, again=lambda v: v.get("llm_failed"))

    assert len(calls) == 3
    assert result["citations"]


def test_다시_할_만하지_않으면_그대로_돌려준다():
    """`auth` 를 상한까지 태우면 시간만 버리고 기록이 「재시도 3/3」이 된다."""
    calls = []

    def dead():
        calls.append(1)
        return {"llm_failed": True, "llm_failure_reason": "auth"}

    result = with_retries(dead, limit=3, again=lambda v: v.get("llm_failure_reason") == "timeout")

    assert len(calls) == 1
    assert result["llm_failure_reason"] == "auth"
