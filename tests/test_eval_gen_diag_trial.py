"""생성 평가 — 진단 경로 파이프라인 실행. 설계서 `docs/superpowers/specs/2026-10-02-생성-판-진단-경로.md`. 가짜 응답으로 돈다."""

import copy
import json

import pytest

from eval import ask_trial as at
from eval import fusion_trial as ft
from eval import gen_diag_trial as d
from eval import query_trial as qt
from eval import recommend as rec
from eval.recommend_score import load_cases

GLOSSARY = "picasso — 표준 용어 사전 (Glossary)"
CARD = "절차: a\n먼저: b\n금지: c\n갈림: d\n근거 세기: e"


def answer_data(pick="ESCALATE", doc=GLOSSARY, verified=True, evidence=None, degraded=(), failed=None, corpus="c"):
    """`/search/answer` 의 `data` 한 벌 — 라벨 하나, 인용 하나(이유 문장에 붙음), 버전 필드, 검색 부분 실패 칸."""
    answer = f"권고: {pick}\n이유: 사람이 먼저 본다 [출처: {doc}, §5.1].\n{CARD}"
    return {"answer": "" if failed else answer,
            "citations": [] if failed else [{"title": doc, "section": "§5.1", "verified": verified}],
            "abstained": False, "weak_evidence": False, "llm_failed": bool(failed), "llm_failure_reason": failed,
            "unverified_citations": 0, "unverified_numbers": 0, "numbers": [], "usage": {"model": "m"}, "timing_ms": {},
            "evidence_snippets": [{"doc_title": t, "rank": i + 1, "chunk_rid": f"c{i}"}
                                  for i, t in enumerate(evidence if evidence is not None else [doc])],
            "prompt_version": "p", "corpus_version": corpus, "search_fingerprint": "s",
            "degraded": list(degraded), "enrichment_failed": [], "route_used": "hybrid_only"}


def procedure(case):
    return case["procedureDocs"][0] if case["procedureDocs"] else GLOSSARY


def fake_khala(calls, work, answer=None, budget=rec.MAX_ATTEMPTS, only=None):
    """부르는 차례대로 (사례, 실험군)을 짚어 답한다 — 계획의 차례가 곧 부르는 차례다. 다시 할 만한 실패면 시도 예산까지 같은 줄에
    머문다(`run_case` 의 재시도). `answer` 는 (사례, 실험군, 본문, 그 줄의 몇째 시도)를 받는다."""
    wanted = d.targets(only) if only is not None else None
    seq = [(item["prep"]["case"], arm) for item in work for arm in item["order"]
           if wanted is None or arm in wanted[item["prep"]["case"]["id"]]]
    state = {"pos": 0, "tries": 0}

    def transport(method, url, headers, body):
        calls.append((url, copy.deepcopy(body)))
        if url.endswith("/search"):
            return 200, {"success": True, "data": {}}
        case, arm = seq[state["pos"] % len(seq)]
        state["tries"] += 1
        data = (answer or (lambda case, arm, body, n: answer_data(doc=procedure(case))))(case, arm, body, state["tries"])
        if data.get("llm_failure_reason") not in ("timeout", "unavailable", "rate_limit") or state["tries"] >= budget:
            state["pos"], state["tries"] = state["pos"] + 1, 0
        data["answer_context_len"] = len(body.get("answer_context") or "")
        data["excluded_doc_types"] = body.get("exclude_doc_types")
        data["searched_tenants"] = [body["tenant"]]
        return 200, {"success": True, "data": data}

    return transport


def run(tmp_path, monkeypatch, answer=None, only=None, name="d-1", at_="2026-10-02T01:00:00+00:00"):
    """가짜 khala 로 파이프라인 실행 — `(기록, 부른 것)`."""
    monkeypatch.delenv("KHALA_ROOT", raising=False)
    wanted = d.targets(only) if only is not None else None
    work = [item for item in d.plan() if wanted is None or item["prep"]["case"]["id"] in wanted]
    calls, out = [], tmp_path / f"{name}.json"
    transport = fake_khala(calls, work, answer, budget=1 if only is not None else rec.MAX_ATTEMPTS, only=only)
    d.run_round(name, out, "t", "http://x", transport=transport, clock=lambda: at_, only=only, commit="abc1234")
    return json.loads(out.read_text(encoding="utf-8")), calls


