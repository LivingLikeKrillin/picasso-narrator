"""질문 제거 — 설계서 `docs/superpowers/specs/2026-10-01-물음-떼기.md`. 가짜 응답으로 돈다."""

import pytest

from composer.query import ASK, Query
from eval import ask_trial as a
from eval import fusion_trial as ft
from eval import query_trial as qt

SOP01 = "SOP-01 파지 실패와 잔여 파지 처리"
SOP03 = "SOP-03 자재 결품과 대체 슬롯 운용"
SOP06 = "SOP-06 제어권 상실과 명령 덮어쓰기"
GUIDE = "합성 SOP 6종 — 코퍼스 안내"
EXCLUDE = ("spec", "design_doc", "case")


def snip(doc, rank, rid=None):
    return {"chunk_rid": rid or f"{doc[:6]}-{rank}", "doc_title": doc, "section_path": "5", "rank": rank, "score": 0.5,
            "text": "가" * 300}


def ranked(*docs):
    titles = list(docs) + [GUIDE] * (20 - len(docs))
    return [snip(title, i + 1, rid=f"r{i + 1}-{title[:6]}") for i, title in enumerate(titles)]


def row(cid, expected, snippets, query="질의", set_="recommend", exclude=EXCLUDE, context=None, route="graph_then_hybrid",
        used=None):
    item = {"id": cid, "set": set_, "expected": list(expected)}
    body = {"query": query, "tenant": "picasso", "top_k": 20, "identifier_channel": True}
    if exclude:
        body["exclude_doc_types"] = list(exclude)
    if context is not None:
        body["answer_context"] = context
    sent = qt.tokens(query)
    data = {"evidence_only": True, "fusion_doc_agreement": False, "identifier_channel_asked": True, "answer_context_len": 0,
            "searched_tenants": ["picasso"], "degraded": [], "enrichment_failed": [], "prompt_version": "p",
            "corpus_version": "c", "search_fingerprint": "s", "identifier_channel": sent if used is None else used,
            "top_distance": 0.3, "top_bm25": 1.2, "weak_evidence": False, "excluded_doc_types": list(exclude),
            "timing_ms": {"total_ms": 100}, "evidence_snippets": snippets}
    out = ft.row_of(item, body, 200, {"success": True, "data": data})
    out.update(queryChars=len(query), sentTokens=sent, route=route)
    return out


def record(name, arm, rows, at):
    return {"env": {"pass": name, "arm": arm, "at": at, "narratorCommit": "c0"}, "rows": rows}


def three_arms(q3_r01=(SOP01,), q3_r03=(SOP03,)):
    """Q0 는 R01 을 놓친다. Q2 는 R01 을 들이되 R03 에 SOP-06 을 더 끌어온다. Q3 은 질문만 뺀 글이다. 질의 줄은 세 글이 같다."""
    q0 = [row("R01", [SOP01], ranked(GUIDE), query="R01 PAYLOAD_LOST 긴 글"),
          row("R03", [SOP03], ranked(SOP03), query="R03 HOLD_KIND_EMPTY 긴 글"),
          row("Q1", [], ranked(GUIDE), query="물음", set_="golden", exclude=())]
    q2 = [row("R01", [SOP01], ranked(SOP01), query=ASK + "PAYLOAD_LOST 짧음", route="graph_then_hybrid"),
          row("R03", [SOP03], ranked(SOP03, SOP06), query=ASK + "HOLD_KIND_EMPTY 짧음"),
          row("Q1", [], ranked(GUIDE), query="물음", set_="golden", exclude=())]
    q3 = [row("R01", [SOP01], ranked(*q3_r01), query="PAYLOAD_LOST 짧음", route="hybrid_only"),
          row("R03", [SOP03], ranked(*q3_r03), query="HOLD_KIND_EMPTY 짧음", route="hybrid_only"),
          row("Q1", [], ranked(GUIDE), query="물음", set_="golden", exclude=())]
    return q0, q2, q3


