"""검색 텍스트 칸 — 두 경로 한 회차 실행. 설계서 `docs/superpowers/specs/2026-10-06-검색-텍스트-칸.md`. 가짜 응답으로 돈다."""

import copy
import datetime
import functools
import hashlib
import json

import pytest

from eval import ask_trial as at
from eval import fusion_trial as ft
from eval import gen_diag_trial as gdt
from eval import query_trial as qt
from eval import recommend as rec
from eval import st_trial as st
from eval.recommend_score import load_cases
from eval.run import fixture_history, load, query_for
from eval.score import QUERY
from explainer.client import INCIDENT_EXCLUDED
from recorder.outcome import TRANSIENT

AT = "2026-10-07T01:00:00+00:00"
LATER = "2026-10-07T03:00:00+00:00"
CORPUS = "c-test"
GLOSSARY = "picasso — 표준 용어 사전 (Glossary)"
G_CARD = "절차: 첫 걸음\n먼저: 확인\n금지: 없음\n갈림: 관측\n근거 세기: 강함\n"
D_CARD = "절차: a\n먼저: b\n금지: c\n갈림: d\n근거 세기: e"
OLD, NEW = st.TITLE_PAIR
SPEC_FILES = {"docs/superpowers/specs/2026-10-06-검색-텍스트-칸.md", "eval/st_trial.py", "tests/test_eval_st_trial.py"}


#: 시험의 git 객체 해시와 khala 코드 식별 정보 — git 서브프로세스를 안 띄우고, 식별 정보가 늘 `None` 이라 못 보는 검사를 본다.
FAKE_HEAD = "0" * 40
KHALA = {"head": "k" * 40, "dirty": ""}


def fake_git(*args, cwd=None):
    return FAKE_HEAD


def fake_identity():
    return dict(KHALA)


@pytest.fixture(autouse=True)
def expected(monkeypatch):
    """코퍼스 버전 기대 값은 실행 전에 박는다 — 시험에서는 가짜 값을 둔다. git 과 khala 식별 정보도 고정한다."""
    monkeypatch.setitem(st.EXPECTED, "corpus", CORPUS)
    monkeypatch.delenv("KHALA_ROOT", raising=False)
    monkeypatch.setattr(ft, "git", fake_git)
    monkeypatch.setattr(ft, "khala_identity", fake_identity)


@functools.lru_cache(maxsize=None)
def entries():
    return {e["id"]: e for e in load(st.GOLDEN)}


@functools.lru_cache(maxsize=None)
def cases():
    return {c["id"]: c for c in load_cases()["cases"]}


def live(title):
    """재적재 뒤 khala 가 실어 보낼 제목 — 정지 코드 문서만 새 제목이다."""
    return NEW if title == OLD else title


def versions(**over):
    v = {"usage": {"model": st.EXPECTED["model"]}, "prompt_version": st.EXPECTED["prompt"], "corpus_version": CORPUS,
         "search_fingerprint": st.EXPECTED["search"]}
    v.update(over)
    return v


def g_data(answer, cited=(), evidence=None, weak=False, failed=None, degraded=()):
    """설명 경로 `/search/answer` 의 `data` 한 벌."""
    return {"answer": "" if failed else answer,
            "citations": [] if failed else [{"title": t, "section": "5", "verified": True} for t in cited],
            "evidence_snippets": [{"doc_title": t, "rank": i + 1, "chunk_rid": f"c{i}"}
                                  for i, t in enumerate(evidence if evidence is not None else cited)],
            **versions(), "degraded": list(degraded), "enrichment_failed": [], "weak_evidence": weak,
            "top_bm25": 2.5, "top_distance": 0.3, "llm_failed": bool(failed), "llm_failure_reason": failed}


def d_data(pick="ESCALATE", doc=GLOSSARY, evidence=None, degraded=(), failed=None, weak=False):
    """진단 경로 `/search/answer` 의 `data` 한 벌 — 라벨 하나, 인용 하나(이유 문장에 붙음)."""
    answer = f"권고: {pick}\n이유: 사람이 먼저 본다 [출처: {doc}, §5.1].\n{D_CARD}"
    return {"answer": "" if failed else answer,
            "citations": [] if failed else [{"title": doc, "section": "§5.1", "verified": True}],
            "abstained": False, "weak_evidence": weak, "llm_failed": bool(failed), "llm_failure_reason": failed,
            "unverified_citations": 0, "unverified_numbers": 0, "numbers": [], "timing_ms": {},
            "evidence_snippets": [{"doc_title": t, "rank": i + 1, "chunk_rid": f"c{i}"}
                                  for i, t in enumerate(evidence if evidence is not None else [doc])],
            **versions(), "degraded": list(degraded), "enrichment_failed": [], "top_bm25": 1.0, "top_distance": 0.4}


def g_answer(lose=(), title=live):
    """사건은 답변 카드와 함께 기대 절차를 인용하고(G0 는 `lose` 의 항목에서 못 함), 질의 줄은 근거 없음으로 물러선다."""
    def make(eid, arm, body, n):
        e = entries()[eid]
        if e["kind"] == QUERY:
            return g_data("근거에 없다", weak=True)
        doc = (e.get("procedure") or {}).get("doc")
        if doc and not (arm == "G0" and eid in lose):
            t = title(doc)
            return g_data(G_CARD + f"본문 [출처: {t}, 5]", cited=(t,))
        return g_data(G_CARD + "본문 [출처: 다른 문서, 1]", cited=("다른 문서",))
    return make


def procedure(cid):
    docs = cases()[cid]["procedureDocs"]
    return live(docs[0]) if docs else GLOSSARY


def d_answer(cid, arm, body, n):
    return d_data(doc=procedure(cid))


def g_again(status, data):
    """설명 경로가 같은 줄에서 다시 하는가 — 200 이 아닌 것 전부와 다시 할 만한 생성 실패(`with_retries`)."""
    return status != 200 or bool(data.get("llm_failed") and data.get("llm_failure_reason") in TRANSIENT)


def d_again(status, data):
    """진단 경로가 같은 줄에서 다시 하는가 — 사유가 다시 할 만한 것(`run_case`)."""
    return (data or {}).get("llm_failure_reason") in TRANSIENT


def fake_khala(calls, seq, answer, again, budget):
    """부르는 차례대로 (항목, 실험군)을 짚어 답한다. 다시 하는 실패면 시도 예산까지 같은 줄에 머문다. `answer` 는 (항목, 실험군, 본문,
    그 줄의 몇째 시도)를 받아 `data` 나 `(상태, 본문)` 을 돌려준다. 성공 봉투에는 khala 처럼 받은 것을 되울린다."""
    state = {"pos": 0, "tries": 0}

    def transport(method, url, headers, body):
        calls.append((url, copy.deepcopy(body)))
        if url.endswith("/search"):
            return 200, {"success": True, "data": {}}
        key, arm = seq[state["pos"] % len(seq)]
        state["tries"] += 1
        got = answer(key, arm, body, state["tries"])
        status, data = got if isinstance(got, tuple) else (200, got)
        if not again(status, data) or state["tries"] >= budget:
            state["pos"], state["tries"] = state["pos"] + 1, 0
        if status != 200:
            return status, data
        text = body.get("search_text") or ""
        data = dict(data, answer_context_len=len(body.get("answer_context") or ""),
                    search_text_len=len(text) if text.strip() else 0,
                    excluded_doc_types=list(body.get("exclude_doc_types") or []), searched_tenants=[body["tenant"]],
                    identifier_channel_asked=bool(body.get("identifier_channel")), route_used="hybrid_only")
        return 200, {"success": True, "data": data}

    return transport


def g_seq(only=None):
    wanted = st.targets(only, st.ARMS_G) if only is not None else None
    return [(item["entry"]["id"], arm) for item in st.plan_g() for arm in item["order"]
            if wanted is None or arm in wanted.get(item["entry"]["id"], ())]


def d_seq(only=None):
    wanted = st.targets(only, st.ARMS_D) if only is not None else None
    return [(item["prep"]["case"]["id"], arm) for item in st.plan_d() for arm in item["order"]
            if wanted is None or arm in wanted.get(item["prep"]["case"]["id"], ())]


def run_g(tmp_path, answer=None, only=None, name="g-1", at_=AT, transport=None, file=None):
    """가짜 khala 로 설명 경로 실행 — `(기록, 부른 것)`. `name` 은 실행 이름, `file` 은 기록 파일 이름(없으면 실행 이름)이다."""
    calls, out = [], tmp_path / f"{file or name}.json"
    transport = transport or fake_khala(calls, g_seq(only), answer or g_answer(), g_again,
                                        1 if only is not None else st.LIMIT)
    st.run_g(name, out, "t", "http://x", transport=transport, clock=lambda: at_, only=only)
    return json.loads(out.read_text(encoding="utf-8")), calls