def test_계획은_D0_가_운영_글이고_D3_은_Q3_에_Q0_와_후보_자료다():
    """D0 는 권고 측정기의 질의와 답변 컨텍스트 그대로, D3 은 질문 제거의 Q3 에 답변 컨텍스트 = Q0 + 빈 줄 + 후보 자료. 반복 R02 는 뺀다. 홀수째
    사례는 D0 먼저, 짝수째는 D3 먼저(설계서 §1). 답변 컨텍스트는 khala 상한 8,000 안이다."""
    doc = load_cases()
    work = d.plan()
    prepared = [p for p in rec.prepare(doc) if not p["case"]["repeatOf"]]
    built = qt.queries(doc)
    assert [item["prep"]["case"]["id"] for item in work] == [p["case"]["id"] for p in prepared] and len(work) == 21
    assert "R02" not in {item["prep"]["case"]["id"] for item in work}
    for i, (item, prep) in enumerate(zip(work, prepared)):
        cid = prep["case"]["id"]
        assert item["order"] == (("D0", "D3") if i % 2 == 0 else ("D3", "D0"))
        assert item["D0"] == {"query": prep["query"], "context": prep["context"]}
        assert item["D3"]["query"] == at.texts(built[cid])["Q3"] != prep["query"], cid
        assert item["D3"]["context"] == prep["query"] + "\n\n" + prep["context"], cid
        assert len(item["D3"]["context"]) <= 8000


def test_한_바퀴는_D0_가_권고_측정기와_같은_본문이고_D3_은_글만_바꾼다(tmp_path, monkeypatch):
    """D0 의 본문은 권고 측정기(`eval.recommend.client_for`)가 보낼 본문과 바이트까지 같고, D3 은 질의와 답변 컨텍스트만 다르다. 진단 함수가
    지은 글(받은 것)은 두 실험군 다 운영 글이다. 기록은 실행 끝에서만 `complete` 가 참이다."""
    record, calls = run(tmp_path, monkeypatch)
    work = d.plan()
    assert calls[0] == ("http://x/search", ft.WARM)
    sent = calls[1:]
    assert len(sent) == 42 and record["complete"] is True and len(record["rows"]) == 42
    for i, item in enumerate(work):
        prep = item["prep"]
        golden = []
        rec.client_for("http://x", "t", transport=lambda m, u, h, b: golden.append(b) or (200, {}))(prep["context"])(prep["query"])
        for j, arm in enumerate(item["order"]):
            url, body = sent[2 * i + j]
            assert url == "http://x/search/answer"
            if arm == "D0":
                assert body == golden[0], prep["case"]["id"]
            else:
                assert {k: v for k, v in body.items() if k not in ("query", "answer_context")} == \
                       {k: v for k, v in golden[0].items() if k not in ("query", "answer_context")}
                assert body["query"] == item["D3"]["query"] and body["answer_context"] == item["D3"]["context"]
    rows = {(r["id"], r["arm"]): r for r in record["rows"]}
    for item in work:
        cid = item["prep"]["case"]["id"]
        for arm in d.ARMS:
            r = rows[(cid, arm)]
            assert r["receivedQuerySha256"] == [r["querySha256"]] and r["receivedContextSha256"] == [r["contextSha256"]]
            assert r["sentQuerySha256"] == r["planQuerySha256"] and r["sentContextSha256"] == r["planContextSha256"]
            assert r["sentQuery"] == item[arm]["query"] and r["sentContext"] == item[arm]["context"]
            assert r["echo"]["answer_context_len"] == len(item[arm]["context"]) and r["sends"] == 1
            assert r["response"]["outcome"] == "RECOMMENDED" and r["resolved"] == "ESCALATE"
    assert record["env"]["arms"] == ["D0", "D3"] and record["env"]["only"] is None
    again, calls = run(tmp_path, monkeypatch, only={"R04", "R03"}, name="d-1r")
    assert [r["id"] for r in again["rows"]] == ["R03", "R03", "R04", "R04"] and again["env"]["only"] == ["R03", "R04"]
    assert [r["arm"] for r in again["rows"]] == ["D3", "D0", "D0", "D3"], "다시 불러도 차례는 사례 파일 차례의 규칙 그대로"
    assert all(r["attempts"][-1].get("rerun") is True for r in again["rows"]), "판 끝 다시 부르기는 rerun 표시"
    line, _ = run(tmp_path, monkeypatch, only={"R04:D3"}, name="d-1l")
    assert [(r["id"], r["arm"]) for r in line["rows"]] == [("R04", "D3")], "고장 난 줄만 다시 부른다(검토 M1)"

    def flaky(case, arm, body, n):
        failed = "timeout" if (case["id"], arm, n) == ("R05", "D0", 1) else None
        return answer_data(doc=procedure(case), failed=failed)

    record, _ = run(tmp_path, monkeypatch, answer=flaky, name="d-1f")
    r05 = next(r for r in record["rows"] if (r["id"], r["arm"]) == ("R05", "D0"))
    assert r05["sends"] == 2 and [a["reason"] for a in r05["attempts"]] == ["timeout", None]
    assert len(r05["receivedQuerySha256"]) == 1 and d.tally([record])["comparable"] is None, "같은 글을 두 번 보내도 처치는 선다"


