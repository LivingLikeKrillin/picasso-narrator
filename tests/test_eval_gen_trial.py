"""생성 평가 — 설명 경로 파이프라인 실행. 설계서 `docs/superpowers/specs/2026-10-01-생성-판-설명-경로.md`. 가짜 응답으로 돈다."""

import copy

import pytest

from eval import ask_trial as at
from eval import fusion_trial as ft
from eval import gen_trial as g
from eval import query_trial as qt
from eval.run import fixture_history, load, query_for
from eval.score import QUERY
from recorder.record import from_answer

CARD = "절차: 첫 걸음\n먼저: 확인\n금지: 없음\n갈림: 관측\n근거 세기: 강함\n"


def answer_data(answer, cited=(), weak=False, failed=False, degraded=()):
    """`/search/answer` 의 `data` 한 벌 — 버전 필드와 검색 부분 실패 칸을 싣는다."""
    return {"answer": answer, "citations": [{"title": t, "section": "5", "verified": True} for t in cited],
            "evidence_snippets": [{"doc_title": t} for t in cited], "usage": {"model": "m"}, "prompt_version": "p",
            "corpus_version": "c", "search_fingerprint": "s", "degraded": list(degraded), "enrichment_failed": [],
            "weak_evidence": weak, "llm_failed": failed, "llm_failure_reason": "unavailable" if failed else None}


def test_계획은_G0_가_측정기의_질의이고_G3_은_Q3_에_Q0_자료_칸이다():
    """G0 는 `eval/measure.py` 와 같은 질의(`query_for`)에 답변 컨텍스트 없음, G3 은 질문 제거의 Q3 에 답변 컨텍스트 = 그 항목의 Q0. 질의 줄은 두
    실험군이 같은 요청이다. 홀수째 항목은 G0 먼저, 짝수째는 G3 먼저(설계서 §1). 답변 컨텍스트는 khala 상한 8,000 안이다."""
    work = g.plan()
    entries = load(g.GOLDEN)
    built = qt.queries()
    history = fixture_history()
    assert [item["entry"]["id"] for item in work] == [e["id"] for e in entries] and len(work) == 15
    for i, item in enumerate(work):
        e = item["entry"]
        assert item["order"] == (("G0", "G3") if i % 2 == 0 else ("G3", "G0"))
        assert item["G0"] == {"query": query_for(e, prior=history), "context": None}
        assert item["G3"]["query"] == at.texts(built[e["id"]])["Q3"]
        if e["kind"] == QUERY:
            assert item["G3"] == item["G0"], e["id"]
        else:
            assert item["G3"]["context"] == item["G0"]["query"] and item["G3"]["query"] != item["G0"]["query"], e["id"]
            assert len(item["G3"]["context"]) < 8000
    assert sum(item["G3"]["context"] is not None for item in work) == 12


def fake_khala(calls, outcome=None):
    def transport(method, url, headers, body):
        calls.append((url, copy.deepcopy(body)))
        if url.endswith("/search"):
            return 200, {"success": True, "data": {}}
        data = (outcome or (lambda body: answer_data(CARD + "본문", cited=("문서",))))(body)
        data["answer_context_len"] = len(body.get("answer_context") or "")
        return 200, {"success": True, "data": data}
    return transport