def run_d(tmp_path, answer=None, only=None, name="d-1", at_=AT, transport=None, file=None):
    """가짜 khala 로 진단 경로 실행 — `(기록, 부른 것)`."""
    calls, out = [], tmp_path / f"{file or name}.json"
    transport = transport or fake_khala(calls, d_seq(only), answer or d_answer, d_again,
                                        1 if only is not None else rec.MAX_ATTEMPTS)
    st.run_d(name, out, "t", "http://x", transport=transport, clock=lambda: at_, only=only, commit="abc1234")
    return json.loads(out.read_text(encoding="utf-8")), calls


def stopped(tmp_path, runner, answer, name, transport=None, file=None, only=None):
    """멈추는 실행 — `(기록, 멈춘 글)`."""
    with pytest.raises(SystemExit) as stop:
        runner(tmp_path, answer=answer, name=name, transport=transport, file=file, only=only)
    return json.loads((tmp_path / f"{file or name}.json").read_text(encoding="utf-8")), str(stop.value)


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    """계획대로 돈 두 경로의 기록 — 시험마다 사본을 쓴다."""
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("KHALA_ROOT", raising=False)
        mp.setattr(ft, "git", fake_git)
        mp.setattr(ft, "khala_identity", fake_identity)
        tmp = tmp_path_factory.mktemp("st")
        g, _ = run_g(tmp)
        d, _ = run_d(tmp)
    return g, d


def fresh(base):
    return copy.deepcopy(base[0]), copy.deepcopy(base[1])


def row_of(record, rid, arm):
    return next(r for r in record["rows"] if (r["id"], r["arm"]) == (rid, arm))


# ── 1. 계획 ──

def test_plans(monkeypatch):
    """설명 경로 G0 · GS 는 질의가 같은 Q0 이고 GS 만 `search_text` = Q3(질의 줄은 안 보냄). 진단 경로 D0 · DS 는 질의와 답변 컨텍스트가
    권고 측정기의 글 그대로이고 DS 만 `search_text` = Q3. 홀수째는 기준 쪽 먼저, 짝수째는 S 쪽 먼저(설계서 §1)."""
    golden = load(st.GOLDEN)
    built = qt.queries()
    history = fixture_history()
    work = st.plan_g()
    assert [item["entry"]["id"] for item in work] == [e["id"] for e in golden] and len(work) == 15
    for i, item in enumerate(work):
        e = item["entry"]
        assert item["order"] == (("G0", "GS") if i % 2 == 0 else ("GS", "G0")), e["id"]
        q0 = query_for(e, prior=history)
        assert item["G0"] == {"query": q0, "context": None, "searchText": None}, e["id"]
        if e["kind"] == QUERY:
            assert item["GS"] == item["G0"] and tuple(item["exclude"]) == (), e["id"]
        else:
            assert item["GS"] == {"query": q0, "context": None, "searchText": at.texts(built[e["id"]])["Q3"]}, e["id"]
            assert item["GS"]["searchText"] != q0 and tuple(item["exclude"]) == INCIDENT_EXCLUDED, e["id"]
    assert sum(item["GS"]["searchText"] is not None for item in work) == 12

    doc = load_cases()
    prepared = [p for p in rec.prepare(doc) if not p["case"]["repeatOf"]]
    built = qt.queries(doc)
    work = st.plan_d()
    assert [item["prep"]["case"]["id"] for item in work] == [p["case"]["id"] for p in prepared] and len(work) == 21
    assert "R02" not in {item["prep"]["case"]["id"] for item in work}
    for i, (item, prep) in enumerate(zip(work, prepared)):
        cid = prep["case"]["id"]
        assert item["order"] == (("D0", "DS") if i % 2 == 0 else ("DS", "D0")), cid
        assert item["D0"] == {"query": prep["query"], "context": prep["context"], "searchText": None}, cid
        assert item["DS"] == {"query": prep["query"], "context": prep["context"],
                              "searchText": at.texts(built[cid])["Q3"]}, cid
        assert item["DS"]["searchText"] != prep["query"] and tuple(item["exclude"]) == rec.EXCLUDE, cid

    assert st.targets({"G4:GS", "G7"}, st.ARMS_G) == {"G4": {"GS"}, "G7": {"G0", "GS"}}
    assert st.targets({"R03:D0", "R03:DS"}, st.ARMS_D) == {"R03": {"D0", "DS"}}
    for bad in ({"G4:G3"}, {"R03:GS"}):
        with pytest.raises(SystemExit, match="실험군"):
            st.targets(bad, st.ARMS_D if bad == {"R03:GS"} else st.ARMS_G)

    assert "eval/st/.gitkeep" in st.COMMITTED and SPEC_FILES <= set(st.COMMITTED)
    # Q3 가 비었거나 공백뿐이면 짓는 자리에서 멈춘다
    real = at.texts
    monkeypatch.setattr(at, "texts", lambda query: dict(real(query), Q3=" " * 3))
    with pytest.raises(ValueError, match="Q3"):
        st.plan_g()
    with pytest.raises(ValueError, match="Q3"):
        st.plan_d()
    # Q0 가 측정기 · 진단 함수의 글과 다르면 짓는 자리에서 멈춘다
    monkeypatch.setattr(at, "texts", lambda query: dict(real(query), Q0="다른 글"))
    with pytest.raises(ValueError, match="Q0"):
        st.plan_g()
    with pytest.raises(ValueError, match="Q0"):
        st.plan_d()


# ── 2. 전송 감싸기와 본문 해시 ──

def test_search_text_transport():
    """`with_search_text` 는 글이 있을 때만 본문 사본에 `search_text` 키 하나를 더한다. 본문 해시는
    `json.dumps(본문, ensure_ascii=False, sort_keys=True, separators=(",", ":"))` 의 sha256 이다."""
    seen = []

    def transport(method, url, headers, body):
        seen.append((method, url, headers, body))
        return 200, {"ok": True}

    body = {"query": "질의", "tenant": "picasso", "top_k": 20, "identifier_channel": True}
    assert st.with_search_text(transport, "검색 텍스트")("POST", "u", {"h": 1}, body) == (200, {"ok": True})
    assert seen[-1] == ("POST", "u", {"h": 1}, dict(body, search_text="검색 텍스트"))
    assert "search_text" not in body, "보낸 쪽 본문은 그대로다(사본에 더한다)"
    for empty in (None, ""):
        st.with_search_text(transport, empty)("POST", "u", {}, body)
        assert seen[-1][3] == body and "search_text" not in seen[-1][3], f"{empty!r} 는 키를 안 보낸다"
        assert seen[-1][3] is not body

    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    want = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert st.body_sha(body) == want
    assert st.body_sha(dict(reversed(list(body.items())))) == want, "키 차례에 흔들리지 않는다"
    assert st.body_sha({"query": "한글"}) == hashlib.sha256('{"query":"한글"}'.encode("utf-8")).hexdigest()
    assert st.body_sha(dict(body, search_text="x")) != want
    assert st.body_sha(st.plain(dict(body, search_text="x"))) == want and st.plain(body) == body
    assert st.sha(None) is None and st.sha("가") == hashlib.sha256("가".encode("utf-8")).hexdigest()


# ── 3. 설명 경로 실행 ──

