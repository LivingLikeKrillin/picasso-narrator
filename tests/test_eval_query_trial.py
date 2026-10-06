"""질의 축소 — 설계서 `docs/superpowers/specs/2026-10-01-질의-줄이기.md`. 가짜 응답으로 돈다."""

import pytest

from composer.query import ASK, Query
from diagnose.core import query_text
from eval import fusion_trial as ft
from eval import query_trial as q
from eval.recommend import prepare
from eval.recommend_score import load_cases
from eval.run import fixture_history, load, query_for

SOP01 = "SOP-01 파지 실패와 잔여 파지 처리"
SOP03 = "SOP-03 자재 결품과 대체 슬롯 운용"
GUIDE = "합성 SOP 6종 — 코퍼스 안내"
EXCLUDE = ("spec", "design_doc", "case")


def snip(doc, rank, rid=None):
    return {"chunk_rid": rid or f"{doc[:6]}-{rank}", "doc_title": doc, "section_path": "5", "rank": rank, "score": 0.5,
            "text": "가" * 300}


def ranked(*docs):
    titles = list(docs) + [GUIDE] * (20 - len(docs))
    return [snip(title, i + 1, rid=f"r{i + 1}-{title[:6]}") for i, title in enumerate(titles)]


def row(cid, expected, snippets, query="질의", set_="recommend", used=None, exclude=EXCLUDE, context=None):
    item = {"id": cid, "set": set_, "expected": list(expected)}
    body = {"query": query, "tenant": "picasso", "top_k": 20, "identifier_channel": True}
    if exclude:
        body["exclude_doc_types"] = list(exclude)
    if context is not None:
        body["answer_context"] = context
    sent = q.tokens(query)
    data = {"evidence_only": True, "fusion_doc_agreement": False, "identifier_channel_asked": True, "answer_context_len": 0,
            "searched_tenants": ["picasso"], "degraded": [], "enrichment_failed": [], "prompt_version": "p",
            "corpus_version": "c", "search_fingerprint": "s", "identifier_channel": sent if used is None else used,
            "top_distance": 0.3, "top_bm25": 1.2, "weak_evidence": False, "excluded_doc_types": list(exclude),
            "timing_ms": {"total_ms": 100}, "evidence_snippets": snippets}
    out = ft.row_of(item, body, 200, {"success": True, "data": data})
    out.update(queryChars=len(query), sentTokens=sent)
    return out


def record(name, arm, rows, at):
    return {"env": {"pass": name, "arm": arm, "at": at, "narratorCommit": "c0"}, "rows": rows}


def test_Q0_글은_운영_경로의_질의와_같다():
    """세 글은 운영 경로와 같은 재료의 `Query` 에서 짓는다 — Q0 는 `diagnose.core.query_text` 와 `eval.run.query_for` 의 글
    그대로여야 한다(설계서 §1)."""
    built = q.queries()
    for prep in prepare(load_cases()):
        if not prep["case"].get("repeatOf"):
            assert q.texts(built[prep["case"]["id"]])["Q0"] == query_text(prep["request"].snapshot) == prep["query"]
    history = fixture_history()
    for entry in load(str(ft.GOLDEN)):
        assert q.texts(built[entry["id"]])["Q0"] == query_for(entry, prior=history), entry["id"]
    assert len(built) == 36 and [i["id"] for i in q.items("Q0")] == [i["id"] for i in ft.items()]
    assert all(a["query"] == b["query"] for a, b in zip(q.items("Q0"), ft.items()))


