"""융합 실험 두 실행 — 설계서 `docs/superpowers/specs/2026-10-01-융합-처치-두-판.md`. 가짜 응답으로 돈다."""

import pytest

from eval import fusion_trial as f
from eval import recommend

SOP01 = "SOP-01 파지 실패와 잔여 파지 처리"
SOP03 = "SOP-03 자재 결품과 대체 슬롯 운용"
GUIDE = "합성 SOP 6종 — 코퍼스 안내"
VERSIONS = ("p", "c", "s")
RECOMMEND_EXCLUDE = ("spec", "design_doc", "case")


def data(snippets, arm="T0", exclude=RECOMMEND_EXCLUDE, **extra):
    """근거만 받는 응답의 `data` — 기본은 유효한 모양."""
    base = {"evidence_only": True, "fusion_doc_agreement": arm == "F1", "identifier_channel_asked": True,
            "answer_context_len": 0, "searched_tenants": ["picasso"], "degraded": [], "enrichment_failed": [],
            "prompt_version": "p", "corpus_version": "c", "search_fingerprint": "s",
            "identifier_channel": ["PAYLOAD_LOST"], "top_distance": 0.3, "top_bm25": 1.2, "weak_evidence": False,
            "excluded_doc_types": list(exclude), "timing_ms": {"total_ms": 100}, "evidence_snippets": snippets}
    base.update(extra)
    return base


def snip(doc, rank, rid=None, score=0.5):
    return {"chunk_rid": rid or f"{doc[:6]}-{rank}", "doc_title": doc, "section_path": "5", "rank": rank, "score": score,
            "text": "가" * 300}


def ranked(*docs):
    """상위 20 — `docs` 를 1위부터 차례로, 모자라면 코퍼스 안내로 채운다."""
    titles = list(docs) + [GUIDE] * (20 - len(docs))
    return [snip(title, i + 1, rid=f"r{i + 1}-{title[:6]}") for i, title in enumerate(titles)]


def row(cid, expected, snippets, arm="T0", key=None, set_="recommend", exclude=RECOMMEND_EXCLUDE, status=200, **extra):
    item = {"id": cid, "set": set_, "expected": list(expected)}
    body = {"query": key or cid, "tenant": "picasso", "top_k": 20, "identifier_channel": True}
    if exclude:
        body["exclude_doc_types"] = list(exclude)
    response = ({"success": True, "data": data(snippets, arm=arm, exclude=exclude, **extra)} if status == 200
                else {"detail": "끊김"})
    return f.row_of(item, body, status, response)


def record(name, arm, rows, at, commit="c0"):
    return {"env": {"pass": name, "arm": arm, "at": at, "narratorCommit": commit}, "rows": rows}


def test_보내는_본문은_측정기의_본문에_두_칸을_더한_것이다():
    """권고는 `client_for` 가, 골든은 `eval/measure.py` 의 `CLIENTS` 와 같은 인자가 지은 본문에 `evidence_only` 와 실험군의 칸만
    더한다. T0 는 F1 키를 안 보낸다(khala 요청 문서 36). 기록하는 본문은 칸을 더하기 전의 것이다."""
    sent = []

    def fake(method, url, headers, body):
        sent.append(body)
        return 200, {"success": True, "data": data([])}

    items = {item["id"]: item for item in f.items()}
    for arm in ("T0", "F1"):
        def flagged(method, url, headers, body, arm=arm):
            return fake(method, url, headers, {**body, **f.FLAGS, **f.ARMS[arm]})

        for cid in ("R01", "G1", "S1", "Q1"):
            body, status, _ = f.call(items[cid], flagged, "http://x", "t")
            assert not {"evidence_only", "fusion_doc_agreement"} & set(body), "칸을 더하기 전의 본문을 잡는다"
            assert status == 200 and sent[-1] == {**body, **f.FLAGS, **f.ARMS[arm]}
            assert ("fusion_doc_agreement" in sent[-1]) is (arm == "F1")
    seen = []

    def capture(method, url, headers, body):
        seen.append(body)
        return 200, {}

    recommend.client_for("http://x", "t", transport=capture)(items["R01"]["context"])(items["R01"]["query"])
    body_r01, _, _ = f.call(items["R01"], fake, "http://x", "t")
    assert body_r01 == seen[0], "권고는 측정기가 지을 본문 그대로"
    golden = {cid: f.call(items[cid], fake, "http://x", "t")[0] for cid in ("G1", "S1", "Q1")}
    assert golden["G1"]["exclude_doc_types"] == ["spec", "design_doc"] == golden["S1"]["exclude_doc_types"]
    assert "exclude_doc_types" not in golden["Q1"], "질의 줄은 안 뺀다"
    assert all(b["identifier_channel"] is True and b["top_k"] == 20 and b["tenant"] == "picasso" for b in golden.values())
    assert "answer_context" not in golden["G1"] and body_r01["answer_context"] == items["R01"]["context"]


