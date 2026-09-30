"""권고 측정의 채점 — 설계서 `docs/superpowers/specs/2026-09-30-권고-측정.md` §3. 가짜 줄로 돈다."""

import json

import pytest

from diagnose.context import aliases
from eval import recommend_score as s

REQUESTS = s.CASES.parent / "recommend-requests"
VERSIONS = {"modelId": "claude-sonnet-5", "promptVersion": "73536dc7c9c0", "corpusVersion": "d462b22017d6",
            "searchFingerprint": "b071397c854c", "narratorCommit": "0000000"}
SOP01 = "SOP-01 파지 실패와 잔여 파지 처리"


def _doc():
    return s.load_cases()


def row(cid, *, outcome="RECOMMENDED", raw="ESCALATE", resolved="ESCALATE", answer=None, rationale=None,
        citations=None, docs=None, versions=None):
    """측정기가 적는 줄의 모양 — 후보 종류와 별칭은 그 사례의 요청에서 온다."""
    case = next(c for c in _doc()["cases"] if c["id"] == cid)
    request = json.loads((REQUESTS / case["request"]).read_text(encoding="utf-8"))
    rationale = f"절차가 사람의 육안 확인을 먼저 둔다 [출처: {SOP01}, §5.1]." if rationale is None else rationale
    return {
        "id": cid, "tier": case["tier"], "aliases": aliases(request["candidates"]),
        "kinds": {c["candidateId"]: c["kind"] for c in request["candidates"]},
        "attempts": [{"n": 1, "reason": None}], "failed": None,
        "response": {"outcome": outcome, "candidateId": resolved if outcome == "RECOMMENDED" else None,
                     "picked": None, "rationale": rationale, "card": [], "cause": None,
                     "citations": [{"title": SOP01, "section": "§5.1", "verified": True}] if citations is None
                     else citations,
                     "unverifiedClaims": [], "uncitedSentences": [], "versions": dict(versions or VERSIONS),
                     "elapsedSeconds": 200.0},
        "rawPick": raw, "resolved": resolved, "recordOutcome": "GIVEN",
        "answer": answer if answer is not None else
        f"권고: {raw}\n이유: {rationale}\n절차: a\n먼저: b\n금지: c\n갈림: d\n근거 세기: e",
        "diagnostics": {"evidenceDocs": docs or [SOP01]},
    }


def test_느슨한_탐지는_꾸민_표지를_잡고_문장은_안_잡는다():
    """⛔ **첫 실물 진단에서 모델이 표지 줄을 「## 권고: ESCALATE」로 꾸몄다 (2026-09-30).** 꾸밈을 종류로 가른다 — 파서가
    받는 꾸밈(#, 굵게, 글머리표)은 답하는 법을 안 지킨 수이고, 파서가 거절하는 꾸밈은 후보 밖의 갈래 (ii) 다."""
    kinds = {line: s.decorations(line).get("권고") for line in
             ("권고: A", "## 권고: ESCALATE", "**권고**: B", "- 권고: A", "1. 권고: A", "> 권고: A", "### 권고",
              "## 권고 사항: A", "__권고__: A", "*권고*: A", "권고 - A")}
    assert kinds == {"권고: A": ["plain"], "## 권고: ESCALATE": ["heading"], "**권고**: B": ["bold"],
                     "- 권고: A": ["bullet"], "1. 권고: A": ["numbered"], "> 권고: A": ["quote"],
                     "### 권고": ["heading"], "## 권고 사항: A": ["heading"], "__권고__: A": ["bold"],
                     "*권고*: A": ["italic"], "권고 - A": ["plain"]}
    assert s.decorations("권고하지 않는다.\n권고안은 없다") == {}, "본문의 문장은 표지가 아니다"
    assert s.decorations("# 절차: SOP-01\n* 먼저: 확인")["절차"] == ["heading"], "다섯 표지도 센다"