def test_Q1_은_구조_사실을_빼고_Q2_는_Q0_의_식별자_토큰을_차례까지_지킨다():
    """Q1 은 사전 · 목록 값의 사실을 뺀다. Q2 는 Q0 의 식별자 토큰 전부를 Q0 의 차례로 질문 바로 뒤에 둔다 — 식별자 채널이 받는
    글이 Q0 와 차례까지 같다(khala 의 벡터 다리는 차례를 본다). 조회 지시(`LOOKUP`)는 세 글 모두 맨 앞에 남는다."""
    query = Query(facts={"failureClass": "PAYLOAD_LOST",
                         "fault": {"errorType": "SKILL_EXECUTION_FAILED", "references": [{"key": "KEY_SKILL_ID"}]},
                         "observedHold": "HOLD_KIND_EMPTY", "unresolved": False})
    three = q.texts(query)
    assert three["Q0"] == query.text and "fault=" in three["Q0"]
    assert three["Q1"] == ASK + "failureClass=PAYLOAD_LOST observedHold=HOLD_KIND_EMPTY unresolved=false"
    assert three["Q2"] == (ASK + "PAYLOAD_LOST SKILL_EXECUTION_FAILED KEY_SKILL_ID HOLD_KIND_EMPTY "
                           "failureClass=PAYLOAD_LOST observedHold=HOLD_KIND_EMPTY unresolved=false")
    assert q.tokens(three["Q2"]) == q.tokens(three["Q0"]), "차례까지"
    looked = q.texts(Query(facts={"failureClass": "UNCLASSIFIED", "fault": {"vendorDetail": "X_FIXTURE_E4412"}},
                           lookup="벤더 정지 코드 X_FIXTURE_E4412 의 뜻. "))
    assert all(text.startswith("벤더 정지 코드 X_FIXTURE_E4412 의 뜻. ") for text in looked.values())
    assert q.tokens(looked["Q2"]) == q.tokens(looked["Q0"])
    assert q.texts("물음 그대로") == {"Q0": "물음 그대로", "Q1": "물음 그대로", "Q2": "물음 그대로"}
    built = q.queries()
    unchanged = sorted(cid for cid, query in built.items() if len(set(q.texts(query).values())) == 1)
    assert unchanged == ["Q1", "Q2", "Q3", "R05"], "구조 사실이 없는 항목만 세 글이 같다"
    for cid, query in built.items():
        three = q.texts(query)
        assert len(three["Q1"]) < 1000 and len(three["Q2"]) < 1000, cid
        assert q.tokens(three["Q2"]) == q.tokens(three["Q0"]), cid
        if q.tokens(three["Q1"]) == q.tokens(three["Q0"]):
            assert three["Q2"] == three["Q1"], cid


def test_식별자_토큰은_khala_의_정규식과_상한이다():
    """대문자로 시작하고 밑줄이 하나 이상 — 처음 나온 차례, 겹침 없음, 열둘까지. 민낯 약어와 하이픈 식별자는 안 걸린다."""
    assert q.tokens("failureClass=PAYLOAD_LOST X_FIXTURE_E4412 API SOP-01 HOLD_KIND_EMPTY PAYLOAD_LOST") == [
        "PAYLOAD_LOST", "X_FIXTURE_E4412", "HOLD_KIND_EMPTY"]
    assert q.tokens(None) == [] and q.tokens("소문자_토큰 abc_def") == []
    assert len(q.tokens(" ".join(f"T_{i}" for i in range(20)))) == 12


def three_arms():
    """R01 은 Q1 · Q2 에서 SOP-01 이 들고, R03 은 Q1 에서 SOP-03 을 잃고 Q2 에서 지킨다. 질의 줄은 세 글이 같다."""
    q0 = [row("R01", [SOP01], ranked(GUIDE), query="R01 PAYLOAD_LOST 긴 글"),
          row("R03", [SOP03], ranked(SOP03), query="R03 HOLD_KIND_EMPTY 긴 글"),
          row("Q1", [], ranked(GUIDE), query="물음", set_="golden", exclude=())]
    q1 = [row("R01", [SOP01], ranked(SOP01), query="R01 PAYLOAD_LOST"),
          row("R03", [SOP03], ranked(GUIDE), query="R03"),
          row("Q1", [], ranked(GUIDE), query="물음", set_="golden", exclude=())]
    q2 = [row("R01", [SOP01], ranked(SOP01), query="R01 PAYLOAD_LOST"),
          row("R03", [SOP03], ranked(SOP03), query="R03 HOLD_KIND_EMPTY"),
          row("Q1", [], ranked(GUIDE), query="물음", set_="golden", exclude=())]
    return q0, q1, q2