def test_한_바퀴는_항목마다_두_실험군을_번갈아_부르고_보낸_글을_적는다(monkeypatch):
    written = []
    monkeypatch.setattr(ft, "write", lambda path, env, rows: written.append((env, rows)))
    monkeypatch.delenv("KHALA_ROOT", raising=False)
    calls = []
    g.run_round("g-1", "unused.json", "t", "http://x", transport=fake_khala(calls), clock=lambda: "now")
    assert calls[0] == ("http://x/search", ft.WARM)
    work = g.plan()
    sent = calls[1:]
    assert len(sent) == 30
    for i, item in enumerate(work):
        for j, arm in enumerate(item["order"]):
            url, body = sent[2 * i + j]
            assert url == "http://x/search/answer" and body["query"] == item[arm]["query"]
            assert body.get("answer_context") == item[arm]["context"]
            assert ("answer_context" in body) == (item[arm]["context"] is not None), "안 실으면 키도 안 보낸다"
            assert body["identifier_channel"] is True and body["top_k"] == 20 and body["tenant"] == "picasso"
    env, rows = written[0]
    assert env["arms"] == ["G0", "G3"] and len(rows) == 30 and env["only"] is None
    assert all(r["sentQuerySha256"] == r["planQuerySha256"] and r["sentContextSha256"] == r["planContextSha256"] for r in rows)
    assert all(r["outcome"] == "GIVEN" and len(r["card"]) == 5 for r in rows)
    assert all(r["echo"]["answer_context_len"] == r["sentContextLen"] for r in rows)
    golden = {item["id"]: item for item in ft.items() if item["set"] == "golden"}
    for i, item in enumerate(work):
        g0_body = sent[2 * i + item["order"].index("G0")][1]
        measured, _, _ = ft.call(golden[item["entry"]["id"]], lambda *a: (200, {"success": True, "data": {}}), "http://x", "t")
        assert g0_body == measured, f"{item['entry']['id']}: G0 는 측정기와 같은 본문이다"
    # 고장 항목 다시 — 그 항목들만, 차례 규칙은 골든셋 차례 그대로(G1 은 홀수째라 G0 먼저, G2 는 짝수째라 G3 먼저)
    calls.clear()
    g.run_round("g-1r", "unused.json", "t", "http://x", transport=fake_khala(calls), clock=lambda: "now", only={"G2", "G1"})
    env, rows = written[1]
    assert env["only"] == ["G1", "G2"] and [(r["id"], r["arm"]) for r in rows] == [("G1", "G0"), ("G1", "G3"), ("G2", "G3"), ("G2", "G0")]
    with pytest.raises(SystemExit, match="모르는 항목"):
        g.run_round("g-1r", "unused.json", "t", "http://x", transport=fake_khala(calls), clock=lambda: "now", only={"G99"})


def test_422_나_생성_실패_연속_둘이면_기록_없이_멈춘다(monkeypatch):
    written = []
    monkeypatch.setattr(ft, "write", lambda path, env, rows: written.append((env, rows)))
    monkeypatch.delenv("KHALA_ROOT", raising=False)

    def refused(method, url, headers, body):
        return (200, {"success": True, "data": {}}) if url.endswith("/search") else (422, {"detail": "extra_forbidden"})

    with pytest.raises(SystemExit, match="422"):
        g.run_round("g-1", "unused.json", "t", "http://x", transport=refused, clock=lambda: "now")
    calls = []
    with pytest.raises(SystemExit, match="연속"):
        g.run_round("g-1", "unused.json", "t", "http://x", clock=lambda: "now",
                    transport=fake_khala(calls, outcome=lambda body: answer_data("", failed=True)))
    assert written == [] and len(calls) == 1 + 2 * g.LIMIT, "생성 실패는 시도 한도까지 다시 하고 둘째에서 접는다"


def record_of(make):
    """계획대로 보낸 파이프라인 실행의 기록 — `make(entry, arm) -> data` 로 답을 정한다."""
    rows = []
    for item in g.plan():
        e = item["entry"]
        for arm in item["order"]:
            body = {"query": item[arm]["query"], **({"answer_context": item[arm]["context"]} if item[arm]["context"] else {})}
            record = from_answer(("golden", e["id"], arm), make(e, arm))
            echo = {"answer_context_len": len(item[arm]["context"] or "")}
            rows.append(g.row_of(e, arm, item[arm], [body], record, at="now", echo=echo))
    return {"env": {"pass": "g-1", "khalaBefore": {"head": "k"}, "khalaAfter": {"head": "k"}}, "rows": rows}


def cite_procedure(lose=()):
    """사건은 답변 카드와 함께 기대 절차를 인용하고(G0 는 `lose` 의 항목에서 못 함), 질의 줄은 근거 없음으로 물러선다."""
    def make(e, arm):
        if e["kind"] == QUERY:
            return answer_data("근거에 없다", weak=True)
        doc = (e.get("procedure") or {}).get("doc")
        if doc and not (arm == "G0" and e["id"] in lose):
            return answer_data(CARD + f"본문 [출처: {doc}, 5]", cited=(doc,))
        return answer_data(CARD + "본문 [출처: 다른 문서, 1]", cited=("다른 문서",))
    return make


