"""운영 검색 텍스트 — 설계서 `docs/superpowers/specs/2026-10-07-운영-검색-텍스트.md`.

운영 경로 둘(수신기 파이프라인 · 진단 워커)이 khala 에 보내는 본문에 `search_text` = Q3 을 싣는다. 이 변경의 증거는 새 측정이
아니라 「운영이 보내는 것이 측정이 보낸 것과 같다」는 같음이다(설계서 §1 · §7). 측정 코드(`eval/`)는 여기 시험에서만 가져다 쓰고
운영 코드는 가져다 쓰지 않는다.

⚠ **`temporalio` 가 없어도 돈다.** 워커 모듈은 가져오는 자리에서 `temporalio` 를 부르므로, 없으면 이 파일이 쓰는 이름만 가진
흉내 모듈을 시험 동안만 끼운다. 워커의 `main` 은 흉내든 실물이든 `Client` · `Worker` 를 바꿔 끼워 실제 서비스 없이 부른다.
"""

import asyncio
import hashlib
import importlib
import json
import pathlib
import sys
import types

import pytest

from composer.query import ASK, LOOKUP, Query, compose, compose_search
from diagnose.contract import parse_request
from diagnose.core import diagnose, run_diagnosis
from diagnose.judge import DiagnoseFailed
from diagnose.store import FirstResultStore
from eval import ask_trial as at
from eval import query_trial as qt
from eval import recommend as rec
from eval import recommend_score as rs
from eval.run import fixture_history, load, query_for
from eval.score import QUERY
from eval.st_trial import body_sha
from explainer.ask import ask_once
from explainer.client import INCIDENT_EXCLUDED, nexus_client
from receiver import cli
from receiver.history import count_recurrence
from receiver.pipeline import ask_and_record, explain
from receiver.scan import scan
from recorder.store import RecordStore