def test_run_g_writes_each_line_and_stops(tmp_path, monkeypatch):
    """줄마다 기록을 다시 쓰고 `complete` 는 끝에서만 참이다. G0 는 측정기와 같은 본문, GS 는 그 본문에 `search_text` 만 더한다.
    401 · 403 · 422 · `quota` · `auth` 는 곧바로, 잇단 실패 둘이면 멈추고 그 줄까지 쓴 기록과 `env.stopped` 가 남는다."""
    writes = []
    real = rec.write
    monkeypatch.setattr(rec, "write", lambda path, env, rows, complete: writes.append((len(rows), complete))
                        or real(path, env, rows, complete))
    record, calls = run_g(tmp_path)
    assert writes == [(i, False) for i in range(1, 31)] + [(30, True)], "줄마다 다시 쓰고 끝에서만 complete"
    assert calls[0] == ("http://x/search", ft.WARM)
    sent = calls[1:]
    assert len(sent) == 30 and record["complete"] is True and len(record["rows"]) == 30
    env = record["env"]
    assert env["path"] == "g" and env["arms"] == ["G0", "GS"] and env["only"] is None and env["stopped"] is None
    assert env["at"] == AT and env["expected"]["prompt"] == st.EXPECTED["prompt"]
    golden = {item["id"]: item for item in ft.items() if item["set"] == "golden"}
    for i, item in enumerate(st.plan_g()):
        eid = item["entry"]["id"]
        measured, _, _ = ft.call(golden[eid], lambda *a: (200, {"success": True, "data": {}}), "http://x", "t")
        for j, arm in enumerate(item["order"]):
            url, body = sent[2 * i + j]
            assert url == "http://x/search/answer"
            text = item[arm]["searchText"]
            assert body == (dict(measured, search_text=text) if text else measured), f"{eid} {arm}"
            row = row_of(record, eid, arm)
            assert row["at"] == AT and row["sends"] == 1 and row["outcome"] in ("GIVEN", "NO_EVIDENCE")
            assert row["sentBodySha256"] == [st.body_sha(body)] and row["sentPlainSha256"] == [st.body_sha(measured)]
            assert row["sentSearchTextSha256"] == [st.sha(text)] and row["planSearchTextSha256"] == st.sha(text)
            assert row["sentSearchTextLen"] == len(text or "") == row["echo"]["search_text_len"]
            assert row["echo"]["identifier_channel_asked"] is True and row["echo"]["top_bm25"] == 2.5
            assert row["echo"]["excluded_doc_types"] == row["sentExclude"] == list(item["exclude"])
            assert row["sentTenant"] == "picasso" and row["sentIdentifierChannel"] is True
            assert row["statuses"] == [200] and row["unreachable"] is False

    record, why = stopped(tmp_path, run_g, None, "s422", transport=_refuse_at(3, 422))
    assert "422" in why and record["complete"] is False and len(record["rows"]) == 3, "그 줄까지 쓴 뒤에 멈춘다"
    assert record["env"]["stopped"]["basis"] is True and "422" in record["env"]["stopped"]["why"]
    for status in (401, 403):
        record, why = stopped(tmp_path, run_g, None, f"s{status}", transport=_refuse_at(1, status))
        assert str(status) in why and len(record["rows"]) == 1 and record["env"]["stopped"]["basis"] is True

    for reason, rows, basis in (("quota", 1, True), ("auth", 1, True), ("timeout", 2, False)):
        record, why = stopped(tmp_path, run_g, lambda eid, arm, body, n, r=reason: g_data("", failed=r), f"s-{reason}")
        assert record["complete"] is False and len(record["rows"]) == rows, reason
        assert all(r["reason"] == reason for r in record["rows"]) and record["env"]["stopped"]["basis"] is basis, reason
        if reason == "timeout":
            assert [r["attempts"] for r in record["rows"]] == [2, 2], "다시 할 만한 사유는 시도 한도 2 까지"
            assert "잇달아" in record["env"]["stopped"]["why"]

    cut = (599, {"detail": "ConnectError: 연결 거부", "llm_failure_reason": "unavailable"})
    record, _ = stopped(tmp_path, run_g, lambda eid, arm, body, n: cut, "s-cut")
    assert len(record["rows"]) == 2 and all(r["unreachable"] for r in record["rows"])
    assert record["env"]["stopped"]["basis"] is True, "연결 불가 둘은 기반 장애다"
    record, _ = stopped(tmp_path, run_g, lambda eid, arm, body, n: g_data("", failed="unavailable"), "s-bridge")
    assert len(record["rows"]) == 2 and all(r["unreachable"] and r["statuses"] == [200, 200] for r in record["rows"])
    assert record["env"]["stopped"]["basis"] is True, "브리지가 죽어 khala 가 200 에 실은 unavailable 도 연결 불가다"
    mixed = {"n": 0}

    def cut_then_timeout(eid, arm, body, n):
        mixed["n"] += 1
        return cut if mixed["n"] <= 2 else g_data("", failed="timeout")

    record, _ = stopped(tmp_path, run_g, cut_then_timeout, "s-mixed")
    assert len(record["rows"]) == 2 and record["env"]["stopped"]["basis"] is False, "연결 불가 하나와 timeout 하나는 기반 장애가 아니다"
    record, _ = run_g(tmp_path, answer=lambda eid, arm, body, n: g_data("", failed="timeout") if (eid, arm) == ("G1", "G0")
                      else g_answer()(eid, arm, body, n), name="one-fail")
    assert record["complete"] is True and record["env"]["stopped"] is None, "실패 하나는 멈추지 않는다"

    asked = []
    out = tmp_path / "warm.json"
    with pytest.raises(SystemExit) as stop:
        st.run_g("g-1", out, "t", "http://x", clock=lambda: AT,
                 transport=lambda m, u, h, b: asked.append(u) or (502, {"detail": "프록시"}))
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert "예열" in str(stop.value) and asked == ["http://x/search"], "예열이 200 이 아니면 하나도 안 부른다"
    assert saved["rows"] == [] and saved["complete"] is False and saved["env"]["stopped"]["basis"] is True

    # 실행 명령의 거부 — 기대 코퍼스 · 경계 시각이 비었거나 지금이 경계 앞이면 khala 를 안 부른다
    after = datetime.datetime(2026, 10, 7, 9, 0, tzinfo=st.KST)
    argv = ["run", "g-9", "--path", "g", "--out", str(tmp_path / "x.json")]
    monkeypatch.setenv("NEXUS_TOKEN", "t")
    monkeypatch.setitem(st.EXPECTED, "corpus", None)
    with pytest.raises(SystemExit, match="코퍼스"):
        st.main(argv, now=after)
    monkeypatch.setitem(st.EXPECTED, "corpus", CORPUS)
    with pytest.raises(SystemExit, match="경계 시각 앞"):
        st.main(argv, now=datetime.datetime(2026, 10, 6, 21, 14, 59, tzinfo=st.KST))
    with pytest.raises(SystemExit, match="경계 시각 앞"):
        st.main(argv, now=datetime.datetime(2026, 10, 6, 12, 14, 0, tzinfo=datetime.timezone.utc))
    monkeypatch.setitem(st.BOUNDARIES, "corpus", None)
    with pytest.raises(SystemExit, match="경계 시각이 비었다"):
        st.main(argv, now=after)
    monkeypatch.setitem(st.BOUNDARIES, "corpus", datetime.datetime(2026, 10, 6, 21, 14, 59, tzinfo=st.KST))
    with pytest.raises(SystemExit, match="KHALA_ROOT"):
        st.main(argv, now=after)
    monkeypatch.delenv("NEXUS_TOKEN")
    with pytest.raises(SystemExit, match="토큰"):
        st.main(argv, now=after)
    with pytest.raises(SystemExit, match="--path"):
        st.main(["run", "g-9", "--path", "x", "--out", str(tmp_path / "x.json")], now=after)


def _refuse_at(nth, status):
    """`/search/answer` 의 `nth` 째 부름부터 `status` 로 거절하는 전송 — 그 앞은 계획대로 답한다."""
    calls = []
    fine = fake_khala(calls, g_seq(), g_answer(), g_again, st.LIMIT)
    count = {"n": 0}

    def transport(method, url, headers, body):
        if url.endswith("/search/answer"):
            count["n"] += 1
            if count["n"] >= nth:
                return status, {"detail": "거절"}
        return fine(method, url, headers, body)

    return transport


# ── 4. 진단 경로 실행 ──