def test_세_글은_질의_줄이기의_Q0_Q2_와_물음만_뺀_Q3_이다():
    """Q0 · Q2 는 질의 축소의 글 그대로이고, Q3 은 Q2 에서 고정 질문만 뺀 글이다 — 조회 지시는 맨 앞에 남고 식별자 토큰은 Q0 와
    차례까지 같다. 질의 줄은 세 글이 같고, R05 는 Q3 에서만 달라진다(설계서 §1)."""
    built = qt.queries()
    for cid, query in built.items():
        three, base = a.texts(query), qt.texts(query)
        assert (three["Q0"], three["Q2"]) == (base["Q0"], base["Q2"]), cid
        assert qt.tokens(three["Q3"]) == qt.tokens(three["Q0"]), cid
        if isinstance(query, str):
            assert three["Q3"] == three["Q0"], cid
        else:
            assert len(three["Q2"]) - len(three["Q3"]) == len(ASK) and ASK not in three["Q3"], cid
            assert three["Q3"].startswith(query.lookup), cid
    assert sorted(cid for cid, query in built.items() if a.texts(query)["Q2"] == a.texts(query)["Q0"]) == ["Q1", "Q2", "Q3", "R05"]
    assert sorted(cid for cid, query in built.items() if a.texts(query)["Q3"] == a.texts(query)["Q0"]) == ["Q1", "Q2", "Q3"]
    looked = a.texts(Query(facts={"failureClass": "UNCLASSIFIED", "fault": {"vendorDetail": "X_FIXTURE_E4412"}},
                           lookup="벤더 정지 코드 X_FIXTURE_E4412 의 뜻. "))
    # 조회 지시에 토큰이 이미 있으면 Q1 의 토큰이 Q0 와 같아 Q2 = Q1 이다 — Q3 은 토큰을 다시 붙이지 않는다
    assert looked["Q3"] == "벤더 정지 코드 X_FIXTURE_E4412 의 뜻. failureClass=UNCLASSIFIED"
    with pytest.raises(ValueError, match="빈 글"):
        a.texts(Query(facts={"fault": {"errorType": "X"}}))
    assert [i["query"] for i in a.items("Q0")] == [i["query"] for i in ft.items()]
    # 합쳐짐 — Q3 은 Q2 와 같은 무리로 합쳐진다(서로 다른 검색 스물둘, 기대 있는 것 열여덟, 설계서 §1)
    keys = {}
    for item in a.items("Q3"):
        body, _, _ = ft.call(item, lambda *sent: (200, {"success": True, "data": {}}), "http://x", "t")
        keys.setdefault(ft.search_key(body), []).append(item)
    assert len(keys) == 22 and sum(any(i["expected"] for i in group) for group in keys.values()) == 18


def test_셈은_Q3_하나만_후보로_보고_물음의_몫을_적는다():
    q0, q2, q3 = three_arms()
    out = a.tally([record("q0-1", "Q0", q0, "1"), record("q2-1", "Q2", q2, "2"), record("q3-1", "Q3", q3, "3")])
    assert out["comparable"] is None and out["n"] == 2
    arms = out["arms"]
    assert [arms[arm]["headline"][:2] for arm in a.ARMS] == [(1, 2), (2, 2), (2, 2)]
    assert arms["Q2"]["secondary"]["wrong"]["labeled"] == 1 and arms["Q3"]["secondary"]["wrong"]["labeled"] == 0
    assert arms["Q2"]["wrongBy"] == {SOP06: 1} and arms["Q3"]["wrongBy"] == {}
    assert arms["Q3"]["routes"] == {"graph_then_hybrid": 1, "hybrid_only": 2} and arms["Q0"]["routes"] == {"graph_then_hybrid": 3}
    assert arms["Q3"]["strength"] == {"weak": 0, "of": 3, "topDistance": {"median": 0.3, "max": 0.3},
                                      "topBm25": {"median": 1.2, "min": 1.2}}
    assert out["changed"] == {"Q2": ["R01", "R03"], "Q3": ["R01", "R03"]} and out["askCut"] == [] and out["unchanged"] == ["Q1"]
    assert out["q2VsQ3"]["onlyQ2"] == [] and out["q2VsQ3"]["onlyQ3"] == [] and out["q2VsQ3"]["wrong"] == (1, 0)
    assert out["advance"] == "Q3"
    lines = a.report_lines(out)
    assert any(line.startswith("Q2 대 Q3(물음의 몫) ") for line in lines) and lines[-1] == "다음 단계로 넘길 실험군 — Q3"