def test_후보_밖_갈래와_옛_파서():
    headed = row("R04", answer="## 권고: ESCALATE\n이유: 없다")
    assert s.marker_bucket(headed) is None and s.out_of_candidates_old(headed) is True, "옛 파서는 # 를 못 읽었다"
    assert s.marker_bucket(row("R04", raw=None, resolved=None, answer="1. 권고: ESCALATE")) == \
        ("ii", "1. 권고: ESCALATE")
    assert s.marker_bucket(row("R04", raw=None, resolved=None, answer="\n" * 12 + "권고: ESCALATE")) == \
        ("iii", "권고: ESCALATE")
    assert s.marker_bucket(row("R04", raw=None, resolved=None, answer="검색된 문서에 없습니다.")) == ("i", None)
    assert s.marker_bucket(row("R04", raw="A 또는 ESCALATE", resolved=None)) == ("iv", None)


def test_UNCITED_원인_넷():
    """⚠ 표지 줄의 꾸밈은 원인이 될 수 없다 — 판정 3 은 표지를 보기 전에 인용만 본다(설계서 §3.5)."""
    bare = row("R04", outcome="UNCITED", citations=[], answer="권고: ESCALATE\n이유: 없다")
    assert s.uncited_cause(bare) == "a"
    assert s.uncited_cause(row("R04", outcome="UNCITED", citations=[], answer="이유: (출처: SOP-03)")) == "b"
    unverified = [{"title": "SOP-03", "section": "§4", "verified": False}]
    assert s.uncited_cause(row("R04", outcome="UNCITED", citations=unverified,
                               docs=["SOP-03 자재 결품과 대체 슬롯 운용"])) == "c"
    assert s.uncited_cause(row("R04", outcome="UNCITED", citations=unverified,
                               docs=["SOP-05 자기 위치 상실 복구"])) == "d"


def test_맨_정수는_미리_박은_제외_뒤에_센다():
    """⛔ **「지어낸 수」가 실은 인용 절 번호였다**(함정 3) — 근거 등급 · 절 번호 · 식별자 · 날짜를 먼저 지운다. 걸린 조각을
    다 돌려줘 사람이 연다."""
    assert s.bare_integers("E2 근거로 1회, [출처: SOP-01, §5.1] exec-8 은 최대 2.") == ["1", "2"]
    assert s.bare_integers("RACK-204.S06 은 §5.1 ② 대로 5절 2항, 2026-09-06T00:00:04Z 에 X_FIXTURE_E9001") == []
    assert s.bare_integers("③ 확인 뒤 3 번째 시도") == ["3", "③"]
    assert s.bare_integers(None) == []


def test_판독_대리값과_뺀_조치를_가리키는_말():
    assert s.reading_proxy("설비가 기대 품목을 봤다(MATCHED). 사람이 슬롯을 육안으로 확인한 뒤 완료한다.") is True
    assert s.reading_proxy("완료로 본다.") is False and s.reading_proxy(None) is False
    assert s.reading_proxy("E2 에 못 미치니 사람이 육안으로 확인한다.") is False, "맨 E2 는 설비의 근거가 아니다"
    r07 = next(c for c in _doc()["cases"] if c["id"] == "R07")
    assert s.names_removed(row("R07", rationale="재작업 전에 사람이 현물을 본다."), r07) is True
    assert s.names_removed(row("R07", rationale="사람이 현물을 본다."), r07) is False
    r09 = next(c for c in _doc()["cases"] if c["id"] == "R09")
    cited = "사람에게 넘긴다 [출처: SOP-03 자재 결품과 대체 슬롯 운용, §4]."
    assert s.names_removed(row("R09", rationale=cited), r09) is False, "인용 제목의 「대체 슬롯」은 권고가 아니다"
    assert s.names_doc("SOP-01", SOP01) and not s.names_doc("SOP-0", SOP01)


def all_escalate():
    return [row(c["id"]) for c in _doc()["cases"]]