def test_셈은_기록만으로_두_실험군을_채점하고_넘김을_정한다():
    """줄을 `Record` 로 되지어 골든셋 채점에 넘긴다. 가드레일 지표 일곱이 지켜지고 절차 문서 인용이 G3 ≥ G0 이면 승격한다."""
    out = g.tally(record_of(cite_procedure(lose=("G1", "G6"))))
    assert out["comparable"] is None and out["missing"] == [] and out["treatment"] == []
    g0, g3 = out["arms"]["G0"], out["arms"]["G3"]
    assert g3["procedureDoc"][0] == g0["procedureDoc"][0] + 2 and g3["procedureDoc"][1] == g0["procedureDoc"][1] == 10
    assert g0["cards"] == g3["cards"] == 11 and g3["admitsNoEvidence"] == (3, 3)
    assert all(out["guards"].values()) and out["primary"] is True and out["advance"] is True
    assert out["arms"]["G3"]["citedWhenBoth"] == out["arms"]["G0"]["citedWhenBoth"] == (8, 8), "G0 가 못 받은 G1 · G6 은 뺀다"
    assert out["items"][0]["G3"]["procedureCited"] is True and out["items"][0]["G0"]["procedureCited"] is False
    lines = g.report_lines(out)
    assert lines[-1] == "다음 단계로 넘김 — G3" and len([line for line in lines if line.startswith("  ")]) == 15
    worse = g.tally(record_of(lambda e, arm: cite_procedure(lose=("G1",))(e, "G0" if arm == "G3" else "G3")))
    assert worse["primary"] is False and worse["advance"] is False, "G3 이 절차 인용을 잃으면 안 넘긴다"
    assert g.report_lines(worse)[-1] == "다음 단계로 넘김 — 없음"


def test_검색이_더_준_몫을_빼고_둘_다_받은_사건의_인용이_줄면_넘기지_않는다():
    """⛔ 독립 검토 M1 — G3 은 검색만으로 기대 절차를 더 받고 시작한다. G0 가 못 받은 셋(G1 · G6 · G11)을 G3 이 인용하면 1차 결과 변수는
    같아도, 둘 다 받은 사건에서 G3 이 둘 넘게 덜 인용하면 답변 컨텍스트의 질문을 안 따른 것이라 승격하지 않는다."""
    def make(e, arm):
        if e["kind"] == QUERY:
            return answer_data("근거에 없다", weak=True)
        doc = (e.get("procedure") or {}).get("doc")
        if not doc:
            return answer_data(CARD + "본문 [출처: 다른 문서, 1]", cited=("다른 문서",))
        evidence = (doc, "다른 문서") if not (arm == "G0" and e["id"] in ("G1", "G6", "G11")) else ("다른 문서",)
        cites = doc if (arm == "G0" and e["id"] not in ("G1", "G6", "G11")) or (arm == "G3" and e["id"] in ("G1", "G6", "G11")) \
            else "다른 문서"
        data = answer_data(CARD + f"본문 [출처: {cites}, 5]", cited=(cites,))
        data["evidence_snippets"] = [{"doc_title": t} for t in evidence]
        return data

    out = g.tally(record_of(make))
    g0, g3 = out["arms"]["G0"], out["arms"]["G3"]
    assert out["comparable"] is None and len(out["bothRetrieved"]) == 7
    assert g3["procedureDoc"][0] == 3 and g0["procedureDoc"][0] == 7 and g0["citedWhenBoth"] == (7, 7)
    assert g3["citedWhenBoth"] == (0, 7) and out["guards"]["citedWhenBoth"] is False and out["advance"] is False