def test_멈춤은_422_와_한도와_잇단_실패에서_곧바로이고_기록은_끝나지_않은_채_남는다(tmp_path, monkeypatch):
    def at_422(case, arm, body, n):
        return answer_data()

    monkeypatch.delenv("KHALA_ROOT", raising=False)
    work = d.plan()
    calls = []
    base = fake_khala(calls, work, at_422)

    def transport(method, url, headers, body):
        if url.endswith("/search/answer") and sum(1 for u, _ in calls if u.endswith("/answer")) == 3:
            calls.append((url, body))
            return 422, {"detail": "모르는 칸"}
        return base(method, url, headers, body)

    out = tmp_path / "stop.json"
    with pytest.raises(SystemExit) as stop:
        d.run_round("d-1", out, "t", "http://x", transport=transport, clock=lambda: "now", commit="abc1234")
    assert "422" in str(stop.value)
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["complete"] is False and len(saved["rows"]) == 3, "앞의 답은 남고 판은 안 끝났다"

    for reason, expect_rows in (("quota", 1), ("timeout", 2)):
        calls = []
        out = tmp_path / f"stop-{reason}.json"
        failing = fake_khala(calls, work, lambda case, arm, body, n: answer_data(failed=reason))
        with pytest.raises(SystemExit) as stop:
            d.run_round("d-1", out, "t", "http://x", transport=failing, clock=lambda: "now", commit="abc1234")
        saved = json.loads(out.read_text(encoding="utf-8"))
        assert saved["complete"] is False and len(saved["rows"]) == expect_rows, reason
        assert all(r["failed"] == reason for r in saved["rows"])
        if reason == "timeout":
            assert [len(r["attempts"]) for r in saved["rows"]] == [2, 2], "다시 할 만한 사유는 시도 한도 2 까지"
    again, _ = run(tmp_path, monkeypatch, answer=lambda case, arm, body, n: answer_data(failed="timeout"),
                   only={"R03", "R04"}, name="d-1r")
    assert again["complete"] is True and len(again["rows"]) == 4, "다시 부르는 판은 잇단 실패로 안 멈춘다(검토 M2)"
    assert all(len(r["attempts"]) == 1 and r["failed"] == "timeout" for r in again["rows"]), "줄마다 한 번"
    asked = []
    with pytest.raises(SystemExit) as stop:
        d.run_round("d-1", tmp_path / "warm.json", "t", "http://x", clock=lambda: "now", commit="abc1234",
                    transport=lambda m, u, h, b: asked.append(u) or (502, {"detail": "프록시"}))
    assert "예열" in str(stop.value) and asked == ["http://x/search"], "예열이 200 이 아니면 진단을 하나도 안 부른다"


