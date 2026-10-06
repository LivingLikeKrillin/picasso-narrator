"""권고 변동의 평가 도구 — 설계서 `docs/superpowers/specs/2026-10-01-권고-변동.md` §2. 가짜 줄로."""

import pytest

from eval.recommend_score import load_cases, scoring_hash
from eval.recommend_variance import cited_docs, exact_interval, search_state, tally

DOC = load_cases()
CASES = {c["id"]: c for c in DOC["cases"]}
A01 = "APPROVE_REMEDY:hum-02:PATROL-1:pick_place"
SOP01 = "SOP-01 파지 실패와 잔여 파지 처리"
SOP03 = "SOP-03 자재 결품과 대체 슬롯 운용"
ORCH = "오케스트레이션 — 세 층과 자원 소유"
VERSIONS = {"modelId": "m", "promptVersion": "p", "corpusVersion": "c", "searchFingerprint": "s", "narratorCommit": "x"}


def env(name="var-01", commit="abc", scoring=None):
    return {"pass": name, "narratorCommit": commit, "scorer": "s1", "measurer": "m1",
            "cases": {"scoringHash": scoring or scoring_hash(DOC)}}


def row(cid="R01", pick="ESCALATE", outcome="RECOMMENDED", rationale="이유.", uncited=(), unverified=(), citations=(),
        evidence=(), degraded=(), enrichment=(), query="q1", failed=None):
    kinds = {"ESCALATE": "ESCALATE", A01: "APPROVE_REMEDY"}
    base = {"id": cid, "requestSha256": "r1", "querySha256": query, "contextSha256": "c1", "kinds": kinds, "failed": failed,
            "resolved": None, "response": None, "diagnostics": None}
    if failed:
        return base
    base.update(resolved=pick, response={
        "outcome": outcome, "candidateId": pick if outcome == "RECOMMENDED" else None, "rationale": rationale,
        "uncitedSentences": list(uncited), "unverifiedClaims": list(unverified), "citations": list(citations),
        "versions": dict(VERSIONS)},
        diagnostics={"evidenceDocs": list(evidence),
                     "degraded": None if degraded is None else list(degraded),
                     "enrichment_failed": None if enrichment is None else list(enrichment)})
    return base


def record(rows, **kwargs):
    return {"env": env(**kwargs), "complete": True, "rows": rows}


def cite(title, verified=True):
    return {"title": title, "section": "5. 절차", "verified": verified}


def test_입력마다_고른_것과_깨끗한_A_와_금지_후보를_센다():
    """분모는 답한 반복이다. 생성 실패는 사유별로 따로 센다. 인용 없는 문장이 있는 A 는 깨끗하지 않아도 결과가 RECOMMENDED 라
    금지 후보 · 효과로 센다(바깥 루프가 그 제안을 사람 승인으로 올린다)."""
    out = tally(DOC, [record([
        row(),
        row(pick=A01, uncited=["사실 읽기."]),
        row(pick=A01),
        row(failed="rate_limit"),
    ])])
    r01 = out["inputs"]["R01"]["all"]
    assert r01["n"] == 3
    assert r01["picks"] == {"APPROVE_REMEDY": 2, "ESCALATE": 1}
    assert r01["outcomes"] == {"RECOMMENDED": 3}
    assert r01["approve"] == (2, 3) and r01["cleanApprove"] == (1, 3) and r01["forbiddenEffect"] == (2, 3)
    assert out["inputs"]["R01"]["failed"] == {"rate_limit": 1}
    assert out["headline"] is True


