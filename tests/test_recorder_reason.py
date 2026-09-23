"""합성 실패의 사유를 가른다 — Nexus `llm/failure.py`.

**「안 받는다」와 「안 끝난다」와 「키가 없다」는 다음 행동이 다르다.** 하나로 접으면
운영자가 다시 눌러 볼 일인지 사람이 가서 고칠 일인지 구별하지 못한다.
"""

from recorder.outcome import Outcome, classify, retryable

TIMEOUT = {"llm_failed": True, "llm_failure_reason": "timeout", "citations": []}
AUTH = {"llm_failed": True, "llm_failure_reason": "auth", "citations": []}
QUOTA = {"llm_failed": True, "llm_failure_reason": "quota", "citations": []}
UNAVAILABLE = {"llm_failed": True, "llm_failure_reason": "unavailable", "citations": []}


def test_기다리면_되는_것만_다시_해본다():
    """`timeout` 은 **안 끝난 것**이라 다시 하면 될 수 있다."""
    assert retryable(TIMEOUT) is True
    assert retryable(UNAVAILABLE) is True


def test_사람이_가야_하는_것은_다시_하지_않는다():
    """`auth` 는 키가 없거나 틀린 것이라 **설정 전까지 영원히 실패한다.**
    세 번 해봐야 300초를 태우고, 기록에는 「재시도 3/3」이 남아 운영자가 다시
    눌러 볼 일처럼 보인다. 사람이 가서 고칠 일인데."""
    assert retryable(AUTH) is False
    assert retryable(QUOTA) is False


def test_모르는_사유는_다시_하지_않는다():
    """모르는 값을 일시적이라 가정하면 영원히 실패할 것을 상한까지 태운다.
    **모를 때는 덜 하는 쪽으로 기운다.**"""
    assert retryable({"llm_failed": True, "llm_failure_reason": "made_up"}) is False
    assert retryable({"llm_failed": True}) is False


def test_실패가_아니면_다시_할_일이_없다():
    assert retryable({"llm_failed": False, "citations": [{"verified": True}]}) is False
    assert classify(TIMEOUT) is Outcome.GENERATION_FAILED