def test_run_d_sends_function_text_and_search_text(tmp_path, monkeypatch):
    """진단 함수가 지은 질의와 답변 컨텍스트를 그대로 보낸다 — D0 는 권고 측정기와 바이트까지 같은 본문, DS 는 그 본문에 `search_text`
    = Q3 만 더한다. 줄마다 기록을 다시 쓰고 멈춤 규칙은 설명 경로와 같다."""
    writes = []
    real = rec.write
    monkeypatch.setattr(rec, "write", lambda path, env, rows, complete: writes.append((len(rows), complete))
                        or real(path, env, rows, complete))
    record, calls = run_d(tmp_path)
    assert writes == [(i, False) for i in range(1, 43)] + [(42, True)]
    assert calls[0] == ("http://x/search", ft.WARM)
    sent = calls[1:]
    assert len(sent) == 42 and record["complete"] is True and len(record["rows"]) == 42
    env = record["env"]
    assert env["path"] == "d" and env["arms"] == ["D0", "DS"] and env["only"] is None and env["stopped"] is None
    for i, item in enumerate(st.plan_d()):
        prep = item["prep"]
        cid = prep["case"]["id"]
        golden = []
        rec.client_for("http://x", "t", transport=lambda m, u, h, b: golden.append(b) or (200, {}))(prep["context"])(prep["query"])
        for j, arm in enumerate(item["order"]):
            url, body = sent[2 * i + j]
            text = item[arm]["searchText"]
            assert url == "http://x/search/answer"
            assert body == (dict(golden[0], search_text=text) if text else golden[0]), f"{cid} {arm}"
            row = row_of(record, cid, arm)
            assert row["receivedQuerySha256"] == [row["querySha256"]] == [st.sha(prep["query"])]
            assert row["receivedContextSha256"] == [row["contextSha256"]] == [st.sha(prep["context"])]
            assert row["sentQuery"] == prep["query"] and row["sentContext"] == prep["context"], "함수가 지은 글 그대로"
            assert row["sentPlainSha256"] == [st.body_sha(golden[0])] and row["sentBodySha256"] == [st.body_sha(body)]
            assert row["sentSearchTextSha256"] == [st.sha(text)] and row["echo"]["search_text_len"] == len(text or "")
            assert row["echo"]["answer_context_len"] == len(prep["context"]) and row["sends"] == 1
            assert row["response"]["outcome"] == "RECOMMENDED" and row["attempts"][-1].get("rerun") is None

    def flaky(cid, arm, body, n):
        return d_data(doc=procedure(cid), failed="timeout" if (cid, arm, n) == ("R05", "D0", 1) else None)

    record, _ = run_d(tmp_path, answer=flaky, name="d-flaky")
    r05 = row_of(record, "R05", "D0")
    assert r05["sends"] == 2 and len(r05["sentPlainSha256"]) == 2 and len(set(r05["sentPlainSha256"])) == 1
    assert [a["reason"] for a in r05["attempts"]] == ["timeout", None]

    record, why = stopped(tmp_path, run_d, None, "s422", transport=_refuse_d_at(3, 422))
    assert "422" in why and record["complete"] is False and len(record["rows"]) == 3
    assert record["env"]["stopped"]["basis"] is True
    for reason, rows, basis in (("quota", 1, True), ("auth", 1, True), ("timeout", 2, False)):
        record, _ = stopped(tmp_path, run_d, lambda cid, arm, body, n, r=reason: d_data(failed=r), f"s-{reason}")
        assert record["complete"] is False and len(record["rows"]) == rows, reason
        assert all(r["failed"] == reason for r in record["rows"]) and record["env"]["stopped"]["basis"] is basis, reason
    cut = (599, {"detail": "ConnectError", "llm_failure_reason": "unavailable"})
    record, _ = stopped(tmp_path, run_d, lambda cid, arm, body, n: cut, "s-cut")
    assert len(record["rows"]) == 2 and record["env"]["stopped"]["basis"] is True
    record, _ = stopped(tmp_path, run_d, lambda cid, arm, body, n: d_data(failed="unavailable"), "s-bridge")
    assert all(r["unreachable"] and [a["reason"] for a in r["attempts"]] == ["unavailable"] * 2 for r in record["rows"])
    assert len(record["rows"]) == 2 and record["env"]["stopped"]["basis"] is True
    swing = {"n": 0}

    def unavailable_then_timeout(cid, arm, body, n):
        swing["n"] += 1
        return d_data(failed="unavailable" if swing["n"] != 2 else "timeout")

    record, _ = stopped(tmp_path, run_d, unavailable_then_timeout, "s-swing")
    assert [r["unreachable"] for r in record["rows"]] == [False, True] and record["env"]["stopped"]["basis"] is False,         "한 시도라도 unavailable 이 아니면 연결 불가가 아니다"
    asked = []
    out = tmp_path / "warm.json"
    with pytest.raises(SystemExit) as stop:
        st.run_d("d-1", out, "t", "http://x", clock=lambda: AT, commit="abc1234",
                 transport=lambda m, u, h, b: asked.append(u) or (503, {}))
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert "예열" in str(stop.value) and asked == ["http://x/search"]
    assert saved["rows"] == [] and saved["env"]["stopped"]["basis"] is True


def _refuse_d_at(nth, status):
    calls = []
    fine = fake_khala(calls, d_seq(), d_answer, d_again, rec.MAX_ATTEMPTS)
    count = {"n": 0}

    def transport(method, url, headers, body):
        if url.endswith("/search/answer"):
            count["n"] += 1
            if count["n"] >= nth:
                return status, {"detail": "거절"}
        return fine(method, url, headers, body)

    return transport


# ── 5. 줄 단위 다시 부르기 ──

def test_rerun_line_level(tmp_path, base):
    """다시 부르기는 줄 단위다(`G4:GS`, 항목만 적으면 두 실험군). 줄마다 시도 하나이고 잇단 실패로 멈추지 않는다. 다시 부른 줄은 앞에서
    검색 부분 실패 · 다시 할 만한 생성 실패였던 것만, 한 번만 덮는다."""
    again, _ = run_g(tmp_path, only={"G2:GS", "G1"}, name="g-1r", at_=LATER)
    assert [(r["id"], r["arm"]) for r in again["rows"]] == [("G1", "G0"), ("G1", "GS"), ("G2", "GS")]
    assert again["env"]["only"] == ["G1", "G2:GS"] and again["complete"] is True
    assert all(r["sends"] == 1 for r in again["rows"])
    with pytest.raises(SystemExit, match="모르는 항목"):
        run_g(tmp_path, only={"G99"}, name="g-x")
    with pytest.raises(SystemExit, match="실험군"):
        run_g(tmp_path, only={"G1:G3"}, name="g-y")
    failing, _ = run_g(tmp_path, answer=lambda eid, arm, body, n: g_data("", failed="timeout"), only={"G1", "G2"},
                       name="g-1f", at_=LATER)
    assert failing["complete"] is True and len(failing["rows"]) == 4, "다시 부르는 실행은 잇단 실패로 안 멈춘다"
    assert all(r["sends"] == 1 and r["reason"] == "timeout" for r in failing["rows"]), "줄마다 한 번"
    quota_rerun, why = stopped(tmp_path, run_g, lambda eid, arm, body, n: g_data("", failed="quota"), "g-1q",
                               only={"G1:G0"})
    assert "quota" in why and quota_rerun["env"]["stopped"]["basis"] is True and len(quota_rerun["rows"]) == 1

    line, _ = run_d(tmp_path, only={"R04:DS", "R03"}, name="d-1r", at_=LATER)
    assert [(r["id"], r["arm"]) for r in line["rows"]] == [("R03", "DS"), ("R03", "D0"), ("R04", "DS")]
    assert all(r["attempts"][-1].get("rerun") is True and len(r["attempts"]) == 1 for r in line["rows"])
    stuck, _ = run_d(tmp_path, answer=lambda cid, arm, body, n: d_data(failed="timeout"), only={"R03", "R04"},
                     name="d-1f", at_=LATER)
    assert stuck["complete"] is True and len(stuck["rows"]) == 4 and all(len(r["attempts"]) == 1 for r in stuck["rows"])
    with pytest.raises(SystemExit, match="모르는 사례"):
        run_d(tmp_path, only={"R02"}, name="d-x")

    g, d = fresh(base)
    # 검색 부분 실패 줄 하나만 다시 부르면 선다
    broken = copy.deepcopy(g)
    row_of(broken, "G2", "GS")["diagnostics"]["degraded"] = ["vector"]
    out = st.tally([broken, d])
    assert out["g"]["comparable"] == "검색 부분 실패가 남았다" and out["g"]["broken"] == ["G2 GS"]
    fix, _ = run_g(tmp_path, only={"G2:GS"}, name="g-fix", at_=LATER)
    assert st.tally([broken, fix, d])["g"]["comparable"] is None, "고장 난 줄만 다시 부르면 선다"
    assert st.tally([fix, broken, d])["g"]["comparable"] is None, "시각 차례로 합친다"
    stale = copy.deepcopy(broken)
    row_of(stale, "G2", "GS")["diagnostics"]["corpus_version"] = "other"
    assert st.tally([stale, fix, d])["g"]["comparable"] == "버전 필드가 한 벌이 아니다", "덮인 줄의 버전 필드도 본다"
    whole, _ = run_g(tmp_path, only={"G2"}, name="g-whole", at_=LATER)
    assert st.tally([broken, whole, d])["g"]["badReruns"] == ["G2 G0"], "멀쩡한 줄을 다시 부르면 안 선다"
    twice = copy.deepcopy(fix)
    twice["env"]["at"] = "2026-10-07T04:00:00+00:00"
    out = st.tally([broken, fix, twice, d])
    assert out["g"]["comparable"] == "다시 부른 줄이 검색 부분 실패 · 다시 부를 실패가 아니었거나 두 번이다"
    # 다시 할 만한 생성 실패는 다시 불러야 하고, 다시 불러도 실패면 그대로 센다
    pending = copy.deepcopy(g)
    row_of(pending, "G1", "G0").update(outcome="GENERATION_FAILED", reason="timeout", answer="", citations=[], echo=None)
    assert st.tally([pending, d])["g"]["comparable"] == "다시 부를 실패가 남았다"
    plain_fail = copy.deepcopy(g)
    row_of(plain_fail, "G1", "G0").update(outcome="GENERATION_FAILED", reason="exception:KeyError", answer="",
                                          citations=[], echo=None)
    assert st.tally([plain_fail, d])["g"]["comparable"] is None, "다시 할 만하지 않은 실패는 다시 안 부른다"
    still, _ = run_g(tmp_path, answer=lambda eid, arm, body, n: g_data("", failed="timeout"), only={"G1:G0"},
                     name="g-still", at_=LATER)
    out = st.tally([pending, still, d])
    assert out["g"]["comparable"] is None and out["g"]["failedAfterRerun"] == ["G1 G0"]
    assert out["g"]["arms"]["G0"]["failed"] == 1 and out["g"]["guards"]["failed"] is True, "기준 쪽 실패는 가드를 안 깬다"
    still2 = copy.deepcopy(still)
    still2["env"]["at"] = "2026-10-07T04:00:00+00:00"
    assert st.tally([pending, still, still2, d])["g"]["badReruns"] == ["G1 G0"], "다시 불러도 실패인 줄도 한 번만 덮는다"
    quota_rerun["env"]["at"] = LATER
    out = st.tally([pending, quota_rerun, still, d])
    assert out["excluded"] == [] and out["g"]["comparable"] == "멈춘 기록이 있다", "다시 부른 기록은 기반 장애여도 안 뺀다"
    assert "G1 G0" in out["g"]["badReruns"], "멈춘 다시 부르기도 그 줄의 한 번이다"
    unreachable = copy.deepcopy(pending)
    row_of(unreachable, "G1", "G0")["reason"] = "unreachable"
    assert st.tally([unreachable, d])["g"]["comparable"] == "다시 부를 실패가 남았다", "전송이 끊긴 실패도 다시 부른다"
    wrong = copy.deepcopy(still)
    wrong["rows"][0]["id"] = "G3"
    assert st.tally([pending, wrong, d])["g"]["badReruns"] == ["G3 G0"]

    dbroken = copy.deepcopy(d)
    row_of(dbroken, "R07", "DS")["diagnostics"]["enrichment_failed"] = ["entities"]
    assert st.tally([g, dbroken])["d"]["comparable"] == "검색 부분 실패가 남았다"
    dfix, _ = run_d(tmp_path, only={"R07:DS"}, name="d-fix", at_=LATER)
    assert st.tally([g, dbroken, dfix])["d"]["comparable"] is None
    dpending = copy.deepcopy(d)
    row_of(dpending, "R04", "D0").update(response=None, failed="rate_limit", answer=None, diagnostics=None, echo=None)
    assert st.tally([g, dpending])["d"]["comparable"] == "다시 부를 실패가 남았다"
    dstill, _ = run_d(tmp_path, answer=lambda cid, arm, body, n: d_data(failed="timeout"), only={"R04:D0"},
                      name="d-still", at_=LATER)
    out = st.tally([g, dpending, dstill])
    assert out["d"]["comparable"] is None and out["d"]["failedAfterRerun"] == ["R04 D0"] and out["d"]["unpaired"] == ["R04"]
    assert out["d"]["arms"]["D0"]["procedureCited"] == out["d"]["arms"]["DS"]["procedureCited"] == (19, 19)
    assert st.tally([g, d, dfix])["d"]["badReruns"] == ["R07 DS"]


