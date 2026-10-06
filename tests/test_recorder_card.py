"""운영자 답변 카드 — 답 앞의 다섯 줄. 파싱은 결정적이고 없으면 없는 것이다."""

from recorder.card import LABELS, head_window, parse_card


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
    """지어내지 않는다. 라벨을 요구하기 전 실행의 답에는 라벨이 없어야 한다 — 그것은
    J 실행 기록으로 **센다**(Task 13). 값이 비어 있는 라벨(「금지: 」)도 라벨이 아니다."""
    assert parse_card("## 원인 후보 순위\n…") == {}
    assert parse_card("") == {}
    assert parse_card("금지: \n먼저:   ") == {}


#: 끝까지 한 번(2026-10-04)의 머리 모양 — 라벨 줄마다 빈 줄. 근거 세기가 13번째 줄이다.
SPACED = (
    "권고: ESCALATE\n\n이유: 관측이 없다 [출처: X, §7].\n\n"
    "절차: SOP-01 §5 [출처: SOP-01, 5. 절차]\n\n먼저: 하류를 멈춘다 [출처: SOP-01, 5. 절차]\n\n"
    "금지: SUCCEEDED 로 두지 않는다 [출처: SOP-01, 5. 절차]\n\n갈림: liveHold 값\n\n"
    "근거 세기: 사실에 그 칸이 없다 [출처: Y, §6]\n\n후보별 근거는 다음과 같다.\n\n금지: 본문의 문장\n"
)


def test_빈_줄로_띄운_머리는_열두_줄을_넘겨도_이어진다():
    """⛔ **끝까지 한 번의 답변 카드가 넷이었다 (2026-10-04).** 라벨 줄마다 빈 줄을 띄우면 다섯째 라벨이 13번째
    줄로 밀린다. 앞 12줄 안의 첫 라벨 줄부터 12번째 줄까지가 라벨 줄과 빈 줄뿐이면 헤더 창은 그 뒤로 라벨 줄과 빈 줄이
    이어지는 데까지 늘어난다.
    **글이 있는 줄이 끼면 끝난다** — 본문의 「금지:」는 여전히 답변 카드가 아니다."""
    card = parse_card(SPACED)

    assert set(card) == set(LABELS)
    assert card["근거 세기"].startswith("사실에 그 칸이 없다")
    assert card["금지"].startswith("SUCCEEDED"), "본문의 금지 줄이 머리의 것을 덮지 않는다"

    lines = SPACED.splitlines()
    window = head_window(lines)
    assert lines[window[-1] + 1] == "후보별 근거는 다음과 같다.", "글이 있는 줄에서 창이 끝난다"

    prose = "\n".join(["본문 문장이다."] * 12) + "\n\n근거 세기: 늦은 표지"
    assert parse_card(prose) == {}, "앞 12줄에 표지가 없으면 창이 안 늘어난다"

    interrupted = ("권고: ESCALATE\n이유: x\n절차: P\n먼저: F\n금지: N\n갈림: B\n\n본문 첫 문장이다.\n\n정리하면:\n"
                   "- 금지: 본문 글머리표\n- 먼저: 본문 글머리표\n- 근거 세기: 본문 글머리표 늦은\n\n끝.")
    assert "근거 세기" not in parse_card(interrupted), "머리 사이에 본문 글이 끼면 창이 안 늘어난다"