def test_Q2_는_어떤_수가_나와도_넘기지_않는다():
    """후보는 Q3 하나다 — 앞 실행이 이미 정한 Q2 를 새 창에서 다시 후보로 걸지 않는다. 임계값은 질의 축소와 같다."""
    def arm(head, pairs, wrong=10):
        return {"headline": (head, 27, None), "pairs": (pairs, 40), "secondary": {"wrong": {"labeled": wrong}}}

    base = arm(23, 29, wrong=41)
    assert a.advance({"Q0": base, "Q2": arm(27, 37, wrong=10), "Q3": arm(23, 29, wrong=41)}) is None, "Q2 만 넘으면 없다"
    assert a.advance({"Q0": base, "Q2": arm(27, 36, wrong=52), "Q3": arm(25, 31, wrong=41)}) == "Q3"
    assert a.advance({"Q0": base, "Q2": arm(27, 36, wrong=52), "Q3": arm(27, 37, wrong=42)}) is None, "틀린 절차가 늘면 안 넘는다"
    assert a.advance({"Q0": base, "Q2": arm(27, 36), "Q3": arm(26, 28, wrong=5)}) is None, "짝이 줄면 안 넘는다"
    assert a.advance({"Q0": base, "Q3": arm(27, 37, wrong=5)}) is None, "세 실험군이 다 있어야 정한다"
    q0, q2, q3 = three_arms()
    out = a.tally([record("q0-1", "Q0", q0, "1"), record("q3-1", "Q3", q3, "2")])
    assert out["comparable"] is None and out["advance"] is None and out["askCut"] is None
    assert a.report_lines(out)[-1] == "다음 단계로 넘길 실험군 — 판정 안 함"