# ── 6. 성립 ──

def test_tally_validity(tmp_path, base, monkeypatch):
    """성립은 경로마다 — 전체 실행 기록 하나 · 멈춘 기록 없음 · `complete` · 고정 파일 · 빠진 줄 없음 · 버전 필드(두 경로를 합쳐 한 벌,
    기대 값과 같음, 모르는 칸 없음) · 경계 시각 · 검색 부분 실패 · 처치 · khala 코드 식별 정보 · narrator 커밋. 답한 줄 0 인 채
    기반 장애로 멈춘 기록만 집계에서 뺀다."""
    kst = datetime.timezone(datetime.timedelta(hours=9))
    assert {k: v for k, v in st.EXPECTED.items() if k != "corpus"} ==         {"model": "claude-sonnet-5", "prompt": "efe1e242c0e3", "search": "b071397c854c"}
    assert st.BOUNDARIES == {"searchText": datetime.datetime(2026, 10, 6, 6, 42, 56, tzinfo=kst),
                             "promptVersion": datetime.datetime(2026, 10, 6, 19, 54, 23, tzinfo=kst),
                             "corpus": datetime.datetime(2026, 10, 6, 12, 14, 59, tzinfo=datetime.timezone.utc),
                             "syntheticSop": datetime.datetime(2026, 10, 7, 0, 3, 34, tzinfo=kst)}
    g, d = fresh(base)
    out = st.tally([g, d])
    assert out["g"]["comparable"] is None and out["d"]["comparable"] is None
    assert out["g"]["treatment"] == [] and out["d"]["treatment"] == [] and out["excluded"] == []
    assert out["versions"] == [json.dumps([st.EXPECTED["model"], st.EXPECTED["prompt"], CORPUS, st.EXPECTED["search"]])]

    def both(records):
        result = st.tally(records)
        return result["g"]["comparable"], result["d"]["comparable"]

    # 버전 필드 — 기대 값 · 한 벌 · 모르는 칸(정규화 없이)
    monkeypatch.setitem(st.EXPECTED, "prompt", "73536dc7c9c0")
    assert both([g, d]) == ("버전 필드가 기대 값과 다르다",) * 2
    monkeypatch.setitem(st.EXPECTED, "prompt", "efe1e242c0e3")
    monkeypatch.setitem(st.EXPECTED, "corpus", None)
    assert both([g, d]) == ("버전 필드가 기대 값과 다르다",) * 2, "기대 코퍼스가 비었으면 성립하지 않는다"
    monkeypatch.setitem(st.EXPECTED, "corpus", CORPUS)
    for field, path, value, why in (
            ("search_fingerprint", "d", "other", "버전 필드가 한 벌이 아니다"),
            ("corpus_version", "g", "", "모르는 버전 필드가 있다"),
            ("corpus_version", "d", None, "모르는 버전 필드가 있다"),
            ("prompt_version", "g", "81377584ff5a", "버전 필드가 한 벌이 아니다")):
        bent_g, bent_d = fresh(base)
        target = bent_g if path == "g" else bent_d
        target["rows"][4]["diagnostics"][field] = value
        assert both([bent_g, bent_d]) == (why, why), (field, value)
    bent_g, bent_d = fresh(base)
    for row in bent_g["rows"] + bent_d["rows"]:
        row["diagnostics"]["usage"] = {}
    assert both([bent_g, bent_d]) == ("모르는 버전 필드가 있다",) * 2, "근거 0건의 기권문은 모델이 비어 성립하지 않는다"
    bent_g, bent_d = fresh(base)
    for row in bent_d["rows"]:
        row["response"]["versions"]["promptVersion"] = "다른 값"
    assert both([bent_g, bent_d]) == (None, None), "버전 필드는 진단 응답이 아니라 계측에서 읽는다"

    # 경계 시각 — KST 경계와 UTC 줄 시각을 시간대째 견준다. 가장 늦은 경계는 합성 SOP 안내 문서 적재(10-07 00:03:34 KST)다
    for at_, early in (("2026-10-07T00:03:34+09:00", True), ("2026-10-06T15:03:34+00:00", True),
                       ("2026-10-06T15:03:33.999+00:00", True), ("2026-10-07T00:03:35+09:00", False),
                       ("2026-10-06T15:03:34.001+00:00", False), ("2026-10-07T01:00:00", True), ("어제", True),
                       (None, True), ("2026-10-06T19:00:00+09:00", True), ("2026-10-06T21:15:00+09:00", True)):
        bent_g, bent_d = fresh(base)
        bent_g["rows"][7]["at"] = at_
        out = st.tally([bent_g, bent_d])
        assert (out["g"]["comparable"] == "경계 시각 앞의 줄이 있다") is early, at_
        assert out["d"]["comparable"] is None and out["g"]["early"] == ([f"{bent_g['rows'][7]['id']} {bent_g['rows'][7]['arm']}"]
                                                                        if early else []), at_
    bent_g, bent_d = fresh(base)
    bent_d["rows"][0]["at"] = "2026-10-06T07:00:00+09:00"
    assert both([bent_g, bent_d]) == (None, "경계 시각 앞의 줄이 있다"), "프롬프트 버전 경계 앞"
    monkeypatch.setitem(st.BOUNDARIES, "promptVersion", None)
    assert both(fresh(base)) == ("경계 시각 앞의 줄이 있다",) * 2, "비어 있는 경계는 넘은 것이 아니다"
    monkeypatch.setitem(st.BOUNDARIES, "promptVersion", datetime.datetime(2026, 10, 6, 19, 54, 23, tzinfo=st.KST))

    # 기반 장애로 답한 줄 0 인 채 멈춘 기록만 뺀다(다른 경로의 khala · narrator 검사에서도 뺀다)
    first, _ = stopped(tmp_path, run_g, None, "g-1", transport=_refuse_at(1, 401), file="g-1-first")
    assert first["env"]["khalaAfter"] == KHALA and first["env"]["endedAt"] == AT, "멈춰도 끝 시각과 식별 정보를 적는다"
    first["env"].update(at="2026-10-06T23:00:00+00:00", narratorCommit="other", khalaBefore={"head": "other"})
    second = copy.deepcopy(g)
    second["env"]["pass"] = "g-2"
    out = st.tally([first, second, d])
    assert out["g"]["comparable"] is None and out["d"]["comparable"] is None and out["excluded"] == ["g-1"]
    # 전체 실행 이름 — `-1`, 그리고 `-1` 이 기반 장애로 빠졌을 때만 `-2`
    assert st.tally([second, d])["g"]["comparable"] == "전체 실행 기록의 이름이 규칙과 다르다", "-1 없는 -2"
    for name in ("g-3", "g-1b", "d-1"):
        other_name = copy.deepcopy(g)
        other_name["env"]["pass"] = name
        assert st.tally([first, other_name, d])["g"]["comparable"] == "전체 실행 기록의 이름이 규칙과 다르다", name
    renamed_d = copy.deepcopy(d)
    renamed_d["env"]["pass"] = "d-2"
    assert st.tally([first, second, renamed_d])["d"]["comparable"] == "전체 실행 기록의 이름이 규칙과 다르다",         "다른 경로의 -1 이 빠진 것으로는 -2 를 안 받는다"
    warm = {"env": dict(first["env"], **{"pass": "w"}), "complete": False, "rows": []}
    warm["env"]["stopped"] = {"why": "예열", "basis": True}
    assert st.tally([warm, g, d])["g"]["comparable"] is None
    late, _ = stopped(tmp_path, run_g, None, "g-late", transport=_refuse_at(3, 422))
    assert st.tally([late, g, d])["g"]["comparable"] == "멈춘 기록이 있다", "답한 줄이 있으면 빼지 않는다"
    slow, _ = stopped(tmp_path, run_g, lambda eid, arm, body, n: g_data("", failed="timeout"), "g-slow")
    assert st.tally([slow, g, d])["g"]["comparable"] == "멈춘 기록이 있다", "잇단 timeout 은 기반 장애가 아니다"
    quota, _ = stopped(tmp_path, run_d, lambda cid, arm, body, n: d_data(failed="quota"), "d-1", file="d-1-quota")
    quota["env"]["at"] = "2026-10-06T23:00:00+00:00"
    out = st.tally([g, quota, d])
    assert out["d"]["comparable"] is None and out["excluded"] == ["d-1"]
    # 한 경로의 멈춘 기록은 다른 경로의 성립을 깨지 않는다 — khala 식별 정보가 그 뒤 바뀌었어도
    halted, _ = stopped(tmp_path, run_d, lambda cid, arm, body, n: d_data(failed="timeout"), "d-1", file="d-1-slow")
    assert halted["env"]["khalaAfter"] == KHALA and halted["env"]["stopped"]["basis"] is False
    halted["env"]["khalaAfter"] = {"head": "other", "dirty": ""}
    assert both([g, d, halted]) == (None, "멈춘 기록이 있다")
    halted_g, _ = stopped(tmp_path, run_g, None, "g-1", transport=_refuse_at(3, 422), file="g-1-late")
    halted_g["env"]["narratorCommit"] = "other"
    assert both([g, halted_g, d]) == ("멈춘 기록이 있다", None)
    alone = st.tally([g, quota])
    assert alone["d"]["comparable"] == "전체 실행 기록이 하나가 아니다" and alone["verdict"] == st.KEEP

    # 전체 실행 · 끝남 · 고정 파일 · 빠진 줄
    assert both([g, d, copy.deepcopy(d)]) == (None, "전체 실행 기록이 하나가 아니다")
    assert both([d]) == ("전체 실행 기록이 하나가 아니다", None)
    unfinished = copy.deepcopy(g)
    unfinished["complete"] = False
    assert both([unfinished, d]) == ("끝나지 않은 기록이 있다", None)
    assert st.tally([g, d], head=lambda path: "other")["g"]["comparable"] == "골든셋 · fixtures · 정답 데이터가 HEAD 와 다르다"
    for key in ("golden", "fixtures", "truth"):
        bent = copy.deepcopy(g)
        bent["env"][key] = "other"
        assert both([bent, d])[0] == "골든셋 · fixtures · 정답 데이터가 HEAD 와 다르다", key
    for path, changed in (("eval/st_trial.py", ("평가 도구 코드가 집계 때의 HEAD 와 다르다",) * 2),
                          ("diagnose/core.py", (None, "평가 도구 코드가 집계 때의 HEAD 와 다르다")),
                          ("recorder/record.py", ("평가 도구 코드가 집계 때의 HEAD 와 다르다", None))):
        result = st.tally([g, d], head=lambda p, path=path: "other" if p == path else FAKE_HEAD)
        assert (result["g"]["comparable"], result["d"]["comparable"]) == changed, path
    bare = copy.deepcopy(d)
    del bare["env"]["measurers"]
    assert both([g, bare]) == (None, "평가 도구 코드가 집계 때의 HEAD 와 다르다")
    bent = copy.deepcopy(d)
    bent["env"]["cases"]["scoringHash"] = "other"
    assert both([g, bent]) == (None, "사례 파일의 채점 칸이 다르다")
    short = copy.deepcopy(g)
    short["rows"] = short["rows"][:-1]
    out = st.tally([short, d])
    assert out["g"]["comparable"] == "빠진 줄이 있다" and "arms" not in out["g"] and out["verdict"] == st.KEEP
    with pytest.raises(ValueError, match="경로"):
        st.tally([dict(g, env=dict(g["env"], path="x")), d])

    # khala 코드 식별 정보와 narrator 커밋은 두 경로의 모든 기록에서 한 벌이다
    moved = copy.deepcopy(d)
    moved["env"]["khalaAfter"] = {"head": "other", "dirty": ""}
    assert both([g, moved]) == ("khala 코드 식별 정보가 기록마다 다르다",) * 2
    other = copy.deepcopy(g)
    other["env"]["narratorCommit"] = "other"
    assert both([other, d]) == ("narrator 커밋이 기록마다 다르다",) * 2

    # 처치 — 설명 경로
    def g_bent(rid, arm, bend):
        bent_g, bent_d = fresh(base)
        bend(row_of(bent_g, rid, arm))
        result = st.tally([bent_g, bent_d])
        assert result["d"]["comparable"] is None
        return result["g"]

    other_sha = "0" * 64
    for rid, arm, bend in (
            ("G4", "GS", lambda r: r.update(sentSearchTextSha256=[other_sha])),
            ("G4", "GS", lambda r: r.update(planSearchTextSha256=other_sha)),
            ("G4", "G0", lambda r: r.update(sentSearchTextSha256=[st.sha("Q3")])),
            ("Q1", "GS", lambda r: r.update(sentSearchTextSha256=[st.sha("Q3")])),
            ("G4", "GS", lambda r: r.update(sentSearchTextLen=r["sentSearchTextLen"] + 1)),
            ("G4", "GS", lambda r: r.update(sentPlainSha256=[other_sha])),
            ("G4", "GS", lambda r: r.update(sentPlainSha256=r["sentPlainSha256"] + [other_sha])),
            ("G4", "GS", lambda r: r.update(sentPlainSha256=[])),
            ("G4", "GS", lambda r: r.update(sentQuerySha256=other_sha)),
            ("G4", "G0", lambda r: r.update(planQuerySha256=other_sha)),
            ("G4", "GS", lambda r: r.update(sentContextSha256=other_sha)),
            ("G4", "GS", lambda r: r.update(sentExclude=["spec"])),
            ("Q2", "G0", lambda r: r.update(sentExclude=["spec", "design_doc"])),
            ("G4", "GS", lambda r: r.update(sentTenant="other")),
            ("G4", "GS", lambda r: r.update(sentIdentifierChannel=False)),
            ("G4", "GS", lambda r: r["echo"].update(search_text_len=r["sentSearchTextLen"] - 1)),
            ("G4", "G0", lambda r: r["echo"].update(search_text_len=5)),
            ("G4", "GS", lambda r: r["echo"].update(answer_context_len=3)),
            ("G4", "GS", lambda r: r["echo"].update(excluded_doc_types=["spec"])),
            ("Q3", "GS", lambda r: r["echo"].update(excluded_doc_types=["spec"])),
            ("G4", "GS", lambda r: r["echo"].update(searched_tenants=["other"])),
            ("G4", "GS", lambda r: r["echo"].update(identifier_channel_asked=False)),
            ("G4", "GS", lambda r: r["echo"].update(identifier_channel_asked=None)),
            ("G4", "GS", lambda r: r.update(echo=None)),
            ("G4", "G0", lambda r: r["sentKeysAll"][0].append("search_text")),
            ("Q1", "GS", lambda r: r["sentKeysAll"][0].append("search_text")),
            ("G4", "GS", lambda r: r["sentKeysAll"][0].remove("search_text")),
            # 적은 보낸 칸과 되울림을 함께 바꿔도 계획과 견주어 잡는다
            ("G4", "GS", lambda r: (r.update(sentTenant="other"), r["echo"].update(searched_tenants=["other"]))),
            ("G4", "GS", lambda r: (r.update(sentIdentifierChannel=False), r["echo"].update(identifier_channel_asked=False))),
            ("Q2", "GS", lambda r: (r.update(sentExclude=["spec"]), r["echo"].update(excluded_doc_types=["spec"]))),
            ("G4", "GS", lambda r: (r.update(sentSearchTextLen=r["sentSearchTextLen"] + 1),
                                    r["echo"].update(search_text_len=r["sentSearchTextLen"]))),
    ):
        result = g_bent(rid, arm, bend)
        assert result["comparable"] == "처치가 계획과 다르다" and result["treatment"], (rid, arm)
        assert all(p.startswith(rid) for p in result["treatment"]), (rid, arm, result["treatment"])
    both_moved = g_bent("G5", "G0", lambda r: None)
    assert both_moved["comparable"] is None
    bent_g, bent_d = fresh(base)
    for arm in st.ARMS_G:
        row_of(bent_g, "G5", arm).update(sentPlainSha256=[other_sha])
    result = st.tally([bent_g, bent_d])["g"]
    assert result["treatment"] == ["G5 G0: search_text 를 뺀 본문이 운영 클라이언트의 본문과 다르다",
                                   "G5 GS: search_text 를 뺀 본문이 운영 클라이언트의 본문과 다르다"], "두 실험군이 같아도 운영 본문을 본다"
    failed_row = g_bent("G4", "GS", lambda r: r.update(outcome="GENERATION_FAILED", reason="exception:KeyError", echo=None,
                                                       answer="", citations=[]))
    assert failed_row["treatment"] == [], "실패한 줄은 되울림이 없어도 된다"

    # 처치 — 진단 경로
    def d_bent(rid, arm, bend):
        bent_g, bent_d = fresh(base)
        bend(row_of(bent_d, rid, arm))
        result = st.tally([bent_g, bent_d])
        assert result["g"]["comparable"] is None
        return result["d"]

    for rid, arm, bend in (
            ("R11", "DS", lambda r: r.update(sentSearchTextSha256=[other_sha])),
            ("R11", "D0", lambda r: r.update(sentSearchTextSha256=[st.sha("Q3")])),
            ("R11", "DS", lambda r: r.update(sentPlainSha256=[other_sha])),
            ("R11", "DS", lambda r: r.update(sentContextSha256=other_sha)),
            ("R11", "DS", lambda r: r.update(sentContext="다른 글")),
            ("R11", "D0", lambda r: r.update(sentQuery="다른 글")),
            ("R11", "DS", lambda r: r.update(receivedQuerySha256=[other_sha])),
            ("R11", "D0", lambda r: r.update(receivedContextSha256=[other_sha])),
            ("R11", "DS", lambda r: r.update(querySha256=other_sha)),
            ("R11", "D0", lambda r: r.update(contextSha256=other_sha)),
            ("R11", "DS", lambda r: r.update(sentExclude=list(INCIDENT_EXCLUDED))),
            ("R11", "DS", lambda r: r["echo"].update(answer_context_len=1)),
            ("R11", "DS", lambda r: r["echo"].update(search_text_len=0)),
            ("R11", "D0", lambda r: r["echo"].update(excluded_doc_types=list(INCIDENT_EXCLUDED))),
            ("R11", "DS", lambda r: r["echo"].update(searched_tenants=[])),
            ("R11", "DS", lambda r: r["echo"].update(identifier_channel_asked=False)),
            ("R11", "D0", lambda r: r.update(echo=None)),
    ):
        result = d_bent(rid, arm, bend)
        assert result["comparable"] == "처치가 계획과 다르다" and result["treatment"], (rid, arm)
        assert all(p.startswith(rid) for p in result["treatment"]), (rid, arm, result["treatment"])
    pair = d_bent("R12", "DS", lambda r: None)
    assert pair["comparable"] is None
    bent_g, bent_d = fresh(base)
    row_of(bent_d, "R12", "DS").update(sentContextSha256=other_sha, planContextSha256=other_sha)
    assert "R12: 두 실험군의 답변 컨텍스트가 다르다" in st.tally([bent_g, bent_d])["d"]["treatment"]
    bent_g, bent_d = fresh(base)
    row_of(bent_g, "G6", "GS").update(sentQuerySha256=other_sha)
    assert "G6: 두 실험군의 질의가 다르다" in st.tally([bent_g, bent_d])["g"]["treatment"]