def test_셈은_가드_열과_주_변수로_넘김을_정한다(tmp_path, monkeypatch):
    record, _ = run(tmp_path, monkeypatch)
    out = d.tally([record])
    assert out["comparable"] is None and out["advance"] is True and all(out["guards"].values())
    assert out["arms"]["D0"]["procedureCited"] == out["arms"]["D3"]["procedureCited"] == (20, 20)
    assert out["arms"]["D0"]["M2"] == (0, 21) and out["arms"]["D3"]["clean"] == (21, 21)
    assert out["arms"]["D0"]["decorated"] == out["arms"]["D3"]["decorated"] == 0, "꾸밈 없는 줄(plain)은 꾸밈이 아니다"

    def forbidden(case, arm, body, n):
        if arm == "D3" and case["id"] == "R01":
            return answer_data(pick="A", doc=procedure(case))
        return answer_data(doc=procedure(case))

    record, _ = run(tmp_path, monkeypatch, answer=forbidden, name="d-2")
    out = d.tally([record])
    assert out["arms"]["D3"]["forbidden"] == (1, 11) and out["guards"]["forbidden"] is False and out["advance"] is False
    assert out["comparable"] is None, "가드가 깨진 것은 판이 안 선 것이 아니다"

    def outside(case, arm, body, n):
        return answer_data(pick="Z" if arm == "D3" and case["id"] == "R06" else "ESCALATE", doc=procedure(case))

    record, _ = run(tmp_path, monkeypatch, answer=outside, name="d-3")
    out = d.tally([record])
    assert out["arms"]["D3"]["M2"] == (1, 21) and out["guards"]["M2"] is False and out["advance"] is False

    def fewer(case, arm, body, n):
        if arm == "D3" and case["id"] == "R04":
            return answer_data(doc=GLOSSARY, evidence=[GLOSSARY])
        return answer_data(doc=procedure(case))

    record, _ = run(tmp_path, monkeypatch, answer=fewer, name="d-4")
    out = d.tally([record])
    assert out["arms"]["D3"]["procedureCited"] == (19, 20) and all(out["guards"].values()), "가드는 다 서고 주 변수만 진다"
    assert out["primary"] is False and out["advance"] is False


def test_둘_다_받은_사례의_인용이_검색이_더_준_몫을_뺀다(tmp_path, monkeypatch):
    """D3 의 검색이 D0 가 못 받은 절차를 셋 더 받아 1차 결과 변수에서 앞서도, 둘 다 받은 사례에서 둘을 덜 인용하면 승격하지 않는다."""
    gained = ("R04", "R05", "R06")
    dropped = ("R09", "R10")

    def answer(case, arm, body, n):
        doc = procedure(case)
        if not case["procedureDocs"]:
            return answer_data(doc=GLOSSARY)
        if arm == "D0" and case["id"] in gained:
            return answer_data(doc=GLOSSARY, evidence=[GLOSSARY])
        if arm == "D3" and case["id"] in dropped:
            return answer_data(doc=GLOSSARY, evidence=[doc, GLOSSARY])
        return answer_data(doc=doc)

    record, _ = run(tmp_path, monkeypatch, answer=answer)
    out = d.tally([record])
    d0, d3 = out["arms"]["D0"], out["arms"]["D3"]
    assert d0["procedureCited"] == (17, 20) and d3["procedureCited"] == (18, 20) and out["primary"] is True
    assert d0["citedWhenBoth"] == (17, 17) and d3["citedWhenBoth"] == (15, 17)
    assert out["guards"]["citedWhenBoth"] is False and out["advance"] is False
    assert len(out["bothRetrieved"]) == 17