def test_물음만_뺀_글이_아니거나_토큰이_다르면_머리_수치가_아니다():
    """항목마다 Q2 와 Q3 의 글자 수 차가 질문의 길이여야 하고(Q3 이 Q0 와 같은 질의 줄은 빼고), Q2 가 바꾼 항목은 Q3 도 바꿔야 하며,
    실험군이 보낸 토큰은 Q0 와 차례까지 같아야 한다 — 하나라도 어긋나면 대표 지표가 아니고 승격할 실험군도 정하지 않는다."""
    q0, q2, q3 = three_arms()
    padded = [row("R01", [SOP01], ranked(SOP01), query="PAYLOAD_LOST 짧음 더"), *q3[1:]]
    out = a.tally([record("q0-1", "Q0", q0, "1"), record("q2-1", "Q2", q2, "2"), record("q3-1", "Q3", padded, "3")])
    assert out["comparable"] == "Q3 이 Q2 에서 물음만 뺀 글이 아니다" and out["askCut"] == ["R01"] and out["advance"] is None
    reordered = [row("R01", [SOP01], ranked(SOP01), query="HOLD_KIND_EMPTY PAYLOAD_LOST"), *q3[1:]]
    out = a.tally([record("q0-1", "Q0", q0, "1"), record("q3-1", "Q3", reordered, "2")])
    assert out["comparable"] == "실험군의 식별자 토큰이 Q0 와 다르다" and out["tokenOrder"] == {"Q3": ["R01"]}
    kept = [q3[0], row("R03", [SOP03], ranked(SOP03), query="R03 HOLD_KIND_EMPTY 긴 글"), q3[2]]
    out = a.tally([record("q0-1", "Q0", q0, "1"), record("q2-1", "Q2", q2, "2"), record("q3-1", "Q3", kept, "3")])
    assert out["comparable"] == "Q2 가 바꾼 항목을 Q3 이 안 바꿨다" and out["changed"]["Q3"] == ["R01"]
    moved = q3[:2] + [row("Q1", [], ranked(SOP03), query="물음", set_="golden", exclude=())]
    out = a.tally([record("q0-1", "Q0", q0, "1"), record("q2-1", "Q2", q2, "2"), record("q3-1", "Q3", moved, "3")])
    assert out["comparable"] == "음성 대조가 갈렸다" and out["negative"] == ["Q1"]
    # R05 처럼 Q2 가 안 바꾸는 항목에서 Q3 이 질문을 못 떼면 글자 수 검사도 ⊆ 검사도 건너뛴다 — 질문보다 긴 같은 글로 잡는다
    plain = row("R05", [SOP03], ranked(SOP03), query=ASK + "robotId=hum-04 remedyOutcome=WITHHELD")
    out = a.tally([record("q0-1", "Q0", q0 + [plain], "1"), record("q2-1", "Q2", q2 + [plain], "2"),
                   record("q3-1", "Q3", q3 + [plain], "3")])
    assert out["comparable"] == "Q3 이 물음 있는 글을 그대로 보냈다" and out["askKept"] == ["R05"] and out["askCut"] == []
    # 둘째 실행이라도 응답이 쓴 식별자 토큰이 보낸 글의 것과 다르면 대표 지표가 아니다
    renamed = [row("R01", [SOP01], ranked(SOP01), query="PAYLOAD_LOST 짧음", route="hybrid_only", used=["OTHER_TOKEN"]), *q3[1:]]
    out = a.tally([record("q0-1", "Q0", q0, "1"), record("q2-1", "Q2", q2, "2"), record("q3-1", "Q3", q3, "3"),
                   record("q3-2", "Q3", renamed, "4")])
    assert out["comparable"] == "식별자 토큰이 보낸 글과 다르다" and out["tokens"][0]["pass"] == "q3-2"


def test_같은_Q0_무리는_검색_열쇠로_보고_판이_다르면_결정론이_깨진다():
    """구성원의 답변 컨텍스트가 달라도 요청 해시가 같으면 같은 검색이다(`0f2b5ab`). 같은 실험군 실행끼리 상위 20 이 다르거나 khala 코드
    신원이 실행마다 다르면 대표 지표가 아니다."""
    q0 = [row(cid, [SOP03], ranked(SOP03), query="R04 같은 글", context=f"{cid} 의 자료") for cid in ("R04", "R10")]
    q3 = [row(cid, [SOP03], ranked(SOP03), query="R04 짧음", context=f"{cid} 의 자료") for cid in ("R04", "R10")]
    out = a.tally([record("q0-1", "Q0", q0, "1"), record("q3-1", "Q3", q3, "2")])
    assert out["comparable"] is None and out["arms"]["Q3"]["searches"] == {"all": 1, "labeled": 1}
    split = [q3[0], row("R10", [SOP03], ranked(SOP03), query="R10 다르게 짧음", context="R10 의 자료")]
    out = a.tally([record("q0-1", "Q0", q0, "1"), record("q3-1", "Q3", split, "2")])
    assert out["comparable"] == "결정론이 깨졌다" and out["drift"][-1]["why"] == "같은 Q0 무리인데 글이 다르다"
    drifted = [row(cid, [SOP03], ranked(SOP01), query="R04 짧음", context=f"{cid} 의 자료") for cid in ("R04", "R10")]
    out = a.tally([record("q0-1", "Q0", q0, "1"), record("q3-1", "Q3", q3, "2"), record("q3-2", "Q3", drifted, "3")])
    assert out["comparable"] == "결정론이 깨졌다"
    moved = record("q3-2", "Q3", q3, "3")
    moved["env"]["khalaBefore"] = {"head": "k1", "dirty": ""}
    out = a.tally([record("q0-1", "Q0", q0, "1"), record("q3-1", "Q3", q3, "2"), moved])
    assert out["comparable"] == "khala 코드 신원이 판마다 같지 않다"