def test_늘_ESCALATE_는_기대를_다_채우고_금지는_0():
    """⛔ **기대의 거의 전부가 ESCALATE 다 (2026-09-30)** — 이 기준선을 모든 표에 곁들인다(설계서 §2.1). R02 는 R01 의
    반복이라 비율에서 빠진다."""
    report = s.score(_doc(), all_escalate())
    assert report["all"]["answered"] == 21 and report["core"]["answered"] == 14 and report["extended"]["answered"] == 7
    assert report["all"]["M4marker"] == (19, 19) and report["all"]["M4effect"] == (19, 19)
    assert report["all"]["M4choice"] == (12, 12)
    assert report["all"]["forbiddenMarker"] == (0, 11) and report["all"]["forbiddenEffect"] == (0, 11)
    assert report["all"]["M4read"] is None, "판독 전"
    assert report["all"]["groundedEscalation"] == (8, 18), "SOP-01 을 대는 인용 — 절차 문서에 SOP-01 이 든 사례만"
    assert report["cards"] == (21, 21) and report["decorationCounts"]["unseen"]["권고"] == {"plain": 20}
    assert report["repeat"] == {"R02": {"marker": True, "outcome": True, "versions": True}}
    assert [len(group["cases"]) for group in report["versions"]] == [22], "판 칸은 반복(R02)까지 본다"
    assert report["headline"] is True


def test_금지는_표지와_효과로_따로_센다():
    """표지로 골랐어도 인용 없음으로 끝나면 사람에게 간다 — 해가 나는 것은 효과 쪽이다(설계서 §3.3)."""
    rows = all_escalate()
    ar = "APPROVE_REMEDY:hum-02:PATROL-1:pick_place"
    rows[0] = row("R01", outcome="UNCITED", raw="A", resolved=ar, citations=[], rationale="없다.")
    report = s.score(_doc(), rows)
    assert report["all"]["forbiddenMarker"] == (1, 11) and report["all"]["forbiddenEffect"] == (0, 11)
    assert report["uncited"]["R01"] == {"cause": "a", "marker": "other"}, "다른 후보로 풀린 UNCITED 가 재진단 안 하는 값"
    assert report["unseen"]["forbiddenMarker"] == (0, 10), "본 사례를 뺀 값"


def test_판독은_목록에_있는_후보를_다_읽었을_때만_센다():
    """덜 읽은 판독을 「아니다」로 세면 판독이 자동 값보다 낮게 거짓말한다 — 그때는 판독 전이다. 판독에서 받는 후보는 그
    사례의 판독 목록에 있는 것뿐이다 — 금지 후보를 판독으로 받으면 채점 규칙을 답 뒤에 넓힌 것이 된다(함정 1)."""
    rows = all_escalate()
    cd = "OPERATOR_DECISION:exec-4:RACK-204.S03:CONFIRM_DONE"
    i = next(i for i, r in enumerate(rows) if r["id"] == "R11")
    rows[i] = row("R11", raw="A", resolved=cd, rationale="설비가 기대 품목을 봤다(MATCHED). 사람이 슬롯을 육안으로 확인한다.")
    report = s.score(_doc(), rows, readings={"readings": [{"case": "R11", "candidate": cd, "accept": True}]})
    assert report["all"]["M4marker"] == (18, 19) and report["all"]["M4read"] == (19, 19)
    assert report["readingProxy"]["R11"] == {cd: True}
    refused = s.score(_doc(), rows, readings={"readings": [{"case": "R11", "candidate": cd, "accept": False}]})
    assert refused["all"]["M4read"] == (18, 19)
    assert s.score(_doc(), rows, readings={"readings": []})["all"]["M4read"] is None, "읽을 것을 덜 읽었다"
    assert s.score(_doc(), rows, readings={"m3": {"R07": True}})["M3read"] is None, "뺀 조치가 있는 셋 중 하나만 읽었다"
    rework = "OPERATOR_DECISION:exec-4:RACK-204.S03:REWORK"
    rows[i] = row("R11", raw="B", resolved=rework)
    widened = s.score(_doc(), rows, readings={"readings": [{"case": "R11", "candidate": rework, "accept": True}]})
    assert widened["all"]["M4read"] == (18, 19) and widened["all"]["forbiddenMarker"] == (1, 11), "판독 목록 밖"