def test_measure_py_의_실험군과_클라이언트_줄을_글자로_박는다():
    """실행기는 `eval/measure.py` 를 가져오지 않는다(가져오면 실제 서비스 실행을 한다). 골든셋 본문의 근거인 줄을 글자로 박는다 — 이 줄이
    바뀌면 실행기의 골든셋 본문도 함께 고친다."""
    text = (f.ROOT / "eval" / "measure.py").read_text(encoding="utf-8")
    assert "ARM = (sys.argv[1] if len(sys.argv) > 1 else 'T2').upper()" in text
    assert "IDENTIFIERS = ARM == 'T2'" in text
    assert ("def _client(exclude):\n    return nexus_client('http://localhost:8000', token=TOKEN,\n"
            "                        tenant='picasso', transport=http_transport,\n"
            "                        exclude_doc_types=exclude, identifier_channel=IDENTIFIERS)\n") in text
    assert "CLIENTS = {INCIDENT: _client(INCIDENT_EXCLUDED), SEARCH: _client(INCIDENT_EXCLUDED),\n           QUERY: _client(())}" in text


def test_같은_검색은_자료_칸과_case_를_빼고_무리_짓는다():
    """근거만 받는 요청에서 답변 컨텍스트는 검색에 안 쓰이고 picasso 에는 `case` 종류가 없다(설계서 §2). 이 커밋의 무리는 셋이다."""
    a = {"query": "q", "tenant": "picasso", "top_k": 20, "exclude_doc_types": ["spec", "design_doc", "case"],
         "identifier_channel": True, "answer_context": "자료"}
    b = {"query": "q", "tenant": "picasso", "top_k": 20, "exclude_doc_types": ["spec", "design_doc"], "identifier_channel": True}
    assert f.search_key(a) == f.search_key(b)
    assert f.search_key(dict(b, query="r")) != f.search_key(b)
    assert f.search_key({k: v for k, v in b.items() if k != "exclude_doc_types"}) != f.search_key(b), "안 뺀 질의는 다른 검색"
    groups = {}
    for item in f.items():
        body, _, _ = f.call(item, lambda method, url, headers, body: (200, {}), "http://x", "t")
        groups.setdefault(f.search_key(body), []).append(item)
    merged = sorted(sorted(i["id"] for i in group) for group in groups.values() if len(group) > 1)
    assert merged == [["R04", "R10"], ["R06", "S1"], ["R14", "R15", "R16"]]
    assert len(groups) == 32 and sum(1 for group in groups.values() if any(i["expected"] for i in group)) == 27


def test_판의_성립은_응답_하나라도_어긋나면_무효다():
    """khala 요청 문서 36 의 무효 조건과 설계서 §3 — 메아리는 그 실행의 실험군 값과, 안 보낸 빼는 종류는 `[]` 와 견준다."""
    good = row("R01", [SOP01], ranked(SOP01))
    assert f.validity(record("t0-1", "T0", [good], "1"), VERSIONS) == []
    for name, extra in {"evidence_only": dict(evidence_only=False), "fusion_doc_agreement": dict(fusion_doc_agreement=True),
                        "degraded": dict(degraded=["vector"]), "enrichment_failed": dict(enrichment_failed=["section_fill"]),
                        "answer_context_len": dict(answer_context_len=12),
                        "searched_tenants": dict(searched_tenants=["picasso", "narrator"]),
                        "excluded_doc_types": dict(excluded_doc_types=["spec"]),
                        "identifier_channel_asked": dict(identifier_channel_asked=False),
                        "versions": dict(corpus_version="다른 판")}.items():
        bad = row("R01", [SOP01], ranked(SOP01), **extra)
        assert f.validity(record("t0-1", "T0", [bad], "1"), VERSIONS) == [f"R01: {name}"], name
    gap = ranked(SOP01)
    gap[5]["rank"] = 7
    assert f.validity(record("t0-1", "T0", [row("R01", [SOP01], gap)], "1"), VERSIONS) == ["R01: rank"], "순위에 빈틈"
    keyless = [{k: v for k, v in s.items() if k != "rank"} for s in ranked(SOP01)]
    assert f.validity(record("t0-1", "T0", [row("R01", [SOP01], keyless)], "1"), VERSIONS) == ["R01: rank"], "rank 키 없음"
    query = row("Q1", [], ranked(GUIDE), set_="golden", exclude=())
    assert query["sentExclude"] == [] and f.validity(record("t0-1", "T0", [query], "1"), VERSIONS) == []
    none_echo = row("Q1", [], ranked(GUIDE), set_="golden", exclude=(), excluded_doc_types=None)
    assert f.validity(record("t0-1", "T0", [none_echo], "1"), VERSIONS) == ["Q1: excluded_doc_types"], "None 은 [] 가 아니다"
    assert f.validity(record("f1-1", "F1", [row("R01", [SOP01], ranked(SOP01), arm="F1")], "1"), VERSIONS) == []
    assert f.validity(record("f1-1", "F1", [good], "1"), VERSIONS) == ["R01: fusion_doc_agreement"], "F1 판에 거짓 메아리"
    assert f.validity(record("t0-1", "T0", [row("R01", [SOP01], [], status=599)], "1"), VERSIONS) == ["R01: 상태 599"]
    assert f.validity(record("t0-1", "T0", [good], "1"), ("p", "", "s")) == ["R01: versions"], "빈 판 칸은 모름이다"