def test_무효_판은_안_세고_검색_고장은_모든_판에서_센다():
    q0, q2, q3 = three_arms()
    broken = [row("R01", [SOP01], ranked(GUIDE), query="R01 PAYLOAD_LOST 긴 글")] + q0[1:]
    broken[0]["data"]["degraded"] = ["vector"]
    out = a.tally([record("q0-1", "Q0", broken, "1"), record("q2-1", "Q2", q2, "2"), record("q3-1", "Q3", q3, "3"),
                   record("q0-1r", "Q0", q0, "4")])
    assert [p["valid"] for p in out["passes"]] == [False, True, True, True]
    assert out["broken"]["Q0"] == {"rows": 1, "of": 6, "passes": 2} and out["comparable"] is None and out["advance"] == "Q3"


def test_판_하나는_질의만_실험군의_글로_바꾸고_경로를_적는다(monkeypatch):
    """웜업 뒤 항목마다 측정기 본문의 질의만 실험군의 글이고 `evidence_only` 만 더한다 — 질의를 뺀 본문은 Q0 실행과 바이트까지 같다.
    줄에 질의 길이 · 보낸 토큰 · 응답의 `route_used` 를 적는다. 401 · 403 · 422 면 곧바로 멈추고 기록을 안 쓴다."""
    written = []
    monkeypatch.setattr(ft, "write", lambda path, env, rows: written.append((env, rows)))
    monkeypatch.delenv("KHALA_ROOT", raising=False)
    sent = {}

    def fake_for(arm):
        def fake(method, url, headers, body):
            sent.setdefault(arm, []).append((url, body))
            return 200, {"success": True, "data": {"route_used": "hybrid_only"}}
        return fake

    for arm in ("Q0", "Q3"):
        a.run_pass(f"{arm.lower()}-1", arm, "unused.json", "t", "http://x", transport=fake_for(arm), clock=lambda: "now")
    built = qt.queries()
    expected_ids = [i["id"] for i in ft.items()]
    bodies = {arm: [body for _, body in sent[arm][1:]] for arm in sent}
    assert sent["Q3"][0] == ("http://x/search", ft.WARM)
    assert [b["query"] for b in bodies["Q3"]] == [a.texts(built[cid])["Q3"] for cid in expected_ids]
    assert all(b["evidence_only"] is True and "fusion_doc_agreement" not in b for b in bodies["Q3"])
    assert [{k: v for k, v in b.items() if k != "query"} for b in bodies["Q3"]] == \
           [{k: v for k, v in b.items() if k != "query"} for b in bodies["Q0"]], "질의 말고는 Q0 와 같다"
    env, rows = written[1]
    assert env["arm"] == "Q3" and env["flags"] == {"evidence_only": True} and len(rows) == 36
    assert {r["route"] for r in rows} == {"hybrid_only"}
    assert [r["queryChars"] for r in rows] == [len(b["query"]) for b in bodies["Q3"]]
    assert [r["sentTokens"] for r in rows] == [qt.tokens(b["query"]) for b in bodies["Q3"]]
    written.clear()

    def refused(method, url, headers, body):
        return (200, {}) if url.endswith("/search") else (422, {"detail": "extra_forbidden"})

    with pytest.raises(SystemExit, match="422"):
        a.run_pass("q2-1", "Q2", "unused.json", "t", "http://x", transport=refused, clock=lambda: "now")
    assert written == []
