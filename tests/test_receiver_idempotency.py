"""멱등의 열쇠 — `BOUNDARY.md` §3.4, §8."""

import pytest

from receiver.idempotency import NoIdentity, NoRunIdentity, idempotency_key


def test_멱등의_열쇠는_실행과_해시다():
    """`digest` 하나로는 모자란다 — 같은 시드의 재실행이 같은 해시를 낸다."""
    key = idempotency_key({"digest": "abc123"}, manifest={"runId": "run-7"})

    assert key == ("run-7", "abc123")


def test_실행_식별자가_없으면_조용히_넘어가지_않는다():
    """`digest` 와 `incidentId` 는 둘 다 시드와 가상 시계에서 나오는 결정적 값이라
    재실행에서 그대로 반복된다. 그 상태로 멱등 표를 만들면 **두 번째 실행부터
    전부 「이미 본 사건」으로 접힌다.**

    적재 규약이 `manifest.json` 의 내용을 아직 정하지 않았다(picasso §6). 정해질
    때까지 **추측해 넘어가지 않고 멈춘다** — 조용히 넘어가면 데모를 두 번째
    돌리는 순간 설명이 하나도 안 붙고, 그 이유를 아무도 모른다.
    """
    with pytest.raises(NoRunIdentity):
        idempotency_key({"digest": "abc123"}, manifest={})


def test_탐색_줄은_해시가_없어_식별자로_민다():
    """탐색 기록에는 `digest` 가 없다 — 번들과 달리 해시를 계산하지 않는다.
    그래서 열쇠의 뒷자리가 `searchId` 다. 앞자리가 실행인 것은 같은 이유다."""
    record = {"searchId": "search-3", "outcome": "WITHHELD"}

    assert idempotency_key(record, manifest={"runId": "run-7"}) == ("run-7", "search-3")


def test_열쇠로_쓸_것이_없으면_멈춘다():
    """열쇠가 없는 줄을 그냥 넘기면 매 구동마다 다시 설명되거나 영영 안 된다.
    어느 쪽이든 조용하다."""
    with pytest.raises(NoIdentity):
        idempotency_key({"outcome": "NONE"}, manifest={"runId": "run-7"})