# ── 7. 제목 짝 ──

def test_canon_titles(base):
    """채점은 옛 제목을 키로 쓴다 — 셀 때만 새 제목을 옛 제목으로 읽는다(기록은 그대로). 인용 제목과 근거 문서는 새 제목을 대는 것이고
    옛 제목을 안 대는 것만, 답의 글은 새 제목 글자를 옮긴다. 앞 실행과의 견줌에는 아홉 짝을 다 쓴다."""
    assert OLD == "합성 기체(fixture)의 정지 코드 표면 — Synthetic Stop-Code Surface"
    assert NEW == "합성 기체(fixture)의 정지 코드 API 표면 — Synthetic Stop-Code Surface"
    assert st.RENAMES[OLD] == NEW and len(st.RENAMES) == 9 and all("`" not in t for pair in st.RENAMES.items() for t in pair)
    assert st.RENAMES["오케스트레이션 — 세 층과 자원 소유"] == "오케스트레이션 — 세 계층과 자원 소유"
    assert st.RENAMES["시스템 한계 및 미결 과제 대장 (Known Limits & Technical Debt)"] == \
        "시스템 한계 및 오픈 항목 과제 레지스터 (Known Limits & Technical Debt)"

    row = {"id": "G7", "arm": "GS", "answer": f"본문 [출처: {NEW}, 3.1] 그리고 [출처: {GLOSSARY}, 2]",
           "citations": [{"title": NEW}, {"title": "합성 기체(fixture)의 정지 코드 API"}, {"title": "합성 기체(fixture)의 정지 코드"},
                         {"title": GLOSSARY}, {"title": "합성"}],
           "diagnostics": {"evidenceDocs": [NEW, GLOSSARY, "합성 기체(fixture)의 정지 코드 API 표면"]}}
    kept = copy.deepcopy(row)
    out = st.canon(row)
    assert row == kept, "기록은 그대로다"
    assert out["answer"] == f"본문 [출처: {OLD}, 3.1] 그리고 [출처: {GLOSSARY}, 2]"
    assert [c["title"] for c in out["citations"]] == [OLD, OLD, "합성 기체(fixture)의 정지 코드", GLOSSARY, "합성"]
    assert out["diagnostics"]["evidenceDocs"] == sorted({OLD, GLOSSARY})
    drow = {"id": "R13", "arm": "DS", "answer": f"권고: ESCALATE\n이유: x [출처: {NEW}, §3]",
            "response": {"citations": [{"title": NEW, "verified": True}], "outcome": "RECOMMENDED"},
            "diagnostics": {"evidenceDocs": [NEW]}}
    out = st.canon(drow)
    assert out["response"]["citations"][0]["title"] == OLD and out["diagnostics"]["evidenceDocs"] == [OLD]
    assert out["answer"].endswith(f"[출처: {OLD}, §3]") and drow["response"]["citations"][0]["title"] == NEW
    assert st.canon({"id": "R04", "arm": "D0", "answer": None, "response": None, "diagnostics": None})["response"] is None
    many = st.canon({"answer": "", "citations": [], "diagnostics": {"evidenceDocs": list(st.RENAMES.values())}},
                    pairs=tuple(st.RENAMES.items()))
    assert many["diagnostics"]["evidenceDocs"] == sorted(st.RENAMES), "아홉 짝 모두 옛 제목으로"
    assert st.canon({"answer": "", "citations": [], "diagnostics": {"evidenceDocs": ["오케스트레이션 — 세 계층과 자원 소유"]}}) \
        ["diagnostics"]["evidenceDocs"] == ["오케스트레이션 — 세 계층과 자원 소유"], "채점에는 짝 하나만 쓴다"

    # 셀 때 — 새 제목으로 온 정지 코드 문서를 옛 키로 센다
    g, d = fresh(base)
    out = st.tally([g, d])
    assert out["g"]["arms"]["G0"]["procedureDoc"] == out["g"]["arms"]["GS"]["procedureDoc"] == (10, 10)
    assert out["g"]["arms"]["GS"]["retrieved"][0] == 10 and out["g"]["bothRetrieved"] == \
        ["G1", "G2", "G3", "G4", "G6", "G7", "G8", "G9", "G10", "G11"]
    assert out["d"]["arms"]["D0"]["procedureCited"] == out["d"]["arms"]["DS"]["procedureCited"] == (20, 20)
    assert out["d"]["arms"]["DS"]["retrieved"] == (20, 20) and len(out["d"]["bothRetrieved"]) == 20
    raw = gdt.metrics(load_cases(), [r for r in d["rows"] if r["arm"] == "D0"],
                      {r["id"] for r in d["rows"]})
    assert raw["procedureCited"] == (16, 20), "짝 없이 세면 R13~R16 이 빠진다"
    assert row_of(g, "G7", "GS")["citations"][0]["title"] == NEW, "기록은 그대로다"

    # 앞 실행과의 견줌 — 아홉 짝으로 옮겨 근거 문서 집합을 견준다
    g, d = fresh(base)
    renamed = "오케스트레이션 — 세 계층과 자원 소유"
    row_of(g, "G1", "GS")["diagnostics"]["evidenceDocs"].append(renamed)
    reference = {"g": {("GS", "G1"): {"SOP-01 파지 실패와 잔여 파지 처리", "오케스트레이션 — 세 층과 자원 소유"},
                       ("G0", "G1"): {"다른 문서"}, ("GS", "G4"): {OLD}},
                 "d": {("DS", "R13"): {OLD}, ("D0", "R13"): {GLOSSARY}}}
    out = st.tally([g, d], reference=reference)
    assert out["g"]["reference"] == ["G1 G0"] and out["d"]["reference"] == ["R13 D0"]
    assert st.tally([g, d])["g"]["reference"] is None
    ref = st._reference()
    assert set(ref) == {"g", "d"} and ("GS", "G1") in ref["g"] and ("G0", "G1") in ref["g"]
    assert ("DS", "R01") in ref["d"] and ("D0", "R01") in ref["d"] and not any(arm in ("G3", "D3") for arm, _ in ref["g"])