def test_판_칸의_기준은_가장_많은_벌이고_판마다_항목과_본문이_같아야_한다():
    """첫 응답 하나가 튀어도 모든 실행이 무효가 되지 않게 기준은 가장 많은 벌이다. 실행 이름이 겹치거나 실행마다 본문이 다르면 견주지
    않는다."""
    t0 = [row("R01", [SOP01], ranked(SOP01), key="a")]
    f1 = [row("R01", [SOP01], ranked(GUIDE, SOP01), key="a", arm="F1")]
    odd = [row("R01", [SOP01], ranked(SOP01), key="a", corpus_version="튄 판")]
    out = f.tally([record("t0-0", "T0", odd, "0"), record("t0-1", "T0", t0, "1"), record("f1-1", "F1", f1, "2"),
                   record("t0-2", "T0", t0, "3")])
    assert out["versions"] == list(VERSIONS) and [p["valid"] for p in out["passes"]] == [False, True, True, True]
    assert "headline" in out
    other = [row("R01", [SOP01], ranked(GUIDE, SOP01), key="b", arm="F1")]
    assert "본문" in f.tally([record("t0-1", "T0", t0, "1"), record("f1-1", "F1", other, "2")])["comparable"]
    assert "본문" in f.tally([record("t0-1", "T0", t0, "1"), record("f1-1", "F1", f1, "2", commit="c1")])["comparable"]
    assert "같은 이름" in f.tally([record("t0-1", "T0", t0, "1"), record("t0-1", "T0", t0, "2")])["comparable"]


def test_머리_수치는_검색마다_하나라도이고_불일치와_부호_검정():
    """기대 문서가 둘이면 「하나라도」는 한 문서의 빠짐을 못 본다(R01 처럼) — 그래서 쌍을 곁에 둔다. 불일치 6 미만이면 p 를 안 낸다."""
    t0 = [row("R01", [SOP01, SOP03], ranked(SOP03), key="a"),
          row("R03", [SOP03], ranked(GUIDE), key="b"),
          row("Q1", [], ranked(GUIDE), key="c", set_="golden", exclude=())]
    f1 = [row("R01", [SOP01, SOP03], ranked(SOP01, SOP03), key="a", arm="F1"),
          row("R03", [SOP03], ranked(SOP03), key="b", arm="F1"),
          row("Q1", [], ranked(SOP01), key="c", set_="golden", exclude=(), arm="F1")]
    out = f.tally([record("t0-1", "T0", t0, "1"), record("f1-1", "F1", f1, "2")])
    head = out["headline"]
    assert out["comparable"] is None and head["n"] == 2
    assert head["T0"][:2] == (1, 2) and head["F1"][:2] == (2, 2)
    assert head["onlyF1"] == [["R03"]] and head["onlyT0"] == [] and head["p"] is None
    described = out["described"]
    assert described["pairs"]["T0"] == (1, 3) and described["pairs"]["F1"] == (3, 3)
    assert [(s["ids"], s["doc"]) for s in described["pairs"]["split"]] == [(["R01"], SOP01), (["R03"], SOP03)]
    assert described["allIn"] == {"T0": 0, "F1": 2} and described["sets"]["golden"]["T0"] == (0, 0)
    assert out["secondary"]["F1"]["passes"][0]["wrong"] == {"labeled": 0, "unlabeled": 1}, "기대 없는 검색은 따로 센다"
    assert f.sign_test(6, 0) == pytest.approx(0.03125) and f.sign_test(3, 3) == 1.0


