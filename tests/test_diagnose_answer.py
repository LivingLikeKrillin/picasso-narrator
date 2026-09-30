"""답의 머리 줄 — 계약 0.6 §4 「판정 순서」 4 · 5 와 「글 칸」."""

from diagnose.answer import body, card_items, head_value, resolve

TABLE = {"A": "APPROVE_REMEDY:hum-02:PATROL-1:pick_place", "ESCALATE": "ESCALATE"}


def test_권고_줄은_앞_12줄의_첫_표지_줄이다():
    """첫 줄만 보지 않는다 — khala 프롬프트의 규칙 둘(약한 근거는 첫 문장에서 · 여러 부분이면 몇
    부분인지)이 표지 앞에 줄을 세울 수 있다(khala 회신 15). 본문 한가운데의 「권고:」는 머리 줄이 아니다.
    **첫 표지 줄이 정한다** — 값이 비어도 뒤의 표지 줄로 넘어가지 않는다(계약 §4 판정 5).
    줄머리의 제목 기호(`#`)는 목록 기호 · 굵게처럼 꾸밈이다 — 첫 실물 진단에서 모델이 「## 권고: ESCALATE」로 썼다(2026-09-30).
    제목 아래 다음 문단은 「이유:」 줄이 아니다."""
    answer = "세 부분입니다.\n권고: A\n이유: 근거가 있다 [출처: X, §1].\n"

    assert head_value(answer, "권고") == "A"
    assert head_value(answer, "이유") == "근거가 있다 [출처: X, §1]."
    assert head_value("권고:\n권고: A", "권고") == ""

    headed = "## 권고: ESCALATE\n\n## 이유\n근거가 있다 [출처: X, §1]."
    assert head_value(headed, "권고") == "ESCALATE"
    assert head_value("### **권고**: A", "권고") == "A"
    assert head_value(headed, "이유") is None, "제목 아래 문단은 이유 줄이 아니다 — 이유를 안 댄 것으로 친다"


def test_표지가_없으면_None_이다():
    """없으면 없는 것이다 — 빈 글자로 적지 않는다. 13번째 줄의 표지는 머리 줄이 아니다."""
    assert head_value("원인 후보는 둘이다.", "권고") is None
    assert head_value("\n" * 12 + "권고: A", "권고") is None
    assert head_value(None, "이유") is None


def test_이유와_카드와_본문을_가른다(khala_data):
    answer = khala_data()["answer"]

    assert card_items(answer) == [
        {"label": "절차", "text": "파지 상태를 먼저 확인한다 [출처: SOP-02 안착 실패와 품번 불일치, §5]."},
        {"label": "먼저", "text": "근거 없음."},
        {"label": "금지", "text": "근거 없음."},
        {"label": "갈림", "text": "근거 없음."},
        {"label": "근거 세기", "text": "로봇 자체 보고 하나다."},
    ]
    assert head_value(answer, "이유").startswith("탐색이 찾은 조치의 전제가 관측과 맞는다")
    assert body(answer) == "## 원인 후보\n후보 ① — 파지물 낙하."
    assert body("권고: A\n이유: 없다.\n\n## 원인\n- 먼저: 파지를 본다\n본문.") == \
        "## 원인\n- 먼저: 파지를 본다\n본문.", "글이 있는 줄에서 머리가 끝난다 — 본문의 글머리표는 본문이다"
    assert body("권고: A\n이유: 없다.") is None, "표지 줄뿐이면 본문이 없다"
    assert body("세 부분입니다.\n권고: A\n이유: 없다.\n\n---\n\n## 원인\n본문.") == "## 원인\n본문.", \
        "본문은 표지 줄들 뒤다 — 표지 앞 머리말은 본문이 아니다(계약 §4)"
    assert body("표지 없는 답.") == "표지 없는 답.", "표지가 없으면 답 전체가 본문이다"
    live = ("## 권고: ESCALATE\n\n## 이유\n근거가 비었다 [출처: X, §7].\n\n---\n\n"
            "절차: 승인면 절차 [출처: X, §7].\n먼저: 첫 걸음.\n\n## 원인 후보\n본문.")
    assert body(live).startswith("## 이유\n근거가 비었다") and "절차: 승인면 절차" in body(live), \
        "제목 아래 문단으로 쓴 이유는 머리를 끝낸다 — 그 문단과 뒤의 구분선 · 다섯 표지 줄이 본문에 남는다(첫 실물 진단의 모양)"


def test_하나만_가리켜야_받는다():
    """**하나만 가리켜야 한다.** 「A 아니면 ESCALATE」 · 「A 또는 B」에서 A 를 고르면 모델이 망설인 것을
    이 층이 정한 것이 되고 후보 밖 비율이 그만큼 가려진다. 같은 후보를 풀어 적은 것은 받는다. 별칭이나
    식별자 전체를 받는다 — 긴 식별자를 옮겨 적은 것도 맞으면 맞다."""
    assert head_value("**권고:** `A`", "권고") == "`A`"
    assert resolve("`A`", TABLE) == TABLE["A"]
    assert resolve("(A)", TABLE) == TABLE["A"] and resolve("[A]", TABLE) == TABLE["A"]
    assert resolve("**A** (APPROVE_REMEDY:hum-02:PATROL-1:pick_place)", TABLE) == TABLE["A"]
    assert resolve("APPROVE_REMEDY:hum-02:PATROL-1:pick_place.", TABLE) == TABLE["A"]
    assert resolve("ESCALATE", TABLE) == "ESCALATE"
    assert resolve("A 아니면 ESCALATE", TABLE) is None
    assert resolve("A 또는 B", TABLE) is None, "목록에 없는 별칭을 함께 적어도 망설인 것이다"
    assert resolve("후보 A", TABLE) is None, "형식 밖은 후보 밖이다 — 너그럽게 읽지 않는다"
    assert resolve("A 아니면 B를", TABLE) is None, "토씨를 떼고 보면 둘째 후보가 보인다"
    assert resolve("A (ESCALATE도 고려)", TABLE) is None
    assert resolve("A 아니면 Escalate", TABLE) is None and resolve("A 또는 b", TABLE) is None, \
        "망설임은 대소문자를 가리지 않고 본다"
    assert resolve("A를 권한다", TABLE) == TABLE["A"] and resolve("A (A를 고른다)", TABLE) == TABLE["A"]
    assert resolve("a", TABLE) is None
