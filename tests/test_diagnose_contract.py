"""진단 계약의 요청 — 계약 0.6 §3. 어긋나면 비재시도 예외다(다시 보내도 같다)."""

import pytest

from diagnose.contract import (CONTRACT_VERSION, ESCALATE, KINDS, REF_KEYS, RESPONSE_KEYS, ContractViolation,
                               parse_request, response)


def test_계약_요청을_읽는다(diagnose_request):
    request = parse_request(diagnose_request())

    assert CONTRACT_VERSION == "0.6"
    assert request.key == ("ep-1", 1, "sha256:" + "0" * 64)
    assert request.candidate_ids == ("APPROVE_REMEDY:hum-02:PATROL-1:pick_place", "ESCALATE")
    assert request.snapshot["searches"][0]["searchId"] == "search-1"
    assert request.unknowns == () and request.history == ()
    made = response(request, outcome="NO_GROUNDS", candidate_id=None, picked=None, rationale=None,
                    card=[], cause=None, citations=[], unverified_claims=[], uncited_sentences=[],
                    versions={}, elapsed=0.0)
    assert list(made) == list(RESPONSE_KEYS), "칸은 계약 §4 의 순서이고 하나도 빠지지 않는다"
    assert RESPONSE_KEYS == ("contractVersion", "episodeId", "attempt", "outcome", "candidateId", "picked",
                             "sawCandidatesVersion", "rationale", "card", "cause", "citations",
                             "unverifiedClaims", "uncitedSentences", "versions", "elapsedSeconds"), \
        "계약 §4 의 순서를 글자로 고정한다 — 상수만 보면 틀린 상수도 통과한다"
    assert made["sawCandidatesVersion"] == "sha256:" + "0" * 64
    incident = {"incidentId": "incident-1", "digest": "9760fe546d", "robotId": "hum-02"}
    only_incident = parse_request(diagnose_request(snapshot={"manifest": {"schemaVersion": "5"},
                                                      "incidents": [incident], "searches": []}))
    assert only_incident.snapshot["incidents"][0]["digest"] == "9760fe546d", "사건 줄만 있어도 된다 — 한쪽이 비는 것은 정상"


def test_판이_다르면_거절한다(diagnose_request):
    """**한 판만 받는다.** 범위로 받으면 모르는 판을 아는 척 읽게 된다(`receiver/export.py` 와 같은 까닭).
    적재 판도 같다 — picasso 의 `schemaVersion` 은 글자 `"5"` 다(0.5 까지 계약 예제가 숫자로 적어 틀렸다)."""
    with pytest.raises(ContractViolation, match="0.6"):
        parse_request(diagnose_request(contractVersion="0.5"))
    with pytest.raises(ContractViolation, match="적재 판"):
        parse_request(diagnose_request(
            snapshot={"manifest": {"schemaVersion": 5}, "incidents": [], "searches": [{}]}))


def test_빠진_칸과_모양이_틀린_칸은_거절한다(diagnose_request):
    """**값이 없으면 `null`, 키는 빼지 않는다**(계약 §2). 키가 빠지거나 모양이 틀린 것은 형식이 어긋난 것이다.
    여기서 못 잡으면 뒤에서 AttributeError 같은 엉뚱한 예외로 터져 koshei 가 무엇이 어긋났는지 모른다.
    빈 줄(`{}`)을 받으면 질의가 고정 물음만 싣고 나가 「관측이 없다」로 읽힌다."""
    payload = diagnose_request()
    del payload["unknowns"]
    with pytest.raises(ContractViolation, match="unknowns"):
        parse_request(payload)
    with pytest.raises(ContractViolation, match="목록"):
        parse_request(diagnose_request(history=None))
    with pytest.raises(ContractViolation, match="manifest"):
        parse_request(diagnose_request(snapshot={"manifest": "5", "incidents": [], "searches": []}))
    with pytest.raises(ContractViolation, match="picasso 줄"):
        parse_request(diagnose_request(snapshot={"manifest": {"schemaVersion": "5"}, "incidents": [],
                                                 "searches": [{}]}))
    with pytest.raises(ContractViolation, match="두 목록"):
        parse_request(diagnose_request(snapshot={"manifest": {"schemaVersion": "5"}, "incidents": [],
                                                 "searches": []}))
    with pytest.raises(ContractViolation, match="객체"):
        parse_request(diagnose_request(unknowns=["LINK_BROKEN"]))
    history_item = {"attempt": 1, "candidatesVersion": "sha256:" + "1" * 64, "diagnosis": None,
                    "approval": "REJECTED", "dispatch": None, "evidence": None, "closedAs": "REDIAGNOSE",
                    "at": "2026-09-06T00:03:00Z"}
    with pytest.raises(ContractViolation, match="approval"):
        parse_request(diagnose_request(history=[history_item]))
    with pytest.raises(ContractViolation, match="칸이 없다"):
        parse_request(diagnose_request(history=[{"attempt": 1}]))
    with pytest.raises(ContractViolation, match="칸이 없다"):
        parse_request(diagnose_request(unknowns=[{"subject": {}, "what": "LINK_BROKEN"}]))
    with pytest.raises(ContractViolation, match="attempt"):
        parse_request(diagnose_request(attempt=0))
    with pytest.raises(ContractViolation, match="episodeId"):
        parse_request(diagnose_request(episodeId=""))