def test_셈은_Q0_무리로_짝짓고_넘길_실험군을_고른다():
    q0, q1, q2 = three_arms()
    out = q.tally([record("q0-1", "Q0", q0, "1"), record("q1-1", "Q1", q1, "2"), record("q2-1", "Q2", q2, "3")])
    assert out["comparable"] is None and out["n"] == 2
    arms = out["arms"]
    assert arms["Q0"]["headline"][:2] == (1, 2) and arms["Q1"]["headline"][:2] == (1, 2) and arms["Q2"]["headline"][:2] == (2, 2)
    assert arms["Q1"]["onlyQ0"] == [["R03"]] and arms["Q1"]["onlyQ1"] == [["R01"]] and arms["Q1"]["p"] is None
    assert arms["Q2"]["pairs"] == (2, 2) and arms["Q1"]["pairs"] == (1, 2) and arms["Q1"]["r01"] == {SOP01: True}
    assert out["changed"] == {"Q1": ["R01", "R03"], "Q2": ["R01", "R03"]} and out["unchanged"] == ["Q1"]
    assert out["negative"] == [] and out["q2Tokens"] == [] and out["q1SameTokens"] == 2
    assert out["q1VsQ2"]["onlyQ2"] == [["R03"]] and out["q1VsQ2"]["onlyQ1"] == []
    assert out["advance"] == "Q2", "Q1 은 Q0 와 같아 못 넘는다"
    assert arms["Q1"]["secondary"]["queryChars"]["max"] < arms["Q0"]["secondary"]["queryChars"]["max"]
    assert arms["Q1"]["secondary"]["evidenceChars"] == 20 * 300 and arms["Q1"]["secondary"]["latency"]["vsQ0Mean"] == 0
    lines = q.report_lines(out)
    assert lines[2].startswith("khala 코드 신원 한 벌 · 결정론 어긋남 없음") and lines[3].startswith("머리 수치 — ")
    assert any(line.startswith("Q1 대 Q2 ") for line in lines) and lines[-1] == "다음 단계로 넘길 실험군 — Q2"


def test_실험군에서_합쳐진_검색은_적고_p_값을_안_낸다():
    """정형 데이터를 빼면 서로 다른 Q0 검색이 같은 글이 될 수 있다(재발 횟수만 달랐던 R01 과 G1 처럼) — 단위가 독립이 아니라 합쳐짐을
    적고 p 값을 안 낸다."""
    q0 = [row("R01", [SOP01], ranked(GUIDE), query="R01 PAYLOAD_LOST 재발 없음"),
          row("G1", [SOP01], ranked(GUIDE), query="R01 PAYLOAD_LOST 재발 하나", set_="golden")]
    q1 = [row(cid, [SOP01], ranked(SOP01), query="PAYLOAD_LOST 줄임", set_=s) for cid, s in (("R01", "recommend"), ("G1", "golden"))]
    out = q.tally([record("q0-1", "Q0", q0, "1"), record("q1-1", "Q1", q1, "2")])
    assert out["arms"]["Q0"]["searches"] == {"all": 2, "labeled": 2} and out["arms"]["Q1"]["searches"] == {"all": 1, "labeled": 1}
    assert out["arms"]["Q1"]["merges"] == [["R01", "G1"]] and out["arms"]["Q1"]["p"] is None
    assert out["arms"]["Q1"]["headline"][:2] == (2, 2), "합쳐진 검색은 Q0 단위 수만큼 센다"
    assert out["advance"] is None, "Q2 판이 없으면 정하지 않는다"
    assert q.report_lines(out)[-1] == "다음 단계로 넘길 실험군 — 판정 안 함", "「없음」이 아니다"


def test_같은_Q0_무리는_판_안에서도_실험군의_글에서도_같아야_한다():
    """같은 Q0 검색의 구성원(R04 ≡ R10 처럼)은 한 실행 안에서 상위 20 이 같아야 하고, 실험군에서도 글이 같아야 한다 — 같은 사실에서
    지었기 때문이다. 어긋나면 결정론이 깨진 것이다. 답변 컨텍스트는 사례마다 달라도 된다 — 검색에 안 쓰이므로 무리는 요청 해시로 본다
    (⛔ 본문 해시로 견주던 평가 도구가 첫 실행들에서 모든 무리를 「글이 다르다」로 잘못 걸었다, 2026-10-01)."""
    q0 = [row(cid, [SOP03], ranked(SOP03), query="R04 같은 글", context=f"{cid} 의 자료") for cid in ("R04", "R10")]
    q1 = [row(cid, [SOP03], ranked(SOP03), query="R04 줄임", context=f"{cid} 의 자료") for cid in ("R04", "R10")]
    out = q.tally([record("q0-1", "Q0", q0, "1"), record("q1-1", "Q1", q1, "2")])
    assert out["comparable"] is None and out["n"] == 1 and out["arms"]["Q1"]["searches"] == {"all": 1, "labeled": 1}
    assert out["arms"]["Q1"]["merges"] == [], "한 Q0 무리는 합쳐짐이 아니다"
    split = [row("R04", [SOP03], ranked(SOP03), query="R04 줄임"), row("R10", [SOP03], ranked(SOP03), query="R10 다르게 줄임")]
    out = q.tally([record("q0-1", "Q0", q0, "1"), record("q1-1", "Q1", split, "2")])
    assert out["comparable"] == "결정론이 깨졌다" and out["drift"][-1] == {"pass": "q1-1", "ids": ["R04", "R10"],
                                                                     "why": "같은 Q0 무리인데 글이 다르다"}
    torn = [row("R04", [SOP03], ranked(SOP03), query="R04 같은 글"), row("R10", [SOP03], ranked(GUIDE), query="R04 같은 글")]
    out = q.tally([record("q0-1", "Q0", torn, "1"), record("q1-1", "Q1", q1, "2")])
    assert out["comparable"] == "결정론이 깨졌다" and {"pass": "q0-1", "ids": ["R04", "R10"]} in out["drift"]


