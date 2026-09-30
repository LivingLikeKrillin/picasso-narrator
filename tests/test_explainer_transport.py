"""실물 전송의 벽 — 진단 계약 0.5 §2 「시간 벽의 순서」."""

from explainer.transport import TIMEOUT

#: khala 앱이 브리지를 기다리는 벽(초). 브리지 벽(`NEXUS_LLM_BRIDGE_TIMEOUT`, 지금 420)에 30 을 더해
#: 파생된다(khala `providers/llm.py` 의 `_BRIDGE_HEADROOM`). 이 층은 그 값을 읽을 수 없어 여기 적는다.
KHALA_APP_WALL = 450.0


def test_이_층의_벽은_khala_앱의_벽보다_60초_길다():
    """**부르는 쪽 벽이 불리는 쪽 벽보다 길어야 한다.** 거꾸로면 이 층이 먼저 포기해도 khala 의 생성은
    끝까지 돌며 브리지 자리를 물고, 다시 보내면 같은 질문이 두 번 돈다(0.4 까지 360 < 420 이었다).
    60 초는 생성 앞뒤의 몫이다 — 9월 22일 판 열다섯 건에서 검색 최대 8.4 초, 나머지 최대 7.9 초."""
    assert TIMEOUT == 510.0
    assert TIMEOUT - KHALA_APP_WALL == 60.0