def test_분모가_0_이면_짝으로_적고_판독_전은_따로_적는다():
    report = s.score(_doc(), [])
    assert report["all"]["M1"] == (0, 0) and s.fraction(report["all"]["M1"]) == "0/0"
    assert s.fraction(None) == "판독 전"
    assert report["missing"] == [c["id"] for c in _doc()["cases"]], "빠짐은 반복(R02)까지 센다"
    assert report["headline"] is False


def test_판_칸이_두_벌이면_머리_수치가_아니다():
    """반쪽끼리는 사례 구성이 달라 비율을 견줄 수 없다(설계서 §6). 모델에게 가는 글이 같은 프롬프트 판은 한 무리다."""
    rows = all_escalate()
    rows[3] = row(rows[3]["id"], versions=dict(VERSIONS, corpusVersion="aaaaaaaaaaaa"))
    report = s.score(_doc(), rows)
    assert report["headline"] is False and len(report["versions"]) == 2
    rows[3] = row(rows[3]["id"], versions=dict(VERSIONS, promptVersion="81377584ff5a"))
    assert s.score(_doc(), rows)["headline"] is True
    rows[3] = row(rows[3]["id"], versions=dict(VERSIONS, corpusVersion=None))
    split = s.score(_doc(), rows)
    assert split["headline"] is False and split["versions"][0]["cases"] == ["R04"], "다시 돌 사례를 무리마다 적는다"
    unknown = s.score(_doc(), [row(c["id"], versions=dict(VERSIONS, corpusVersion=None)) for c in _doc()["cases"]])
    assert unknown["headline"] is False, "모르는 판(None)은 같다고 못 한다"


def test_합치기는_사례_파일이_같을_때만():
    a = {"env": {"cases": {"scoringHash": "x"}}, "rows": [row("R01"), row("R03")]}
    b = {"env": {"cases": {"scoringHash": "x"}}, "rows": [row("R03", raw="A", resolved=None)]}
    _, rows = s.merge([a, b])
    assert {r["id"]: r["rawPick"] for r in rows} == {"R01": "ESCALATE", "R03": "A"}, "사례마다 뒤의 기록"
    with pytest.raises(SystemExit):
        s.merge([a, {"env": {"cases": {"scoringHash": "y"}}, "rows": []}])


def test_사례_파일이_바뀌면_다시_세지_않고_다른_기록의_판독은_안_쓴다(tmp_path, capsys, monkeypatch):
    """재채점은 기록 때의 사례 파일로만 한다(설계서 §0). `--allow-drift` 로 켜면 결과 머리에 적는다. 판독 파일은 같은 사례
    판과 같은 기록들의 것일 때만 쓴다 — 둘째 판을 첫 판의 판독으로 세지 않는다(설계서 §5)."""
    monkeypatch.setattr(s, "READINGS", tmp_path / "readings.json")
    record = tmp_path / "record.json"
    record.write_text(json.dumps({"env": {"cases": {"scoringHash": "기록 때의 것"}, "at": "t1"}, "complete": True,
                                  "rows": all_escalate()}, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SystemExit):
        s.main([str(record)])
    assert s.main([str(record), "--allow-drift"]) == 0
    assert "사례 판이 다름" in capsys.readouterr().out
    record.write_text(json.dumps({"env": {"cases": {"scoringHash": s.scoring_hash(_doc())}, "at": "t1"},
                                  "complete": True, "rows": all_escalate()}, ensure_ascii=False), encoding="utf-8")
    s.READINGS.write_text(json.dumps({"scoringHash": s.scoring_hash(_doc()), "records": ["t0"], "m3": {}}),
                          encoding="utf-8")
    assert s.main([str(record)]) == 0
    assert "다른 기록들의 것" in capsys.readouterr().out