def test_절차_인용은_검증된_인용으로만_문서마다_센다():
    """이유 글의 `[출처: …]` 무리가 문서를 대려면 검증된 인용의 제목으로 시작해야 한다. 검증 안 된 SOP-01 인용은 안 센다."""
    unverified = row(pick=A01, rationale=f"재승인한다[출처: {SOP01}, 5. 절차].", citations=[cite(SOP01, verified=False)])
    verified = row(pick=A01, rationale=f"재승인한다[출처: {SOP01}, 5. 절차]. 슬롯을 찾았다[출처: {SOP03}, 6. 대장].",
                   citations=[cite(SOP01), cite(SOP03)])
    surface = row(pick=A01, rationale=f"관문이 막지 않는다[출처: {ORCH}, 7. 승인면의 모양].", citations=[cite(ORCH)])
    assert cited_docs(unverified["response"], [SOP01]) == set()
    assert cited_docs(verified["response"], [SOP01, SOP03]) == {SOP01, SOP03}
    assert cited_docs(surface["response"], [SOP01, SOP03]) == set()
    r01 = tally(DOC, [record([unverified, verified, surface, row()])])["inputs"]["R01"]["all"]
    assert r01["approve"] == (3, 4)
    assert r01["approveCites"] == {SOP01: (1, 3), SOP03: (1, 3)}, "절차 인용의 분모는 A 를 고른 답이다"
    assert r01["approveCitesAny"] == (1, 3)
    assert r01["cleanApproveCited"] == (1, 4), "깨끗하고 인용한 A 의 분모는 답한 반복이다"


def test_근거에_온_절차_문서는_문서마다_센다():
    out = tally(DOC, [record([row(evidence=[SOP03, ORCH]), row(evidence=[ORCH]), row(evidence=[SOP01, SOP03])])])
    assert out["inputs"]["R01"]["all"]["evidence"] == {SOP01: (1, 3), SOP03: (2, 3)}


def test_검색_고장과_모름은_따로_세고_온전한_것만의_수를_낸다():
    """고장은 두 칸 가운데 하나라도 빈 목록이 아닌 것, 모름은 하나라도 `None` 인 것, 온전은 둘 다 `[]` 이다. 다시 돌지 않는다."""
    assert search_state(row(degraded=["vector"])) == "broken"
    assert search_state(row(degraded=None)) == "unknown"
    assert search_state(row(degraded=None, enrichment=["section_fill"])) == "broken"
    assert search_state(row()) == "intact"
    out = tally(DOC, [record([row(pick=A01, degraded=["vector"]), row(degraded=None), row()])])
    r01 = out["inputs"]["R01"]
    assert r01["all"]["approve"] == (1, 3) and r01["intact"]["approve"] == (0, 1)
    assert r01["search"] == {"broken": [("var-01", 0)], "unknown": [("var-01", 1)]}


def test_같은_입력이_아니거나_판_칸이_갈리면_머리_수치가_아니고_사례_판이_다른_기록은_안_센다():
    out = tally(DOC, [record([row()]), record([row(query="q2")], name="var-02")])
    assert len(out["inputs"]["R01"]["groups"]) == 2 and out["headline"] is False
    assert [p["all"]["n"] for p in out["inputs"]["R01"]["parts"]] == [1, 1], "갈리면 갈래마다 따로 센다"
    corpus = row(pick=A01)
    corpus["response"]["versions"]["corpusVersion"] = "c2"
    split = tally(DOC, [record([row(), corpus])])
    assert split["headline"] is False and len(split["inputs"]["R01"]["groups"]) == 1
    assert [p["all"]["approve"] for p in split["inputs"]["R01"]["parts"]] == [(0, 1), (1, 1)], "판 칸이 갈려도 합치지 않는다"
    assert tally(DOC, [record([row(), row()])])["inputs"]["R01"]["parts"] == []
    other = tally(DOC, [record([row()]), record([row()], name="old", scoring="0" * 64)])
    assert other["skipped"] == ["old"] and other["inputs"]["R01"]["all"]["n"] == 1


def test_정확한_양쪽_95_구간():
    low, high = exact_interval(0, 10)
    assert low == 0 and high == pytest.approx(0.3085, abs=1e-3)
    low, high = exact_interval(10, 10)
    assert low == pytest.approx(0.6915, abs=1e-3) and high == 1
    low, high = exact_interval(5, 10)
    assert low == pytest.approx(0.1871, abs=1e-3) and high == pytest.approx(0.8129, abs=1e-3)
    assert exact_interval(0, 0) is None