ROOT = pathlib.Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "eval" / "goldenset.json"
EXPORTS = ROOT / "tests" / "fixtures" / "picasso"
#: 운영 수신기 본문을 견주는 설명 경로 아홉(설계서 §1) — 탐색 쌍이 없어 운영이 같은 질의를 짓는 것.
OPERATIONAL_G = ("G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "S1")
#: 탐색 쌍이 있어 운영이 본문을 짓지 않는 셋 — Q3 짓기 함수 수준에서만 견준다.
PAIRED_G = ("G1", "G10", "G11")
MISSING = object()


def _sha(text):
    return None if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()


def _rows(name):
    """측정 기록 한 벌의 줄 — `(항목, 실험군) -> 줄`."""
    record = json.loads((ROOT / "eval" / "st" / name).read_text(encoding="utf-8"))
    assert record["complete"] is True
    return {(row["id"], row["arm"]): row for row in record["rows"]}


def _capture(sent, answer=(500, {"detail": "가짜"})):
    """보낸 본문을 적는 가짜 전송. 기본 답은 실패라 진단이 생성 실패로 끝난다 — 본문만 본다."""

    def transport(method, url, headers, body):
        sent.append(body)
        return answer

    return transport


def _built_body(query, search_text, **kwargs):
    """측정 코드의 짓기 — 운영 클라이언트가 지은 본문에 전송 자리에서 `search_text` 하나를 더한다(`eval/st_trial.py`)."""
    sent = []
    nexus_client("http://x", "t", rec.TENANT, _capture(sent), **kwargs)(query)
    return dict(sent[0], search_text=search_text) if search_text else dict(sent[0])


def _fields(left, right):
    """두 본문에서 다른 칸."""
    return sorted(key for key in set(left) | set(right) if left.get(key, MISSING) != right.get(key, MISSING))


def _stub_temporalio(monkeypatch):
    """워커 모듈이 가져오는 `temporalio` 이름만 가진 흉내 — 실물이 없을 때만 시험 동안 끼운다."""

    class _Failure(Exception):
        def __init__(self, message="", *args, **kwargs):
            super().__init__(message)

    package = types.ModuleType("temporalio")
    activity = types.ModuleType("temporalio.activity")
    activity.defn = lambda **kwargs: (lambda fn: fn)
    activity.heartbeat = lambda *args: None
    activity.is_cancelled = lambda: False
    activity.logger = types.SimpleNamespace(warning=lambda *args, **kwargs: None)
    client = types.ModuleType("temporalio.client")
    client.Client = type("Client", (), {})
    exceptions = types.ModuleType("temporalio.exceptions")
    exceptions.ApplicationError = type("ApplicationError", (_Failure,), {})
    exceptions.CancelledError = type("CancelledError", (_Failure,), {})
    worker = types.ModuleType("temporalio.worker")
    worker.Worker = type("Worker", (), {})
    package.activity = activity
    for name, module in (("temporalio", package), ("temporalio.activity", activity), ("temporalio.client", client),
                         ("temporalio.exceptions", exceptions), ("temporalio.worker", worker)):
        monkeypatch.setitem(sys.modules, name, module)


def _worker(monkeypatch):
    """`diagnose.worker` — `temporalio` 가 없으면 흉내를 끼우고 가져와 시험이 끝나면 둘 다 뺀다."""
    try:
        importlib.import_module("temporalio")
    except ImportError:
        _stub_temporalio(monkeypatch)
        # 자리를 먼저 잡아 시험이 끝나면 지금 상태(없음)로 돌아가게 한다 — 흉내로 가져온 워커가 남지 않는다.
        monkeypatch.setitem(sys.modules, "diagnose.worker", None)
        monkeypatch.setattr(sys.modules["diagnose"], "worker", None, raising=False)
        del sys.modules["diagnose.worker"]
        return importlib.import_module("diagnose.worker")
    return importlib.import_module("diagnose.worker")


def _cases():
    """권고 측정기의 사례 스물하나(반복 R02 뺌) — `eval/recommend.py` 의 `prepare`."""
    return [prep for prep in rec.prepare(rs.load_cases()) if not prep["case"]["repeatOf"]]


def _diagnosis_body(prep, client, search_text):
    """`run_diagnosis` 한 번이 보낸 본문 — 가짜 전송이 실패로 답하므로 생성 실패로 끝난다."""
    sent = []
    with pytest.raises(DiagnoseFailed):
        run_diagnosis(prep["request"], client(sent), "c", **({"search_text": True} if search_text else {}))
    assert len(sent) == 1
    return sent[0]


def test_q3_matches_measurement():
    """`Query.search_text` 가 측정 코드의 Q3(`eval/ask_trial.py` 의 `texts(query)["Q3"]`)와 바이트까지 같고, 측정 기록의 GS · DS 줄이 보낸
    `search_text` 의 sha256 과 같다. 골든셋 열다섯과 권고 사례 스물하나, 서른여섯이다. 질의 줄은 글자 그대로라 키가 없다."""
    built = qt.queries(rs.load_cases(), golden=GOLDEN)
    g, d = _rows("g-1.json"), _rows("d-1.json")
    assert len(built) == 36
    for cid, query in built.items():
        row = g[(cid, "GS")] if (cid, "GS") in g else d[(cid, "DS")]
        if isinstance(query, str):
            assert row["sentSearchTextSha256"][-1] is None, cid
            continue
        mine = query.search_text
        assert mine == at.texts(query)["Q3"], cid
        assert _sha(mine) == row["sentSearchTextSha256"][-1] == row["planSearchTextSha256"], cid
    assert all(isinstance(built[cid], Query) for cid in PAIRED_G)


def test_q3_branches(monkeypatch):
    """Q3 짓기의 갈래 넷 — 식별자 토큰 12개 초과, 조회 지시가 붙는 경우, 토큰을 앞에 안 세우는 갈래(q2 = q1), 빈 Q3. 갈래마다 측정
    코드와도 견준다. 빈 Q3 은 예외 없이 빈 글이고 클라이언트는 키를 안 보낸다."""
    # 1. 식별자 토큰 12개 초과 — 겹친 사실에만 든 토큰은 앞에 세우되 열둘까지다. 스칼라 사실은 그 뒤에 그대로 간다.
    many = [f"TOKEN_{i:02d}" for i in range(1, 15)]
    query = Query(facts={"robotId": "hum-02", "trail": many, "step": 3})
    assert query.search_text == " ".join(many[:12]) + " robotId=hum-02 step=3"
    assert "TOKEN_13" not in query.search_text
    assert query.search_text == at.texts(query)["Q3"]
    # 스칼라 사실이 없으면 토큰만 간다 — 빈 조각을 잇지 않는다.
    alone = Query(facts={"trail": many[:2]})
    assert alone.search_text == "TOKEN_01 TOKEN_02"
    assert alone.search_text == at.texts(alone)["Q3"]

    # 2. 조회 지시가 붙는 경우 — 맨 앞에 남는다. 토큰 차례가 같으면 앞에 안 세우고, 다르면 지시 뒤에 세운다.
    lookup = LOOKUP.format(code="X_FIXTURE_E4412")
    same = Query(facts={"failureClass": "UNCLASSIFIED", "fault": {"vendorDetail": "X_FIXTURE_E4412"}}, lookup=lookup)
    assert same.search_text == lookup + "failureClass=UNCLASSIFIED"
    assert same.search_text == at.texts(same)["Q3"]
    apart = Query(facts={"failureClass": "UNCLASSIFIED", "fault": {"vendorDetail": "X_FIXTURE_E4412"},
                         "blockedBy": ["PAYLOAD_LOST"]}, lookup=lookup)
    assert apart.search_text == lookup + "X_FIXTURE_E4412 PAYLOAD_LOST failureClass=UNCLASSIFIED"
    assert apart.search_text == at.texts(apart)["Q3"]
    # 조회 지시만 있는 경우 — 지시의 끝 빈칸까지 그대로 간다.
    only = Query(facts={"fault": {"vendorDetail": "X_FIXTURE_E4412"}}, lookup=lookup)
    assert only.search_text == lookup
    assert only.search_text == at.texts(only)["Q3"]

    # 3. 토큰을 앞에 안 세우는 갈래 — 스칼라 사실만으로 토큰 차례가 Q0 와 같다. 고정 질문은 빠지고 널 · 참거짓은 Q0 와 같이 적는다.
    scalar = Query(facts={"failureClass": "PAYLOAD_LOST", "robotId": "hum-02", "windowTruncated": False,
                          "verification": None})
    assert scalar.search_text == "failureClass=PAYLOAD_LOST robotId=hum-02 windowTruncated=false verification=모름"
    assert ASK not in scalar.search_text
    assert scalar.search_text == at.texts(scalar)["Q3"]
    # 토큰이 겹친 사실에만 있으면 차례가 달라져 앞에 세운다 — 같은 사실을 겹친 칸에 두었을 뿐인데 갈래가 갈린다.
    # 글자에 붙은 토큰은 토큰이 아니다(정규식의 낱말 경계) — 한글이나 소문자 바로 뒤의 대문자 열은 안 뽑는다.
    nested = Query(facts={"robotId": "hum-02", "fault": {"class": "PAYLOAD_LOST", "note": "코드X_FIXTURE_E4412 xNO_CAPABILITY"}})
    assert nested.search_text == "PAYLOAD_LOST robotId=hum-02"
    assert nested.search_text == at.texts(nested)["Q3"]
    # 갈래는 고정 질문까지 든 글의 토큰으로 가른다(측정 함수와 같음) — 질문에 토큰이 들어서도 측정 함수와 같은 갈래로 간다.
    asked = ASK + "ASK_TOKEN "
    for module in (sys.modules["composer.query"], qt, at):
        monkeypatch.setattr(module, "ASK", asked)
    plain = Query(facts={"failureClass": "PAYLOAD_LOST"})
    assert plain.search_text == "failureClass=PAYLOAD_LOST"
    assert plain.search_text == at.texts(plain)["Q3"]
    monkeypatch.undo()

    # 4. 빈 Q3 — 조회 지시도 토큰도 스칼라 사실도 없다. 예외 없이 빈 글이고 클라이언트는 키를 안 보낸다.
    empty = Query(facts={"fault": {"detail": "x"}})
    assert empty.search_text == ""
    with pytest.raises(ValueError):
        at.texts(empty)  # 측정 코드는 짓는 자리에서 막는다 — 운영은 막지 않고 키를 안 보낸다
    assert Query(facts={}).search_text == ""
    sent = []
    nexus_client("http://x", "t", "picasso", _capture(sent))(empty.text, search_text=empty.search_text)
    assert "search_text" not in sent[0]
    seen = []

    def strict(query):  # 인자 하나짜리 — 빈 Q3 이면 이렇게 불린다
        seen.append(query)
        return 200, {"success": True, "data": {"llm_failed": False, "citations": []}}

    ask_and_record(("k",), empty.text, strict, 1, search_text=empty.search_text)
    assert seen == [empty.text]


def test_operational_bodies_equal_measurement(monkeypatch, tmp_path, nexus):
    """운영이 보내는 본문이 측정이 보낸 본문과 같다(설계서 §1). 본문 해시의 직렬화는 측정과 같다(`eval/st_trial.py` 의 `body_sha`).

    - 설명 경로 아홉 — 운영 수신기(`receiver.cli.run` → `once` → `explain` → `_one`)가 지은 본문이 `eval/st/g-1.json` GS 줄 본문
      해시와 같다. 재발 횟수는 측정과 같이 픽스처 이력으로 센다(저장소가 본 주체에 픽스처 이력을 더한다)
    - 진단 경로 스물하나 — `run_diagnosis`(켬)를 권고 측정기 클라이언트(`eval.recommend.client_for`)로 부른 본문이 `eval/st/d-1.json`
      DS 줄 본문 해시와 같다. 워커 클라이언트(`make_client`)로 부른 본문은 그 본문과 `exclude_doc_types` 의 `case` 하나만 다르다
    - 어긋나면 측정 코드로 다시 지은 본문과의 칸 차이를 보인다
    """
    g, d = _rows("g-1.json"), _rows("d-1.json")
    history = fixture_history()

    class Seen(RecordStore):
        """운영 저장소 — 본 주체에 픽스처 이력을 더한다(측정의 재발 세기)."""

        def subjects(self):
            return history + super().subjects()

    monkeypatch.setattr(cli, "RecordStore", Seen)
    operational = []
    for run in sorted(EXPORTS.glob("run-*")):
        sent = []
        args = cli.build_parser().parse_args([str(run), "--out", str(tmp_path / run.name), "--token", "t"])
        cli.run(args, transport=_capture(sent, nexus("05-answer-with-citations")))
        batch = scan(run, set())
        items = list(batch.incidents) + list(batch.searches)
        assert len(sent) == len(items), run.name
        operational += list(zip(items, sent))

    built = qt.queries(golden=GOLDEN)
    entries = {entry["id"]: entry for entry in load(str(GOLDEN))}
    for gid in OPERATIONAL_G:
        entry = entries[gid]
        target = entry["search"] if entry["kind"] == "search" else entry["bundle"]
        assert "search" not in entry or entry["kind"] == "search", gid
        bodies = [body for item, body in operational if item == target]
        assert bodies, f"{gid}: 운영 수신기가 그 번들을 안 지었다"
        recorded = g[(gid, "GS")]["sentBodySha256"][-1]
        reference = _built_body(query_for(entry, prior=history), at.texts(built[gid])["Q3"],
                                exclude_doc_types=INCIDENT_EXCLUDED, identifier_channel=True)
        assert body_sha(reference) == recorded, f"{gid}: 측정 코드가 기록을 재현하지 못한다"
        for body in bodies:
            assert body_sha(body) == recorded, f"{gid}: 다른 칸 {_fields(body, reference)}"

    worker = _worker(monkeypatch)
    doc_built = qt.queries(rs.load_cases())
    cases = _cases()
    assert len(cases) == 21
    for prep in cases:
        cid = prep["case"]["id"]
        recorded = d[(cid, "DS")]["sentBodySha256"][-1]
        reference = _built_body(prep["query"], at.texts(doc_built[cid])["Q3"], exclude_doc_types=rec.EXCLUDE,
                                identifier_channel=True, answer_context=prep["context"])
        assert body_sha(reference) == recorded, f"{cid}: 측정 코드가 기록을 재현하지 못한다"
        measured = _diagnosis_body(prep, lambda sent: rec.client_for("http://x", "t", transport=_capture(sent)), True)
        assert body_sha(measured) == recorded, f"{cid}: 다른 칸 {_fields(measured, reference)}"
        mine = _diagnosis_body(prep, lambda sent: worker.make_client("http://x", "t", "picasso", _capture(sent)), True)
        assert _fields(mine, measured) == ["exclude_doc_types"], cid
        assert mine["exclude_doc_types"] == list(INCIDENT_EXCLUDED)
        assert mine["exclude_doc_types"] + ["case"] == measured["exclude_doc_types"] == list(rec.EXCLUDE)
        assert body_sha(dict(mine, exclude_doc_types=list(rec.EXCLUDE))) == recorded, cid


def test_default_off_paths(monkeypatch, tmp_path, export_dir, diagnose_request, nexus):
    """기본값은 꺼짐이다 — `nexus_client` 의 `search` 를 인자 하나로 부르거나 `ask_once` · `ask_and_record` · `run_diagnosis` ·
    `diagnose` · `make_activity` 를 기본값으로 부르면 `search_text` 키가 없고, 인자 하나짜리 가짜 `search` 도 그대로 불린다. 켜는
    자리는 수신기 `_one` 과 워커 `main` 둘뿐이다(설계서 머리 MUST 4)."""
    # 클라이언트 — 인자 하나 · None · 빈 글이면 키가 없고, 글이 있을 때만 싣는다.
    sent = []
    search = nexus_client("http://x", "t", "picasso", _capture(sent))
    search("질의")
    search("질의", search_text=None)
    search("질의", search_text="")
    search("질의", search_text="X_FIXTURE_E4412")
    assert ["search_text" in body for body in sent] == [False, False, False, True]
    assert sent[3]["search_text"] == "X_FIXTURE_E4412"
    assert _fields(sent[0], sent[3]) == ["search_text"]

    # 묻기 — 기본값이면 인자 하나짜리 가짜를 인자 하나로 부르고, 글을 주면 키워드로 넘긴다.
    calls = []

    def strict(query):
        calls.append((query,))
        return nexus("05-answer-with-citations")

    def keyword(query, *, search_text=None):  # 키워드로만 받는다 — 넘기는 쪽이 이름으로 넘긴다
        calls.append((query, search_text))
        return nexus("05-answer-with-citations")

    ask_once("질의", strict)
    ask_once("질의", strict, search_text=None)
    ask_and_record(("k",), "질의", strict, 1)
    ask_and_record(("k",), "질의", strict, 1, search_text=None)
    ask_once("질의", keyword, search_text="Q3")
    ask_and_record(("k",), "질의", keyword, 1, search_text="Q3")
    assert calls == [("질의",)] * 4 + [("질의", "Q3")] * 2

    # 수신기 `_one` — 켬. 사건 · 조치 탐색 기록마다 그 질의의 Q3 을 넘긴다.
    batch = scan(export_dir("run-1"), set())
    passed = []

    def receiving(query, search_text=None):
        passed.append((query, search_text))
        return nexus("05-answer-with-citations")

    explain(batch, receiving, limit=1)
    history = list(batch.history)
    wanted = [compose(b, recurrence=count_recurrence(b, history)) for b in batch.incidents]
    wanted += [compose_search(s) for s in batch.searches]
    assert passed == [(q.text, q.search_text) for q in wanted]
    assert all(text for _, text in passed)

    # 진단 — `run_diagnosis` · `diagnose` 는 기본 꺼짐, 켜면 질의의 Q3 을 싣는다. 클라이언트는 워커의 것이다.
    worker = _worker(monkeypatch)
    export = scan(export_dir("run-1"), set())
    incident = next(b for b in export.incidents if b["incidentId"] == "incident-1")
    snapshot = {"manifest": export.manifest, "incidents": [incident], "searches": []}
    q3 = compose(incident).search_text
    request = parse_request(diagnose_request(snapshot=snapshot))
    bodies = []
    client = worker.make_client("http://x", "t", "picasso", _capture(bodies))
    for flag in (None, False, True):
        with pytest.raises(DiagnoseFailed):
            run_diagnosis(request, client, "c", **({} if flag is None else {"search_text": flag}))
    assert [body.get("search_text", MISSING) for body in bodies] == [MISSING, MISSING, q3]
    assert all(body["exclude_doc_types"] == list(INCIDENT_EXCLUDED) for body in bodies)
    bodies.clear()
    for n, flag in enumerate((None, True)):
        payload = diagnose_request(snapshot=snapshot, episodeId=f"ep-{n}")
        with pytest.raises(DiagnoseFailed):
            diagnose(payload, client=client, store=FirstResultStore(tmp_path / f"d{n}.sqlite3"), commit="c", poll=0.01,
                     **({} if flag is None else {"search_text": flag}))
    assert [body.get("search_text", MISSING) for body in bodies] == [MISSING, q3]

    # 워커 — `make_activity` 는 기본 꺼짐, `main` 만 켠다. `main` 의 클라이언트는 `make_client` 로 지은 것이다.
    handed = []

    def fake_diagnose(payload, **kwargs):
        handed.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr(worker, "diagnose", fake_diagnose)
    worker.make_activity(client, "store", "c")({"x": 1})
    assert handed[-1]["search_text"] is False

    workers = []

    class Temporal:
        @staticmethod
        async def connect(*args, **kwargs):
            return "temporal"

    class FakeWorker:
        def __init__(self, client, **kwargs):
            workers.append(kwargs)

        async def run(self):
            return None

    bodies.clear()
    monkeypatch.setattr(worker, "Client", Temporal)
    monkeypatch.setattr(worker, "Worker", FakeWorker)
    monkeypatch.setattr(worker, "_commit", lambda: "c")
    monkeypatch.setattr(worker, "http_transport", _capture(bodies))
    monkeypatch.setenv("NEXUS_TOKEN", "t")
    monkeypatch.setenv("NARRATOR_DIAGNOSE_STORE", str(tmp_path / "main.sqlite3"))
    asyncio.run(worker.main())
    activity, = workers[0]["activities"]
    activity({"x": 1})
    turned = handed[-1]
    assert turned["search_text"] is True
    with pytest.raises(DiagnoseFailed):
        run_diagnosis(request, turned["client"], "c", search_text=turned["search_text"])
    body, = bodies
    assert body["search_text"] == q3
    assert body["exclude_doc_types"] == list(INCIDENT_EXCLUDED)
    assert body["tenant"] == "picasso" and body["identifier_channel"] is True