def test_머리_수치는_순위_조각만_세고_불일치_6_부터_p_를_낸다():
    """채움(`rank` null)에만 있는 기대 문서는 상위 20 에 안 든 것이다 — 묶음 쪽 셈에만 든다."""
    filled = ranked(GUIDE) + [snip(SOP01, None, rid="fill-1")]
    t0 = [row("R01", [SOP01], filled, key="a")]
    f1 = [row("R01", [SOP01], ranked(SOP01), key="a", arm="F1")]
    out = f.tally([record("t0-1", "T0", t0, "1"), record("f1-1", "F1", f1, "2")])
    assert out["headline"]["T0"][0] == 0 and out["described"]["bundle"]["T0"] == 1
    for count, p in ((6, pytest.approx(0.03125)), (5, None)):
        t0 = [row(f"R{i}", [SOP01], ranked(GUIDE), key=f"k{i}") for i in range(count)]
        f1 = [row(f"R{i}", [SOP01], ranked(SOP01), key=f"k{i}", arm="F1") for i in range(count)]
        head = f.tally([record("t0-1", "T0", t0, "1"), record("f1-1", "F1", f1, "2")])["headline"]
        assert len(head["onlyF1"]) == count and head["p"] == p


def test_양성_대조와_결정론과_불변_칸():
    """처치가 걸렸나는 메아리로 못 안다 — F1 의 상위 20 이 T0 와 다른 검색이 없으면 비교하지 않는다. 같은 실험군 실행끼리와 실행 안의
    같은 무리끼리 상위 20 이 같아야 하고, F1 이 안 건드리는 칸은 모든 실행에서 같아야 한다."""
    same = [row("R01", [SOP01], ranked(SOP01), key="a")]
    out = f.tally([record("t0-1", "T0", same, "1"), record("f1-1", "F1", [row("R01", [SOP01], ranked(SOP01), key="a",
                                                                                arm="F1")], "2")])
    assert out["comparable"].startswith("양성 대조") and "headline" not in out
    moved = [row("R01", [SOP01], ranked(GUIDE, SOP01), key="a", arm="F1")]
    drifted = [row("R01", [SOP01], ranked(SOP03), key="a")]
    out = f.tally([record("t0-1", "T0", same, "1"), record("f1-1", "F1", moved, "2"), record("t0-2", "T0", drifted, "3")])
    assert out["comparable"] == "결정론이 깨졌다" and out["drift"] == [{"pass": "t0-2", "ids": ["R01"]}]
    shifted = [row("R01", [SOP01], ranked(GUIDE, SOP01), key="a", arm="F1", top_distance=0.9)]
    out = f.tally([record("t0-1", "T0", same, "1"), record("f1-1", "F1", shifted, "2")])
    assert out["invariant"] == [["R01"]] and out["comparable"] == "불변 칸이 갈렸다"
    twins = [row("R04", [SOP03], ranked(SOP03), key="d"), row("R10", [SOP03], ranked(GUIDE), key="d")]
    twins_f1 = [row("R04", [SOP03], ranked(GUIDE, SOP03), key="d", arm="F1"),
                row("R10", [SOP03], ranked(GUIDE, SOP03), key="d", arm="F1")]
    out = f.tally([record("t0-1", "T0", twins, "1"), record("f1-1", "F1", twins_f1, "2")])
    assert out["drift"] == [{"pass": "t0-1", "ids": ["R04", "R10"]}], "판 안의 같은 무리가 다르다"
    rescored = [row("R01", [SOP01], [dict(s, score=0.9) for s in ranked(SOP01)], key="a", arm="F1")]
    out = f.tally([record("t0-1", "T0", same, "1"), record("f1-1", "F1", rescored, "2")])
    assert out["moved"] == [["R01"]] and out["movedOrder"] == [], "점수만 바뀐 것은 차례가 안 갈린 것이다"


