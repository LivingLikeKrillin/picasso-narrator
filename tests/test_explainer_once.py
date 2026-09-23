"""LLM 이 들어가는 유일한 조각 — `BOUNDARY.md` §1.5."""

from explainer.ask import ask_once


def test_사건당_질의는_한_번이다():
    """**자율 루프가 아니다.** 목표를 향해 도구를 고르며 반복하는 루프는 v1 에 없다.

    넣으려면 조회 횟수와 비용에 상한이 먼저 필요하고, 그때 `BOUNDARY.md` 를 고친다.
    그 전에 루프가 생기면 이 시험이 깨진다 — 그것이 이 시험의 목적이다.
    """
    asked = []

    def search(query):
        asked.append(query)
        return 200, {
            "success": True,
            "data": {"abstained": False, "llm_failed": False, "citations": [{"title": "x"}]},
        }

    ask_once("깨진 사전 조건: 파지 없음", search=search)

    assert len(asked) == 1
