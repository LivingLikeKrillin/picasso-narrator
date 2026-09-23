"""전송이 끊겼을 때 — `BOUNDARY.md` §3.4.

**한 줄의 실패가 한 벌을 죽이면 안 된다.** 설명이 없어도 사건 처리가 진행된다는
원칙은 이 층의 하네스 안에서도 같다.
"""

import httpx
import pytest

from explainer.ask import NexusUnavailable, ask_once
from explainer.transport import http_transport
from recorder.outcome import retryable


def test_읽기_시간초과가_새어_나가지_않는다(monkeypatch):
    """`httpx.ReadTimeout` 이 그대로 올라가면 부르는 쪽의 재시도도 기록도 지나친다 —
    골든셋 한 벌이 통째로 죽는다(2026-09-19 실측)."""

    def timing_out(*_, **__):
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(httpx, "request", timing_out)

    status, body = http_transport("POST", "http://x/y", {}, {})

    assert status != 200
    assert body["llm_failure_reason"] == "timeout"


def test_시간초과는_다시_해볼_만한_것으로_친다(monkeypatch):
    """안 끝난 것이지 못 하는 것이 아니다."""

    def timing_out(*_, **__):
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(httpx, "request", timing_out)

    _, body = http_transport("POST", "http://x/y", {}, {})

    assert retryable({"llm_failed": True, **body}) is True


def test_끊긴_것은_답이_아니다(monkeypatch):
    """`ask_once` 가 예외로 끊어 「생성 실패」로 갈 길을 낸다."""

    def dead(*_, **__):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "request", dead)
    search = lambda q: http_transport("POST", "http://x/y", {}, {"query": q})

    with pytest.raises(NexusUnavailable):
        ask_once("질의", search)


def test_끊긴_사유가_기록까지_간다(monkeypatch, export_dir):
    """**「안 끝났다」와 「끊겼다」는 다음 행동이 다르다.** 예외로 올리면서 사유를
    버리면 기록에 「unreachable」 하나만 남고, khala 가 코드를 가른 뜻이 사라진다."""
    from receiver.pipeline import explain
    from receiver.scan import scan
    from recorder.outcome import Outcome

    def timing_out(*_, **__):
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(httpx, "request", timing_out)
    search = lambda q: http_transport("POST", "http://x/y", {}, {"query": q})

    records = explain(scan(export_dir("run-1"), seen=set()), search=search, limit=2)

    assert len(records) == 13
    assert all(r.outcome is Outcome.GENERATION_FAILED for r in records)
    assert all(r.reason == "timeout" for r in records)
    assert all((r.attempts, r.limit) == (2, 2) for r in records)
