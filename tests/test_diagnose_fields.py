"""글 칸 둘 — 계약 0.6 §4. **두 목록은 `None` 이 아니다** — koshei 의 자동 승인 조건(`requireClean`)이
「비었다」를 본다."""

from diagnose.fields import uncited_sentences, unverified_claims

CITATIONS = [{"title": "SOP-02 안착 실패와 품번 불일치", "section": "§3", "verified": True}]


def test_인용_없는_문장을_글_그대로_센다():
    """인용은 `[출처: …]` 이거나 대괄호 안이 인용 제목으로 시작하는 것이다(khala 의 해석과 같다).
    인용만 있는 조각은 앞 문장의 것이다 — 「…한다. [출처: …]」."""
    rationale = ("전제가 관측과 맞는다 [출처: SOP-02 안착 실패와 품번 불일치, §3]. "
                 "이 기체는 자주 떨어뜨린다. "
                 "대체 슬롯이 비었다. [SOP-02 안착 실패와 품번 불일치]. "
                 "그러니 승인한다.")

    assert uncited_sentences(rationale, CITATIONS) == ["이 기체는 자주 떨어뜨린다.", "그러니 승인한다."]
    assert uncited_sentences("전제가 맞다 [출처: SOP-02, §3.2. 파지].", CITATIONS) == [], \
        "대괄호 안의 마침표에서 문장을 자르지 않는다"
    assert uncited_sentences("A다.[출처: X] B다.", CITATIONS) == ["B다."], \
        "문장이 막 끝난 자리의 인용은 끝난 문장의 것이다 — 뒤 문장을 가리지 않는다"
    assert uncited_sentences("A다 [출처: Y]. [출처: X] B다.", CITATIONS) == ["B다."]
    assert uncited_sentences("A다. [출처: X] B다. [출처: Y]", CITATIONS) == []
    assert uncited_sentences("A다. [출처: X]。 B다.", CITATIONS) == ["B다."]
    assert uncited_sentences("A다 [출처: X. B다. C다.", CITATIONS) == ["A다 [출처: X.", "B다.", "C다."], \
        "닫히지 않은 인용은 인용이 아니다 — khala 도 안 센다"


def test_이유가_없으면_인용_없는_문장은_빈_목록이다():
    """이유가 없으면 셀 문장도 없다. 그래서 이 칸이 비었다고 깨끗한 것은 아니다 — koshei 가 이유의
    유무를 함께 본다(계약 0.6)."""
    assert uncited_sentences(None, CITATIONS) == []


def test_검증_안_된_인용은_CITATION_이다():
    citations = CITATIONS + [{"title": "지어낸 문서", "section": "§9", "verified": False}]

    assert unverified_claims(citations, {"numbers": []}) == [
        {"kind": "CITATION", "text": "지어낸 문서, §9", "foundIn": None}]


def test_숫자는_찾은_곳이_있으면_그것으로_없으면_grounded_로():
    """`found_in` 이 붙은 뒤에는 근거도 답변 컨텍스트도 아닌 수만 — `[]`(어디에도 없음)과 `["query"]`(질의에만
    있음). 그 전에는 `grounded` 가 거짓인 수. ⛔ khala 결함 — 숫자 뒤 문장부호 쉼표가 `value` 에 붙는다
    (회신 16). 판정은 맞고 표시만 틀려 이 계층이 끝의 쉼표를 뗀다."""
    before = {"numbers": [{"value": "30", "grounded": True}, {"value": "15,", "grounded": False},
                          {"value": "99"}]}
    after = {"numbers": [
        {"value": "30", "grounded": True, "found_in": ["evidence", "context"]},
        {"value": "2.5", "grounded": True, "found_in": ["query"]},
        {"value": "47%", "grounded": False, "found_in": []},
        {"value": "12", "grounded": True, "found_in": ["context"]},
    ]}

    assert unverified_claims([], before) == [{"kind": "NUMBER", "text": "15", "foundIn": None},
                                             {"kind": "NUMBER", "text": "99", "foundIn": None}], \
        "근거에 있었다는 말이 없으면 걸린 수다 — 인용의 verified 와 같은 쪽으로 기운다"
    assert unverified_claims([], after) == [
        {"kind": "NUMBER", "text": "2.5", "foundIn": ["query"]},
        {"kind": "NUMBER", "text": "47%", "foundIn": []},
    ]


def test_숫자_항목이_없는_옛_응답은_개수만큼_text_가_null():
    """어느 수인지는 몰라도 있다는 것은 싣는다 — 비었다는 것이 「확인 못 한 것이 없다」여야 한다."""
    claims = unverified_claims([], {"numbers": None, "unverified_numbers": 2})

    assert claims == [{"kind": "NUMBER", "text": None, "foundIn": None}] * 2
    assert claims[0] is not claims[1], "항목은 서로 다른 사전이다"