def test_성립이_깨지면_판정하지_않는다():
    """빠진 줄 · 버전 필드 둘 · 검색 부분 실패 · 계획과 다른 요청 · khala 코드 신원이 바뀜이면 승격을 정하지 않는다(설계서 §3)."""
    base = record_of(cite_procedure())
    short = copy.deepcopy(base)
    short["rows"] = short["rows"][:-1]
    out = g.tally(short)
    assert out["comparable"] == "빠진 줄이 있다" and "arms" not in out
    assert g.report_lines(out)[-1] == "다음 단계로 넘김 — 판정 안 함"
    drift = copy.deepcopy(base)
    drift["rows"][3]["diagnostics"]["corpus_version"] = "c2"
    assert g.tally(drift)["comparable"] == "판 칸이 한 벌이 아니다"
    broken = copy.deepcopy(base)
    broken["rows"][5]["diagnostics"]["degraded"] = ["vector"]
    out = g.tally(broken)
    assert out["comparable"] == "검색 고장이 남았다" and out["advance"] is False
    rerun = {"env": {"pass": "g-1r", "at": "2", "only": [base["rows"][5]["id"]], "khalaBefore": {"head": "k"},
                     "khalaAfter": {"head": "k"}}, "rows": [copy.deepcopy(base["rows"][5])]}
    broken["env"]["at"] = "1"
    out = g.tally([rerun, broken])
    assert out["comparable"] is None and out["pass"] == "g-1 + g-1r", "다시 부른 기록의 줄이 뒤에 와서 이긴다"
    other = copy.deepcopy(rerun)
    other["env"]["narratorCommit"] = "c2"
    assert g.tally([broken, other])["comparable"] == "narrator 커밋이 기록마다 다르다"
    # 다시 부른 줄은 앞에서 고장 · 다시 할 실패였던 것만, 한 번만 덮는다(검토 S2)
    fine = copy.deepcopy(base)
    fine["env"]["at"] = "1"
    out = g.tally([fine, rerun])
    assert out["comparable"] == "다시 부른 줄이 고장 · 실패가 아니었거나 두 번이다" and out["badReruns"]
    twice = copy.deepcopy(rerun)
    twice["env"]["at"] = "3"
    assert g.tally([broken, rerun, twice])["comparable"] == "다시 부른 줄이 고장 · 실패가 아니었거나 두 번이다"
    # 다시 할 만한 생성 실패는 다시 불러야 하고, 다시 불러도 실패면 그대로 센다(검토 M2)
    failed = copy.deepcopy(base)
    failed["env"]["at"] = "1"
    row = failed["rows"][4]
    row.update(outcome="GENERATION_FAILED", reason="timeout", answer="", citations=[], echo=None)
    assert g.tally(failed)["comparable"] == "다시 부를 실패가 남았다"
    again = {"env": {"pass": "g-1r", "at": "2", "only": [row["id"]], "khalaBefore": {"head": "k"}, "khalaAfter": {"head": "k"}},
             "rows": [copy.deepcopy(row)]}
    out = g.tally([failed, again])
    assert out["comparable"] is None and out["failedAfterRerun"] == [f"{row['id']} {row['arm']}"]
    unechoed = copy.deepcopy(base)
    unechoed["rows"][0]["echo"] = None
    assert g.tally(unechoed)["comparable"] == "처치가 계획과 다르다", "되울림 없는 답은 처치를 못 본다"
    swapped = copy.deepcopy(base)
    first_g3 = next(r for r in swapped["rows"] if r["arm"] == "G3" and r["kind"] != QUERY)
    first_g3["sentContextSha256"] = first_g3["planContextSha256"] = None
    assert g.tally(swapped)["comparable"] == "처치가 계획과 다르다"
    moved = copy.deepcopy(base)
    moved["env"]["khalaAfter"] = {"head": "k2"}
    assert g.tally(moved)["comparable"] == "khala 코드 신원이 판 앞뒤로 다르다"


def test_가드는_한_칸을_봐주고_그보다_나빠지면_막는다():
    def arm(cards=11, failed=0, uncited=0, numbers=0, cite=0.95, clean=7, admits=(3, 3), both=7):
        return {"cards": cards, "failed": failed, "uncited": uncited, "ungroundedNumbers": numbers, "citationPass": cite,
                "contradictionFree": (clean, 7), "admitsNoEvidence": admits, "citedWhenBoth": (both, 7)}

    base = arm()
    assert all(g.guards(base, arm(cards=10, uncited=1, numbers=1, cite=0.90, clean=6, both=6)).values()), "한 칸은 봐준다"
    blocked = g.guards(base, arm(cards=9, failed=1, uncited=2, numbers=2, cite=0.89, clean=5, admits=(2, 3), both=5))
    assert not any(blocked.values()) and len(blocked) == 8
    assert g.guards(arm(admits=(2, 3)), arm(admits=(2, 3)))["admitsNoEvidence"] is True, "질의 줄은 두 실험군이 같으면 선다"
    assert g.guards(base, arm(cite=None))["citationPass"] is False, "잴 것이 없으면 선 것이 아니다"
