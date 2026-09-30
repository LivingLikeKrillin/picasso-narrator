"""검색에 쓰지 않는 자료 칸 — 계약 0.6 §3.5."""

import pytest

from diagnose.context import LIMIT, ContextTooLarge, aliases, render


def test_별칭은_A부터_ESCALATE_는_그대로다(diagnose_request):
    """**숫자를 쓰지 않는다** — khala 의 숫자 검증기가 되받아 적은 별칭을 검증 대상으로 센다."""
    candidates = diagnose_request()["candidates"]
    choose = {"candidateId": "CHOOSE_SOURCE:SEQ-RELOCATE:ENGINE-COVER-B:SEQ-IN-03.BIN-B",
              "kind": "CHOOSE_SOURCE",
              "ref": {"jobOrderId": "SEQ-RELOCATE", "material": "ENGINE-COVER-B", "missingSource": "SEQ-IN-03.BIN-A",
                      "alternative": "SEQ-IN-03.BIN-B", "searchId": "search-4"}}

    table = aliases([candidates[0], choose, candidates[1]])

    assert table == {"A": "APPROVE_REMEDY:hum-02:PATROL-1:pick_place",
                     "B": "CHOOSE_SOURCE:SEQ-RELOCATE:ENGINE-COVER-B:SEQ-IN-03.BIN-B",
                     "ESCALATE": "ESCALATE"}
    decide = {"candidateId": "OPERATOR_DECISION:exec-8:RACK-204.S06:CONFIRM_DONE", "kind": "OPERATOR_DECISION",
              "ref": {"executionId": "exec-8", "unitId": "RACK-204.S06", "decision": "CONFIRM_DONE"}}
    odd = {"candidateId": "APPROVE_REMEDY:x:y:z", "kind": "APPROVE_REMEDY",
           "ref": {"robotId": {"id": None}, "jobOrderId": True}, "sawSkillTypes": []}
    text = render([odd, choose, decide, candidates[1]], [], [])
    assert ("B · CHOOSE_SOURCE:SEQ-RELOCATE:ENGINE-COVER-B:SEQ-IN-03.BIN-B · "
            "주문 SEQ-RELOCATE 의 자재 ENGINE-COVER-B 를 원래 슬롯 SEQ-IN-03.BIN-A 대신 대체 위치 SEQ-IN-03.BIN-B 에서") in text
    assert ("C · OPERATOR_DECISION:exec-8:RACK-204.S06:CONFIRM_DONE · "
            "실행 exec-8 · 단위 RACK-204.S06 에 운영자 판단 CONFIRM_DONE") in text
    assert '기체 {"id":"모름"} · 주문 true 의 제안 조치(없음)를 승인' in text, \
        "겹친 값은 설명 경로의 질의와 같은 규칙으로 적는다 — 파이썬 표기가 새지 않는다"


def test_자료_칸은_넷을_싣는다(diagnose_request):
    """후보 · 확인 불가 · 이력 · 답하는 법 넷**만**. 스냅샷은 싣지 않는다 — 사실은 `query` 가 든다."""
    request = diagnose_request(
        unknowns=[{"subject": {"executionId": "exec-8", "unitId": "RACK-204.S06", "searchId": "search-14"},
                   "what": "LINK_BROKEN", "since": "2026-09-06T00:02:00Z", "source": "picasso"}],
        history=[{"attempt": 1, "candidatesVersion": "sha256:" + "1" * 64,
                  "diagnosis": {"outcome": "RECOMMENDED", "candidateId": "ESCALATE", "picked": None},
                  "approval": {"result": None, "by": None, "reason": None, "at": None},
                  "dispatch": None, "evidence": None,
                  "closedAs": "REDIAGNOSE", "at": "2026-09-06T00:03:00Z"}],
    )

    text = render(request["candidates"], request["unknowns"], request["history"])

    assert text.splitlines()[0] == "후보 (별칭 · 식별자 · 대상)"
    assert ("A · APPROVE_REMEDY:hum-02:PATROL-1:pick_place · "
            "기체 hum-02 · 주문 PATROL-1 의 제안 조치(pick_place)를 승인") in text
    assert "ESCALATE · ESCALATE · 사람에게 넘긴다" in text
    assert "LINK_BROKEN" in text and "exec-8" in text
    assert "2026-09-06T00:02:00Z" not in text, "시각은 싣지 않는다 — 시각의 숫자가 자료 칸에서 근거로 잡힌다"
    assert "None" not in text, "null 은 「모름」으로 적는다"
    assert "시도 1: 진단 RECOMMENDED ESCALATE · 승인 모름/모름 모름" in text
    assert "권고: 별칭 하나." in text and "이유: 한두 문장." in text
    assert "일곱 줄 모두 제목(#) · 목록 기호 · 굵게 없이 줄머리에" in text and "값은 표지와 같은 줄에 쓴다." in text, \
        "표지 줄의 꾸밈을 막는다 — 모델이 표지 줄을 제목으로 꾸몄다"
    assert "hum-02" in text and "search-1" not in text, "탐색 식별자는 추적용이라 싣지 않는다"
    assert "search-14" not in text, "확인 불가 항목의 대상에서도 탐색 식별자는 뺀다"


def test_자료_칸이_상한을_넘으면_보내지_않는다(diagnose_request):
    """khala 는 8,000자를 넘으면 422 로 거절하고 **자르지 않는다**(회신 15). 이 층도 자르지 않는다 —
    자른 후보 목록은 다른 질문이다. 먼저 세어 안 보낸다."""
    many = [{"candidateId": f"OPERATOR_DECISION:ex-{i}:u-{i}:CONFIRM_DONE",
             "kind": "OPERATOR_DECISION",
             "ref": {"executionId": f"ex-{i}", "unitId": "u" * 300, "decision": "CONFIRM_DONE"}}
            for i in range(25)]
    candidates = many + [{"candidateId": "ESCALATE", "kind": "ESCALATE", "ref": None}]

    assert LIMIT == 8000
    with pytest.raises(ContextTooLarge, match="8000"):
        render(candidates, [], [])
    many_letters = [{"candidateId": f"OPERATOR_DECISION:ex-{i}:u:CONFIRM_DONE", "kind": "OPERATOR_DECISION",
                     "ref": {"executionId": f"ex-{i}", "unitId": "u", "decision": "CONFIRM_DONE"}}
                    for i in range(27)]
    with pytest.raises(ContextTooLarge, match="26"):
        aliases(many_letters + [{"candidateId": "ESCALATE", "kind": "ESCALATE", "ref": None}])