def test_후보의_종류와_모양이_틀리면_거절한다(diagnose_request):
    """종류는 넷뿐이고, `ref` 는 객체다 — `null` 은 ESCALATE 만. 종류 ESCALATE 와 식별자 ESCALATE 는 함께 간다.
    종류마다의 `ref` 칸을 빼지 않고(더 있는 칸은 받는다), `APPROVE_REMEDY` 에는 `sawSkillTypes` 목록이 있다(§3.1)."""
    escalate = {"candidateId": "ESCALATE", "kind": "ESCALATE", "ref": None}
    odd = {"candidateId": "REBOOT:hum-02", "kind": "REBOOT", "ref": {}}
    with pytest.raises(ContractViolation, match="REBOOT"):
        parse_request(diagnose_request(candidates=[odd, escalate]))
    bare = {"candidateId": "APPROVE_REMEDY:hum-02:PATROL-1:pick_place", "kind": "APPROVE_REMEDY", "ref": None}
    with pytest.raises(ContractViolation, match="ref"):
        parse_request(diagnose_request(candidates=[bare, escalate]))
    twisted = {"candidateId": "ESCALATE", "kind": "OPERATOR_DECISION", "ref": {}}
    with pytest.raises(ContractViolation, match="함께"):
        parse_request(diagnose_request(candidates=[twisted]))
    reversed_pair = {"candidateId": "HAND_OVER", "kind": "ESCALATE", "ref": None}
    with pytest.raises(ContractViolation, match="함께"):
        parse_request(diagnose_request(candidates=[reversed_pair, escalate]))
    no_ref = {"candidateId": "APPROVE_REMEDY:hum-02:PATROL-1:pick_place", "kind": "APPROVE_REMEDY"}
    with pytest.raises(ContractViolation, match="ref 칸이 없다"):
        parse_request(diagnose_request(candidates=[no_ref, escalate]))
    skills = {"candidateId": "APPROVE_REMEDY:hum-02:PATROL-1:pick_place", "kind": "APPROVE_REMEDY",
              "ref": {}, "sawSkillTypes": "pick_place"}
    with pytest.raises(ContractViolation, match="sawSkillTypes"):
        parse_request(diagnose_request(candidates=[skills, escalate]))
    with pytest.raises(ContractViolation, match="candidateId"):
        parse_request(diagnose_request(candidates=[{"candidateId": "", "kind": "APPROVE_REMEDY", "ref": {}},
                                                   escalate]))
    assert set(REF_KEYS) == set(KINDS) - {ESCALATE}, "ESCALATE 밖의 종류마다 ref 칸이 정해져 있다"
    old_name = {"candidateId": "CHOOSE_SOURCE:SEQ-RELOCATE:ENGINE-COVER-B:SEQ-IN-03.BIN-B", "kind": "CHOOSE_SOURCE",
                "ref": {"jobOrderId": "SEQ-RELOCATE", "material": "ENGINE-COVER-B", "source": "SEQ-IN-03.BIN-B",
                        "searchId": "search-4"}}
    with pytest.raises(ContractViolation, match="missingSource · alternative"):
        parse_request(diagnose_request(candidates=[old_name, escalate]))
    both = dict(old_name, ref=dict(old_name["ref"], missingSource=None, alternative="SEQ-IN-03.BIN-B"))
    assert parse_request(diagnose_request(candidates=[both, escalate])).candidate_ids, "더 있는 칸은 받는다"
    unseen = {"candidateId": "APPROVE_REMEDY:hum-02:PATROL-1:pick_place", "kind": "APPROVE_REMEDY",
              "ref": {"robotId": "hum-02", "jobOrderId": "PATROL-1", "searchId": "search-1"}}
    with pytest.raises(ContractViolation, match="sawSkillTypes"):
        parse_request(diagnose_request(candidates=[unseen, escalate]))
    undecided = {"candidateId": "OPERATOR_DECISION:exec-8:RACK-204.S06:CONFIRM_DONE", "kind": "OPERATOR_DECISION",
                 "ref": {"executionId": "exec-8", "unitId": "RACK-204.S06"}}
    with pytest.raises(ContractViolation, match="decision"):
        parse_request(diagnose_request(candidates=[undecided, escalate]))


def test_후보_판은_sha256_소문자_64자다(diagnose_request):
    """판은 koshei 만 계산하고 이 층은 되돌려주기만 한다(계약 §3.2). 모양만 본다 — 16진 소문자 64자."""
    with pytest.raises(ContractViolation, match="sha256"):
        parse_request(diagnose_request(candidatesVersion="sha256:abc"))
    with pytest.raises(ContractViolation, match="sha256"):
        parse_request(diagnose_request(candidatesVersion="sha256:" + "A" * 64))
    with pytest.raises(ContractViolation, match="sha256"):
        parse_request(diagnose_request(candidatesVersion="sha256:" + "0" * 64 + "\n"))


def test_ESCALATE_가_없거나_식별자가_겹치면_거절한다(diagnose_request):
    """ESCALATE 는 늘 들어간다(계약 §3.1) — 없으면 모델이 사람에게 넘길 길이 없다. 식별자가 겹치면
    별칭이 둘로 갈려 무엇을 가리켰는지 못 가른다."""
    approve = diagnose_request()["candidates"][0]
    with pytest.raises(ContractViolation, match="ESCALATE"):
        parse_request(diagnose_request(candidates=[approve]))
    with pytest.raises(ContractViolation, match="겹친다"):
        parse_request(diagnose_request(candidates=[approve, dict(approve),
                                                   {"candidateId": "ESCALATE", "kind": "ESCALATE",
                                                    "ref": None}]))
