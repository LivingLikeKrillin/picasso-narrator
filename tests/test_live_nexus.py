"""실물 스택에 붙여 보는 시험.

**기본 시험군은 픽스처로 돈다.** 인프라가 있어야만 도는 시험은 CI 에서 조용히
사라지므로, 여기서는 **배선이 실제로 닿는지**만 본다. `-m live` 로 돌린다.
"""

import os

import pytest

from explainer.ask import ask_once
from explainer.client import nexus_client
from explainer.transport import http_transport
from recorder.outcome import Outcome
from recorder.record import from_answer

BASE = "http://localhost:8000"
# ⛔ 개발 토큰을 글자로 들고 있었다 — 잴 뿐인 층에 필요 없는 권한이 딸린 신원이었다 (khala 실측 2026-09-23). 값은 환경에서만 온다.
TOKEN = os.environ.get("NEXUS_TOKEN")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not TOKEN, reason="NEXUS_TOKEN 이 없다. 값은 .secrets/nexus-tokens.env 에 있다"),
]


def _ask(query, tenant="picasso"):
    search = nexus_client(BASE, token=TOKEN, tenant=tenant, transport=http_transport)
    return ask_once(query, search)


def test_배선이_닿고_갈래가_나온다():
    """**스택의 건강과 무관하게 참이어야 한다.** 답이 오든 실패가 오든 근거가
    없든, 이 층은 셋 중 하나로 기록한다. 그게 이 배선의 계약이다."""
    record = from_answer(("live", "x"), _ask("대안 탐색의 깊이 상한은 왜 세 걸음인가"))

    assert record.outcome in tuple(Outcome)


def test_LLM_이_살아_있으면_인용이_붙는다():
    """**LLM 이 죽어 있으면 건너뛴다 — 다만 건너뛴 사실이 보인다.**

    조용히 통과시키면 「인용이 붙는다」가 한 번도 확인되지 않은 채 초록이 된다.
    합성이 이 층의 의존이지 이 층의 몫이 아니라서 실패로도 적지 않는다.
    """
    data = _ask("대안 탐색의 깊이 상한은 왜 세 걸음인가")
    if data.get("llm_failed"):
        pytest.skip(f"Nexus 합성 불가: {data.get('llm_failure_reason')}")

    record = from_answer(("live", "x"), data)

    assert record.outcome is Outcome.GIVEN
    assert record.citations
    assert all("verified" in c for c in record.citations)


def test_근거_없는_질의는_실패가_아니라_근거_없음이다():
    data = _ask("오늘 부산 날씨 알려줘")
    if data.get("llm_failed"):
        pytest.skip(f"Nexus 합성 불가: {data.get('llm_failure_reason')}")

    record = from_answer(("live", "y"), data)

    assert record.outcome is Outcome.NO_EVIDENCE
    assert record.citations == []
