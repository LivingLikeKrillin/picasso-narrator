"""결과 넷의 판정 — 계약 0.6 §4 「판정 순서」. 위에서부터 처음 걸리는 것이 결과다."""

import pytest

from diagnose.judge import DiagnoseFailed, judge
from recorder.record import from_answer

KEY = ("ep-1", 1, "sha256:" + "0" * 64)
TABLE = {"A": "APPROVE_REMEDY:hum-02:PATROL-1:pick_place", "ESCALATE": "ESCALATE"}


def test_약한_근거는_표지보다_먼저_NO_GROUNDS(khala_data):
    """약한 근거면 khala 시스템 프롬프트가 첫 문장에서 그것을 말하게 해 「권고:」와 부딪힌다(회신 15).
    이 판정이 표지보다 먼저 보므로 부딪혀도 결과가 흔들리지 않는다. 표지 값은 기록용으로 남는다."""
    verdict = judge(from_answer(KEY, khala_data(weak_evidence=True)), TABLE)

    assert (verdict.outcome, verdict.candidate_id, verdict.picked) == ("NO_GROUNDS", None, None)
    assert (verdict.raw_pick, verdict.resolved) == ("A", TABLE["A"]), "기록은 모든 답의 표지와 그 풀이를 든다"
    assert judge(from_answer(KEY, khala_data(abstained=True)), TABLE).outcome == "NO_GROUNDS"


def test_검증된_인용이_없으면_UNCITED(khala_data):
    """**설명 경로보다 엄하다.** 설명은 인용이 하나라도 붙으면 답으로 치지만 권고는 승인자가 누를 근거라
    꾸러미에 있던 문서를 하나는 대야 한다."""
    unverified = [{"title": "지어낸 문서", "section": "§1", "verified": False}]

    verdict = judge(from_answer(KEY, khala_data(citations=unverified)), TABLE)
    assert verdict.outcome == "UNCITED" and (verdict.raw_pick, verdict.resolved) == ("A", TABLE["A"])
    assert judge(from_answer(KEY, khala_data(citations=[])), TABLE).outcome == "UNCITED"


def test_표지가_없으면_picked_가_null_인_후보_밖(khala_data):
    """형식을 어긴 것도 후보를 가리키지 못한 것이다. koshei 는 `picked` 가 null 이어도 받는다."""
    data = khala_data(answer="절차: 근거 없음.\n\n본문.")

    verdict = judge(from_answer(KEY, data), TABLE)

    assert (verdict.outcome, verdict.candidate_id, verdict.picked, verdict.raw_pick, verdict.resolved) == \
        ("OUT_OF_CANDIDATES", None, None, None, None)


def test_별칭이_맞으면_RECOMMENDED(khala_data):
    verdict = judge(from_answer(KEY, khala_data()), TABLE)

    assert (verdict.outcome, verdict.candidate_id, verdict.picked) == \
        ("RECOMMENDED", "APPROVE_REMEDY:hum-02:PATROL-1:pick_place", None)
    assert (verdict.raw_pick, verdict.resolved) == ("A", TABLE["A"])


def test_목록_밖이면_표지_값_그대로_후보_밖(khala_data):
    data = khala_data(answer="권고: 재부팅\n이유: 근거가 있다 [출처: X, §1].")

    verdict = judge(from_answer(KEY, data), TABLE)

    assert (verdict.outcome, verdict.candidate_id, verdict.picked) == ("OUT_OF_CANDIDATES", None, "재부팅")
    empty = judge(from_answer(KEY, khala_data(answer="권고:\n이유: 근거가 있다 [출처: X, §1].")), TABLE)
    assert (empty.outcome, empty.picked) == ("OUT_OF_CANDIDATES", ""), "표지 뒤가 비면 빈 글자다 — null 은 표지가 없을 때만"


def test_ESCALATE_를_고르면_RECOMMENDED(khala_data):
    """koshei 가 이것을 `ESCALATE_RECOMMENDED` 로 ESCALATED 에 보낸다(설계 §5)."""
    data = khala_data(answer="권고: ESCALATE\n이유: 근거가 어느 후보도 받치지 않는다 [출처: X, §1].")

    verdict = judge(from_answer(KEY, data), TABLE)

    assert (verdict.outcome, verdict.candidate_id) == ("RECOMMENDED", "ESCALATE")
    headed = judge(from_answer(KEY, khala_data(answer="## 권고: ESCALATE\n\n## 이유\n근거가 비었다 [출처: X, §1].")),
                   TABLE)
    assert (headed.outcome, headed.candidate_id) == ("RECOMMENDED", "ESCALATE"), "제목으로 꾸민 표지 줄도 표지 줄이다"


def test_생성_실패는_값이_아니라_예외다(khala_data):
    """값으로 돌리면 Temporal 이 재시도할 기회를 잃는다. 재시도할 만한지는 khala 의 사유가 정한다 —
    일시적인 셋(`rate_limit` · `unavailable` · `timeout`)만 재시도, 모르는 사유는 재시도 안 함."""
    for reason, again in (("timeout", True), ("unavailable", True), ("quota", False), ("other", False)):
        with pytest.raises(DiagnoseFailed) as raised:
            judge(from_answer(KEY, khala_data(llm_failed=True, llm_failure_reason=reason)), TABLE)
        assert (raised.value.reason, raised.value.retryable) == (reason, again)
    with pytest.raises(DiagnoseFailed) as raised:
        judge(from_answer(KEY, khala_data(llm_failed=True, llm_failure_reason=None)), TABLE)
    assert (raised.value.reason, raised.value.retryable) == ("unreachable", False), "사유 없는 실패는 재시도 안 함"