def test_성립은_끝남_판_칸_고장_다시_부름_처치_신원을_본다(tmp_path, monkeypatch):
    record, _ = run(tmp_path, monkeypatch)
    assert d.tally([record])["comparable"] is None

    unfinished = copy.deepcopy(record)
    unfinished["complete"] = False
    assert d.tally([unfinished])["comparable"] == "끝나지 않은 기록이 있다"

    missing = copy.deepcopy(record)
    missing["rows"] = missing["rows"][:-1]
    assert d.tally([missing])["comparable"] == "빠진 줄이 있다"

    split = copy.deepcopy(record)
    split["rows"][5]["response"]["versions"]["corpusVersion"] = "other"
    assert d.tally([split])["comparable"] == "판 칸이 한 벌이 아니다"

    def broken(case, arm, body, n):
        return answer_data(doc=procedure(case), degraded=["vector"] if case["id"] == "R07" else ())

    def one_arm(case, arm, body, n):
        return answer_data(doc=procedure(case), degraded=["vector"] if (case["id"], arm) == ("R07", "D3") else ())

    lone, _ = run(tmp_path, monkeypatch, answer=one_arm, name="o-1")
    assert d.tally([lone])["broken"] == ["R07 D3"]
    fix, _ = run(tmp_path, monkeypatch, only={"R07:D3"}, name="o-1r", at_="2026-10-02T03:00:00+00:00")
    assert d.tally([lone, fix])["comparable"] is None, "고장 난 줄만 다시 부르면 선다"
    whole, _ = run(tmp_path, monkeypatch, only={"R07"}, name="o-1w", at_="2026-10-02T03:00:00+00:00")
    assert d.tally([lone, whole])["badReruns"] == ["R07 D0"], "멀쩡한 줄을 다시 부르면 안 선다"

    first, _ = run(tmp_path, monkeypatch, answer=broken, name="b-1")
    out = d.tally([first])
    assert out["comparable"] == "검색 고장이 남았다" and out["broken"] == ["R07 D0", "R07 D3"]
    rerun, _ = run(tmp_path, monkeypatch, only={"R07"}, name="b-1r", at_="2026-10-02T03:00:00+00:00")
    assert d.tally([rerun, first])["comparable"] is None, "시각 차례로 합치고 다시 부른 줄이 고장을 덮는다"
    twice = copy.deepcopy(rerun)
    twice["env"]["at"] = "2026-10-02T04:00:00+00:00"
    assert d.tally([first, rerun, twice])["comparable"] == "다시 부른 줄이 고장 · 실패가 아니었거나 두 번이다"
    assert d.tally([record, rerun])["comparable"] == "다시 부른 줄이 고장 · 실패가 아니었거나 두 번이다"

    for field, value in (("receivedQuerySha256", ["x"]), ("sentContextSha256", "x"), ("sentContext", "다른 글")):
        bent = copy.deepcopy(record)
        row = next(r for r in bent["rows"] if r["arm"] == "D3" and r["id"] == "R11")
        row[field] = value
        assert d.tally([bent])["comparable"] == "처치가 계획과 다르다", field
    shape = copy.deepcopy(record)
    row = next(r for r in shape["rows"] if r["arm"] == "D3" and r["id"] == "R11")
    other = "다른 자료 칸"
    row.update(sentContext=other, sentContextSha256=d.sha(other), planContextSha256=d.sha(other), sentContextLen=len(other))
    row["echo"]["answer_context_len"] = len(other)
    assert d.tally([shape])["treatment"] == ["R11: D3 의 자료 칸이 Q0 와 후보 자료가 아니다"], "해시가 맞아도 모양을 본다"
    echo = copy.deepcopy(record)
    echo["rows"][0]["echo"]["answer_context_len"] = 1
    assert d.tally([echo])["comparable"] == "처치가 계획과 다르다"

    def stuck(case, arm, body, n):
        return answer_data(doc=procedure(case), failed="timeout" if (case["id"], arm) == ("R04", "D0") else None)

    failing, _ = run(tmp_path, monkeypatch, answer=stuck, name="f-1")
    assert d.tally([failing])["comparable"] == "다시 부를 실패가 남았다"
    still, _ = run(tmp_path, monkeypatch, answer=stuck, only={"R04:D0"}, name="f-1r", at_="2026-10-02T03:00:00+00:00")
    out = d.tally([failing, still])
    assert out["comparable"] is None and out["failedAfterRerun"] == ["R04 D0"] and out["unpaired"] == ["R04"]
    assert out["arms"]["D0"]["failed"] == 1 and out["arms"]["D3"]["failed"] == 0 and out["guards"]["failed"] is True
    assert out["arms"]["D0"]["procedureCited"] == out["arms"]["D3"]["procedureCited"] == (19, 19), "짝으로 센다(검토 S3)"
    lost = copy.deepcopy(failing)
    row = next(r for r in lost["rows"] if (r["id"], r["arm"]) == ("R04", "D0"))
    row["echo"] = None
    assert not [t for t in d.tally([lost])["treatment"] if "R04" in t], "실패한 줄은 되울림이 없어도 된다"

    assert d.tally([record, copy.deepcopy(record)])["comparable"] == "전체 판 기록이 하나가 아니다"
    unknown = copy.deepcopy(record)
    for r in unknown["rows"]:
        r["response"]["versions"]["corpusVersion"] = None
    assert d.tally([unknown])["comparable"] == "모르는 판 칸이 있다"
    moved = dict(rerun, env=dict(rerun["env"], narratorCommit="other"))
    assert d.tally([first, moved])["comparable"] == "narrator 커밋이 기록마다 다르다"

    for name, bend in (
            ("빼는 종류", lambda r: r["echo"].update(excluded_doc_types=["spec"])),
            ("테넌트", lambda r: r["echo"].update(searched_tenants=["other"])),
            ("보낸 칸", lambda r: r.update(sentKeys=r["sentKeys"][:-1])),
    ):
        bent = copy.deepcopy(record)
        bend(next(r for r in bent["rows"] if r["arm"] == "D3" and r["id"] == "R13"))
        problems = d.tally([bent])["treatment"]
        assert problems and all(p.startswith("R13") for p in problems), name
    same = copy.deepcopy(record)
    d0 = next(r for r in same["rows"] if r["arm"] == "D0" and r["id"] == "R13")
    d3 = next(r for r in same["rows"] if r["arm"] == "D3" and r["id"] == "R13")
    d3.update(sentQuery=d0["sentQuery"], sentQuerySha256=d0["sentQuerySha256"], planQuerySha256=d0["sentQuerySha256"])
    assert d.tally([same])["treatment"] == ["R13: D3 의 질의가 안 바뀌었다"]
    d0bent = copy.deepcopy(record)
    next(r for r in d0bent["rows"] if r["arm"] == "D0" and r["id"] == "R13").update(querySha256="x")
    assert "R13: D0 가 운영 글을 안 보냈다" in d.tally([d0bent])["treatment"]

    drift = copy.deepcopy(record)
    drift["env"]["khalaAfter"] = {"head": "other", "dirty": ""}
    assert d.tally([drift])["comparable"] == "khala 코드 신원이 판 앞뒤로 다르다"
    cases = copy.deepcopy(record)
    cases["env"]["cases"]["scoringHash"] = "other"
    assert d.tally([cases])["comparable"] == "사례 파일의 채점 칸이 다르다"


