"""운영자 카드 — 답 앞의 다섯 줄. 파싱은 결정적이고 없으면 없는 것이다."""

from recorder.card import LABELS, parse_card


def test_표지_다섯_줄을_사전으로_읽는다():
    answer = (
        "절차: SOP-05 §4 로 간다 [출처: SOP-05 자기 위치 상실 복구, 4. 절차]\n"
        "먼저: 로봇을 정지시킨다 [출처: SOP-05 자기 위치 상실 복구, 4. 절차]\n"
        "금지: 자동 복구를 먼저 돌리지 않는다 [출처: SOP-05 자기 위치 상실 복구, 4. 절차]\n"
        "갈림: 근거 없음\n"
        "근거 세기: E0 자기 보고 하나다\n"
        "\n## 본문\n…"
    )

    card = parse_card(answer)

    assert set(card) == set(LABELS)
    assert card["먼저"].startswith("로봇을 정지시킨다")
    assert card["갈림"] == "근거 없음"


def test_굵게와_글머리표가_있어도_읽는다():
    card = parse_card("- **절차:** SOP-01 §5\n* **먼저**: 하류를 멈춘다\n")

    assert card == {"절차": "SOP-01 §5", "먼저": "하류를 멈춘다"}


def test_표지가_없으면_빈_사전이다():
    """지어내지 않는다. 표지를 요구하기 전 판의 답에는 표지가 없어야 한다 — 그것은
    J 판 기록으로 **센다**(Task 13). 값이 비어 있는 표지(「금지: 」)도 표지가 아니다."""
    assert parse_card("## 원인 후보 순위\n…") == {}
    assert parse_card("") == {}
    assert parse_card("금지: \n먼저:   ") == {}