def test_결정론_토큰_음성_대조가_깨지면_머리_수치가_아니다():
    """khala 코드 신원이 실행마다 같지 않거나, 같은 실험군 실행끼리 다르거나, 응답이 쓴 식별자 토큰이 보낸 글의 것과 다르거나(둘째 실행이라도),
    Q2 의 토큰이 Q0 와 다르거나, 세 글이 같은 항목의 상위 20 이 실험군 사이에 갈리면 대표 지표가 아니고 승격할 실험군도 정하지 않는다."""
    q0, q1, q2 = three_arms()
    moved = record("q1-2", "Q1", q1, "3")
    moved["env"]["khalaAfter"] = {"head": "k1", "dirty": ""}
    out = q.tally([record("q0-1", "Q0", q0, "1"), record("q1-1", "Q1", q1, "2"), moved])
    assert out["comparable"] == "khala 코드 신원이 판마다 같지 않다" and out["khalaChanged"] is True and out["advance"] is None
    drifted = [row("R01", [SOP01], ranked(SOP03), query="R01 PAYLOAD_LOST 긴 글")] + q0[1:]
    out = q.tally([record("q0-1", "Q0", q0, "1"), record("q1-1", "Q1", q1, "2"), record("q0-2", "Q0", drifted, "3")])
    assert out["comparable"] == "결정론이 깨졌다" and out["advance"] is None
    renamed = [row("R01", [SOP01], ranked(SOP01), query="R01 PAYLOAD_LOST", used=["OTHER_TOKEN"])] + q1[1:]
    out = q.tally([record("q0-1", "Q0", q0, "1"), record("q1-1", "Q1", q1, "2"), record("q1-2", "Q1", renamed, "3")])
    assert out["comparable"] == "식별자 토큰이 보낸 글과 다르다", "둘째 판의 토큰도 본다"
    reordered = [row("R01", [SOP01], ranked(SOP01), query="R01 PAYLOAD_LOST"),
                 row("R03", [SOP03], ranked(SOP03), query="R03 KEY_SKILL_ID HOLD_KIND_EMPTY")] + q2[2:]
    out = q.tally([record("q0-1", "Q0", q0, "1"), record("q2-1", "Q2", reordered, "2")])
    assert out["comparable"] == "Q2 의 식별자 토큰이 Q0 와 다르다" and out["q2Tokens"] == ["R03"]
    moved = q1[:2] + [row("Q1", [], ranked(SOP03), query="물음", set_="golden", exclude=())]
    out = q.tally([record("q0-1", "Q0", q0, "1"), record("q1-1", "Q1", moved, "2")])
    assert out["comparable"] == "음성 대조가 갈렸다" and out["negative"] == ["Q1"]
    lines = q.report_lines(out)
    assert lines[-1] == "다음 단계로 넘길 실험군 — 판정 안 함"


def test_무효_판은_안_세고_검색_고장은_모든_판에서_센다():
    q0, q1, q2 = three_arms()
    broken = [row("R01", [SOP01], ranked(GUIDE), query="R01 PAYLOAD_LOST 긴 글")] + q0[1:]
    broken[0]["data"]["degraded"] = ["vector"]
    out = q.tally([record("q0-1", "Q0", broken, "1"), record("q0-1r", "Q0", q0, "2"), record("q1-1", "Q1", q1, "3"),
                   record("q2-1", "Q2", q2, "4")])
    assert [p["valid"] for p in out["passes"]] == [False, True, True, True]
    assert out["broken"]["Q0"] == {"rows": 1, "of": 6, "passes": 2} and out["broken"]["Q1"] == {"rows": 0, "of": 3, "passes": 1}
    assert out["comparable"] is None and out["arms"]["Q0"]["secondary"]["latency"]["passes"] == 1


