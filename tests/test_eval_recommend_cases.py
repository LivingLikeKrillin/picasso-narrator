"""권고 측정의 사례 — 설계서 `docs/superpowers/specs/2026-09-30-권고-측정.md` §0 · §2 · §7. 스택 없이 돈다.

**사례 파일과 요청 사본은 답을 보기 전에 얼린다.** 편집 도구의 지킴이는 스크립트로 쓴 파일을 못 보므로 여기서 해시를
박는다 — 바꿔야 하면 [SCORING_HASH] 를 함께 고치고 근거를 커밋 본문에 적는다(함정 1).
"""

import hashlib
import json

from diagnose.context import LIMIT, aliases, render
from diagnose.contract import parse_request
from diagnose.core import query_text
from eval.recommend_score import CASES, SCORING_KEYS, load_cases, scoring_hash

REQUESTS = CASES.parent / "recommend-requests"
#: 사례 파일 판 1 의 채점 칸과 판독 기준. 바꾸면 다른 측정이다.
SCORING_HASH = "d0421418d8f9d711aac6936a2652e50761a26937bbfc7c9389b43e7da7422176"
#: 코퍼스 문서 일곱의 제목 — 절차 문서는 이 가운데서만 온다.
CORPUS = {
    "SOP-01 파지 실패와 잔여 파지 처리", "SOP-02 안착 실패와 품번 불일치", "SOP-03 자재 결품과 대체 슬롯 운용",
    "SOP-04 이동 경로 차단 대응", "SOP-05 자기 위치 상실 복구", "SOP-06 제어권 상실과 명령 덮어쓰기",
    "합성 기체(fixture)의 정지 코드 표면 — Synthetic Stop-Code Surface",
}
EXECUTING = {"APPROVE_REMEDY", "CHOOSE_SOURCE"}


def _cases():
    return load_cases()["cases"]


def _request(case):
    return parse_request(json.loads((REQUESTS / case["request"]).read_text(encoding="utf-8")))


def _candidates(case):
    return {c["candidateId"]: c for c in _request(case).candidates}


def test_요청_사본은_koshei_투영의_바이트_그대로다():
    """요청은 koshei 의 실제 투영이 지었다(계약 §8 과 같은 규칙). 사본의 sha256 이 사례 파일과 다르면 누가 고친 것이다."""
    for case in _cases():
        raw = (REQUESTS / case["request"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == case["requestSha256"], case["id"]
    assert sorted(p.name for p in REQUESTS.iterdir()) == sorted(c["request"] for c in _cases()), "남는 사본이 없다"


def test_사례_파일의_채점_칸이_박은_값과_같다():
    """⛔ **답을 보고 채점 칸을 넓히면 재는 것이 모델이 아니라 관측한 답이 된다**(함정 1). 스크립트로 바꿔도 여기서 빨개진다."""
    doc = load_cases()
    assert set(SCORING_KEYS) <= set(doc["cases"][0])
    assert scoring_hash(doc) == SCORING_HASH


def test_요청마다_읽히고_자료_칸이_선다():
    for case in _cases():
        request = _request(case)
        assert len(render(request.candidates, request.unknowns, request.history)) <= LIMIT
        assert aliases(request.candidates)["ESCALATE"] == "ESCALATE"


def test_식별자와_층과_표시():
    cases = _cases()
    assert [c["id"] for c in cases] == [f"R{n:02d}" for n in range(1, 23)]
    assert sum(c["tier"] == "core" for c in cases) == 14 and sum(c["tier"] == "extended" for c in cases) == 8
    assert {c["id"]: c["repeatOf"] for c in cases if c["repeatOf"]} == {"R02": "R01"}
    assert [c["id"] for c in cases if c["seen"]] == ["R01", "R02"]
    assert {c["id"]: c["marks"] for c in cases if c["marks"]} == {"R06": ["observedNull"], "R09": ["observedNull"]}


def test_기대와_금지와_판독은_그_요청의_후보이고_겹치지_않는다():
    for case in _cases():
        ids = set(_candidates(case))
        expect, forbid = set(case["expect"] or []), set(case["mustNotPick"])
        reading = {r["candidate"] for r in case["reading"]}
        assert expect | forbid | reading <= ids, case["id"]
        assert not (expect & forbid) and not (expect & reading) and not (forbid & reading), case["id"]
    nulls = {c["id"] for c in _cases() if c["expect"] is None}
    assert nulls == {"R03", "R19"} and all(not c["mustNotPick"] for c in _cases() if c["id"] in nulls)


def test_판독_목록은_질의_주체인_보류_단위의_완료_확인이다():
    """**기대와 판독은 모델이 본 것으로 정한다**(설계서 §2.3 원칙) — C1 의 단위는 질의 주체 사건의 것이고 그 사건의 MATCHED
    가 질의에 실린다. 합류 줄의 CONFIRM_DONE 은 모델이 MATCHED 를 못 보므로 판독 목록에 없다."""
    seen = []
    for case in _cases():
        request = _request(case)
        candidates = _candidates(case)
        for item in case["reading"]:
            candidate = candidates[item["candidate"]]
            ref = candidate["ref"]
            assert item["criterion"] == "C1"
            assert candidate["kind"] == "OPERATOR_DECISION" and ref["decision"] == "CONFIRM_DONE"
            subject = request.snapshot["incidents"][0]
            assert (subject["executionId"], subject["unitId"]) == (ref["executionId"], ref["unitId"]), case["id"]
            assert subject["verification"] == "MATCHED", case["id"]
            seen.append(case["id"])
    assert seen == ["R11", "R12", "R13", "R14", "R15", "R16", "R18", "R21"]
    assert set(load_cases()["criteria"]) == {"C1"}


def test_확인_불가가_있으면_실행_계열이_없다():
    """계약 §7 의 지표 3 은 이것 때문에 구성상 0 이다 — 그래서 뺀 조치(`removed`)를 가리키는 답을 따로 잰다(설계서 §3.2)."""
    for case in _cases():
        request = _request(case)
        candidates = _candidates(case)
        if request.unknowns:
            for c in candidates.values():
                assert c["kind"] not in EXECUTING, case["id"]
                assert not (c["kind"] == "OPERATOR_DECISION" and c["ref"]["decision"] == "REWORK"), case["id"]
        for removed in case["removed"]:
            assert removed["candidate"] not in candidates and request.unknowns, case["id"]
    assert {c["id"]: len(c["removed"]) for c in _cases() if c["removed"]} == {"R07": 1, "R09": 1, "R16": 5}


def test_반복_짝은_질의와_자료_칸이_같다():
    by_id = {c["id"]: _request(c) for c in _cases()}
    first, second = by_id["R01"], by_id["R02"]
    assert query_text(first.snapshot) == query_text(second.snapshot)
    assert render(first.candidates, first.unknowns, first.history) == render(second.candidates, second.unknowns,
                                                                             second.history)


def test_질의에_답이_없다():
    """**메아리를 재지 않는다** — 설명 골든셋의 「정답은 질의에 없는 말」의 권고 판. 후보는 자료 칸으로만 간다."""
    for case in _cases():
        text = query_text(_request(case).snapshot)
        assert "ESCALATE" not in text and "권고" not in text, case["id"]
        assert not any(cid in text for cid in _candidates(case)), case["id"]


def test_절차_문서는_코퍼스의_제목에서만_온다():
    for case in _cases():
        assert set(case["procedureDocs"]) <= CORPUS, case["id"]
    assert [c["id"] for c in _cases() if not c["procedureDocs"]] == ["R08"]