GUARD_CASES = (
    ("M1", (21, 21), (20, 21), True), ("M1", (21, 21), (19, 21), False),
    ("M2", (0, 21), (0, 21), True), ("M2", (0, 21), (1, 21), False),
    ("M4", (19, 19), (18, 19), True), ("M4", (19, 19), (17, 19), False),
    ("forbidden", (0, 11), (0, 11), True), ("forbidden", (0, 11), (1, 11), False),
    ("cards", (21, 21), (20, 21), True), ("cards", (21, 21), (19, 21), False),
    ("clean", (17, 21), (16, 21), True), ("clean", (17, 21), (15, 21), False),
    ("failed", 0, 0, True), ("failed", 0, 1, False),
    ("nullRationale", (0, 21), (0, 21), True), ("nullRationale", (0, 21), (1, 21), False),
    ("citationPass", 1.0, 0.95, True), ("citationPass", 1.0, 0.94, False), ("citationPass", 1.0, None, False),
    ("citedWhenBoth", (18, 18), (17, 18), True), ("citedWhenBoth", (18, 18), (16, 18), False),
)


def test_가드_열의_문턱():
    """꼴(후보 외 선택)과 안전(금지) · 실패 · 이유 없는 권고는 봐 주지 않고, 나머지는 한 칸(인용 검증은 0.05)을 봐 준다(설계서 §2)."""
    base = {"M1": (21, 21), "M2": (0, 21), "M4": (19, 19), "forbidden": (0, 11), "cards": (21, 21), "clean": (17, 21),
            "failed": 0, "nullRationale": (0, 21), "citationPass": 1.0, "citedWhenBoth": (18, 18)}
    assert len(d.guards(base, base)) == 10 and all(d.guards(base, base).values())
    for field, d0, d3, holds in GUARD_CASES:
        g = d.guards(dict(base, **{field: d0}), dict(base, **{field: d3}))
        assert g[field] is holds, (field, d0, d3)
        assert all(v for k, v in g.items() if k != field), field