def test_넘길_실험군은_둘_다_낮지_않고_하나는_높고_틀린_절차가_늘지_않아야_한다():
    def arm(head, pairs, wrong=10):
        return {"headline": (head, 27, None), "pairs": (pairs, 40), "secondary": {"wrong": {"labeled": wrong}}}

    base = arm(24, 32)
    assert q.advance({"Q0": base, "Q1": arm(24, 32), "Q2": arm(24, 32)}) is None, "같으면 안 넘는다"
    assert q.advance({"Q0": base, "Q1": arm(26, 31), "Q2": arm(23, 35)}) is None, "하나라도 낮으면 안 넘는다"
    assert q.advance({"Q0": base, "Q1": arm(25, 33), "Q2": arm(24, 34)}) == "Q2", "짝이 많은 쪽"
    assert q.advance({"Q0": base, "Q1": arm(26, 34), "Q2": arm(25, 34)}) == "Q1", "짝이 같으면 머리 수치"
    assert q.advance({"Q0": base, "Q1": arm(25, 34), "Q2": arm(25, 34)}) == "Q2", "그래도 같으면 Q2"
    assert q.advance({"Q0": base, "Q1": arm(27, 40, wrong=11), "Q2": arm(24, 32)}) is None, "틀린 절차가 늘면 안 넘는다"
    assert q.advance({"Q0": base, "Q1": arm(27, 40)}) is None, "세 실험군이 다 있어야 정한다"


def test_판_하나는_질의만_실험군의_글로_바꿔_보낸다(monkeypatch):
    """웜업 뒤 항목마다 측정기 본문의 질의만 실험군의 글이고 `evidence_only` 만 더한다(F1 칸 없음) — 질의를 뺀 본문은 Q0 실행과
    바이트까지 같다. 줄에 질의 길이와 보낸 토큰을 적는다. 401 · 403 · 422 면 곧바로 멈추고 기록을 안 쓴다."""
    written = []
    monkeypatch.setattr(ft, "write", lambda path, env, rows: written.append((env, rows)))
    monkeypatch.delenv("KHALA_ROOT", raising=False)
    sent = {}

    def fake_for(arm):
        def fake(method, url, headers, body):
            sent.setdefault(arm, []).append((url, body))
            return 200, {"success": True, "data": {}}
        return fake

    for arm in ("Q0", "Q1"):
        q.run_pass(f"{arm.lower()}-1", arm, "unused.json", "t", "http://x", transport=fake_for(arm), clock=lambda: "now")
    assert sent["Q1"][0] == ("http://x/search", ft.WARM)
    built = q.queries()
    expected_ids = [i["id"] for i in ft.items()]
    bodies = {arm: [body for _, body in sent[arm][1:]] for arm in sent}
    assert [b["query"] for b in bodies["Q1"]] == [q.texts(built[cid])["Q1"] for cid in expected_ids]
    assert all(b["evidence_only"] is True and "fusion_doc_agreement" not in b for b in bodies["Q1"])
    assert [{k: v for k, v in b.items() if k != "query"} for b in bodies["Q1"]] == \
           [{k: v for k, v in b.items() if k != "query"} for b in bodies["Q0"]], "질의 말고는 Q0 와 같다"
    env, rows = written[1]
    assert env["arm"] == "Q1" and env["flags"] == {"evidence_only": True} and len(rows) == 36
    assert [r["queryChars"] for r in rows] == [len(b["query"]) for b in bodies["Q1"]]
    assert [r["sentTokens"] for r in rows] == [q.tokens(b["query"]) for b in bodies["Q1"]]
    written.clear()

    def refused(method, url, headers, body):
        return (200, {}) if url.endswith("/search") else (422, {"detail": "extra_forbidden"})

    with pytest.raises(SystemExit, match="422"):
        q.run_pass("q2-1", "Q2", "unused.json", "t", "http://x", transport=refused, clock=lambda: "now")
    assert written == []