# ── 8. 판정 ──

def test_verdict(tmp_path, base):
    """경로마다 성립 · 가드레일 지표 · 1차 결과 변수(설명 경로 GS ≥ G0, 진단 경로 DS ≥ D0 − 1)로 승격을 정하고, 두 경로가 다 승격되어야
    운영 질의 변경을 사전 등록할 후보다."""
    assert st.primary("g", {"procedureDoc": (7, 10)}, {"procedureDoc": (7, 10)}) is True
    assert st.primary("g", {"procedureDoc": (7, 10)}, {"procedureDoc": (6, 10)}) is False, "설명 경로는 여유가 없다"
    assert st.primary("d", {"procedureCited": (19, 20)}, {"procedureCited": (18, 20)}) is True, "진단 경로는 한 칸"
    assert st.primary("d", {"procedureCited": (19, 20)}, {"procedureCited": (17, 20)}) is False
    assert st.verdict({"advance": True}, {"advance": True}) == st.CANDIDATE == "운영 질의 변경을 사전 등록할 후보"
    for g_adv, d_adv in ((True, False), (False, True), (False, False)):
        assert st.verdict({"advance": g_adv}, {"advance": d_adv}) == st.KEEP == "운영 질의 그대로"
    assert st.verdict({"comparable": "빠진 줄이 있다"}, {"advance": True}) == st.KEEP

    g, d = fresh(base)
    out = st.tally([g, d])
    assert out["g"]["advance"] is True and out["d"]["advance"] is True and out["verdict"] == st.CANDIDATE
    assert all(out["g"]["guards"].values()) and len(out["g"]["guards"]) == 8
    assert all(out["d"]["guards"].values()) and len(out["d"]["guards"]) == 10
    lines = st.report_lines(out)
    assert lines[-1] == "판정 — 운영 질의 변경을 사전 등록할 후보"
    assert any(line.startswith("성립 — 1차 결과 변수 절차 문서 인용 G0 10/10 · GS 10/10") for line in lines)
    assert "승격 — GS" in lines and "승격 — DS" in lines

    unfinished = copy.deepcopy(g)
    unfinished["complete"] = False
    out = st.tally([unfinished, copy.deepcopy(d)])
    assert out["g"]["primary"] is True and all(out["g"]["guards"].values())
    assert out["g"]["advance"] is False and out["verdict"] == st.KEEP, "성립하지 않으면 지표가 좋아도 승격하지 않는다"
    assert "승격 — 판정 안 함" in st.report_lines(out)
    worse, _ = run_g(tmp_path, answer=g_answer(lose=("G1",)), file="g-lose")
    for row in worse["rows"]:
        if row["id"] == "G1":
            row["arm"] = {"G0": "GS", "GS": "G0"}[row["arm"]]
    out = st.tally([worse, copy.deepcopy(d)])
    assert out["g"]["arms"]["GS"]["procedureDoc"] == (9, 10) and out["g"]["primary"] is False
    assert out["g"]["comparable"] == "처치가 계획과 다르다", "실험군을 바꿔 적으면 처치가 깨진다"
    lose, _ = run_g(tmp_path, answer=lambda eid, arm, body, n: g_answer(lose=("G1",))(eid, "G0" if arm == "GS" else "GS", body, n),
                    file="g-lose2")
    out = st.tally([lose, copy.deepcopy(d)])
    assert out["g"]["comparable"] is None and out["g"]["primary"] is False and out["g"]["advance"] is False
    assert all(out["g"]["guards"].values()) and out["d"]["advance"] is True and out["verdict"] == st.KEEP
    assert st.report_lines(out)[-1] == "판정 — 운영 질의 그대로" and "승격 — 없음" in st.report_lines(out)
    gain, _ = run_g(tmp_path, answer=g_answer(lose=("G1", "G6")), file="g-gain")
    out = st.tally([gain, copy.deepcopy(d)])
    assert out["g"]["arms"]["GS"]["procedureDoc"][0] == out["g"]["arms"]["G0"]["procedureDoc"][0] + 2
    assert out["g"]["advance"] is True and out["verdict"] == st.CANDIDATE

    def ds_loses(*cids):
        def answer(cid, arm, body, n):
            if arm == "DS" and cid in cids:
                return d_data(doc=GLOSSARY, evidence=[GLOSSARY])
            return d_data(doc=procedure(cid))
        return answer

    one, _ = run_d(tmp_path, answer=ds_loses("R04"), file="d-one")
    out = st.tally([copy.deepcopy(g), one])
    assert out["d"]["arms"]["DS"]["procedureCited"] == (19, 20) and out["d"]["primary"] is True
    assert out["d"]["advance"] is True and out["verdict"] == st.CANDIDATE, "한 칸은 봐 준다"
    two, _ = run_d(tmp_path, answer=ds_loses("R04", "R05"), file="d-two")
    out = st.tally([copy.deepcopy(g), two])
    assert out["d"]["primary"] is False and out["d"]["advance"] is False and out["verdict"] == st.KEEP

    def forbidden(cid, arm, body, n):
        return d_data(pick="A" if (arm, cid) == ("DS", "R01") else "ESCALATE", doc=procedure(cid))

    bad, _ = run_d(tmp_path, answer=forbidden, file="d-bad")
    out = st.tally([copy.deepcopy(g), bad])
    assert out["d"]["guards"]["forbidden"] is False and out["d"]["comparable"] is None and out["d"]["advance"] is False

    def weak_split(eid, arm, body, n):
        data = g_answer()(eid, arm, body, n)
        if (eid, arm) == ("G2", "GS"):
            data = dict(data, weak_evidence=True)
        return data

    split, _ = run_g(tmp_path, answer=weak_split, file="g-weak")
    out = st.tally([split, copy.deepcopy(d)])
    assert out["g"]["weakSplit"] == ["G2"] and out["d"]["weakSplit"] == []
    item = next(i for i in out["g"]["items"] if i["id"] == "G2")
    assert item["GS"]["weak"] is True and item["G0"]["weak"] is False and item["GS"]["noEvidence"] is True
    assert item["GS"]["route"] == "hybrid_only" and item["GS"]["bm25"] == 2.5 and item["GS"]["distance"] == 0.3
    assert out["g"]["guards"]["cards"] is True and out["g"]["guards"]["uncited"] is True
    bothless = copy.deepcopy(split)
    row_of(bothless, "G7", "GS").update(outcome="GENERATION_FAILED", reason="exception:KeyError", answer="", citations=[],
                                         echo=None)
    out = st.tally([bothless, copy.deepcopy(d)])
    assert "G7" not in out["g"]["bothRetrieved"], "둘 다 받은 사건의 인용은 두 실험군이 다 답한 사건으로만 센다"
    assert out["g"]["arms"]["G0"]["citedWhenBoth"] == out["g"]["arms"]["GS"]["citedWhenBoth"] == (9, 9)