def test_부_변수는_판마다_세고_지연은_T0_판들의_평균과_견준다():
    """한 문서 쏠림은 상위 20 · 순위 10 이하 · 상한 채운 문서 수 · 묶음 전체로 넷, 틀린 절차는 기대가 아닌 절차 문서의 수, 지연의
    잡음 폭은 같은 실험군 실행 사이의 흩어짐이다."""
    snippets = ranked(*([SOP01] * 5 + [SOP03] * 5)) + [snip(GUIDE, None, rid="fill-1"), snip(GUIDE, None, rid="fill-2")]
    conc = f.concentration(row("R01", [SOP01], snippets))
    assert conc == {"top20": pytest.approx(0.5), "top10": pytest.approx(0.5), "capped": 3, "bundle": pytest.approx(12 / 22)}
    assert f.wrong(row("R01", [SOP01], snippets), [SOP01]) == 1, "기대가 아닌 SOP-03"
    t0a = [row("R01", [SOP01], snippets, key="a", timing_ms={"total_ms": 100})]
    t0b = [row("R01", [SOP01], snippets, key="a", timing_ms={"total_ms": 130})]
    f1 = [row("R01", [SOP01], ranked(SOP01), key="a", arm="F1", timing_ms={"total_ms": 90})]
    out = f.tally([record("t0-1", "T0", t0a, "1"), record("f1-1", "F1", f1, "2"), record("t0-2", "T0", t0b, "3")])
    s = out["secondary"]["T0"]
    assert [p["pass"] for p in s["passes"]] == ["t0-1", "t0-2"]
    assert s["passes"][0]["ranked"] == 20 and s["passes"][0]["fills"] == 2 and s["passes"][0]["chars"] == 22 * 300
    assert s["latency"] == {"median": 115.0, "range": [100, 130], "spread": 30, "passes": 2}
    assert out["secondary"]["F1"]["latency"]["spread"] is None, "판 하나면 흩어짐이 없다"
    assert out["secondary"]["F1"]["latency"]["vsT0Mean"] == -25


def test_판_하나는_예열_뒤_측정기_본문에_칸을_더해_보내고_멈춤이면_안_쓴다(monkeypatch):
    """`run_pass` — 첫 부름은 기록하지 않는 웜업이고, 그 뒤 항목마다 측정기 본문에 두 칸을 더해 보낸다. 줄의 본문 해시는 더하기
    전의 것이다. 401 · 403 · 422 면 곧바로 멈추고 기록을 안 쓴다."""
    written = []
    monkeypatch.setattr(f, "write", lambda path, env, rows: written.append((env, rows)))
    monkeypatch.delenv("KHALA_ROOT", raising=False)
    calls = []

    def fake(method, url, headers, body):
        calls.append((url, body))
        return 200, {"success": True, "data": data(ranked(SOP01), arm="F1")}

    f.run_pass("f1-1", "F1", "unused.json", "t", "http://x", transport=fake, clock=lambda: "now")
    assert calls[0] == ("http://x/search", f.WARM)
    sent = [body for _, body in calls[1:]]
    assert len(sent) == 36 and all(b["evidence_only"] is True and b["fusion_doc_agreement"] is True for b in sent)
    env, rows = written[0]
    assert env["arm"] == "F1" and env["flags"] == {"evidence_only": True, "fusion_doc_agreement": True}
    assert env["endedAt"] == "now" and env["khalaBefore"] is None and len(rows) == 36
    assert all(r["bodySha256"] == f.sha({k: v for k, v in b.items() if k not in ("evidence_only", "fusion_doc_agreement")})
               for r, b in zip(rows, sent))
    written.clear()
    calls.clear()
    f.run_pass("t0-1", "T0", "unused.json", "t", "http://x", transport=fake, clock=lambda: "now")
    assert all("fusion_doc_agreement" not in body for _, body in calls[1:]), "T0 는 F1 키를 안 보낸다"
    written.clear()

    def refused(method, url, headers, body):
        return (200, {}) if url.endswith("/search") else (422, {"detail": "extra_forbidden"})

    with pytest.raises(SystemExit, match="422"):
        f.run_pass("f1-1", "F1", "unused.json", "t", "http://x", transport=refused, clock=lambda: "now")
    assert written == [], "멈춘 판은 기록을 안 쓴다"


def test_다시_해도_같은_상태면_곧바로_멈추고_깨진_응답은_판의_실패다():
    assert f.stop_reason("R01", 422, {"detail": "extra_forbidden"}).startswith("멈춘다 — R01 에 422")
    assert f.stop_reason("R01", 401, {}) and f.stop_reason("R01", 403, {})
    assert f.stop_reason("R01", 599, {"detail": "timeout"}) is None and f.stop_reason("R01", 200, {}) is None

    def broken(method, url, headers, body):
        raise ValueError("Expecting value")

    g1 = next(i for i in f.items() if i["id"] == "G1")
    body, status, response = f.call(g1, broken, "http://x", "t")
    assert status == "broken" and "ValueError" in response["detail"] and body["query"] == g1["query"]
    failed = f.row_of(g1, body, "broken", response)
    assert failed["data"] is None and "ValueError" in failed["error"]
