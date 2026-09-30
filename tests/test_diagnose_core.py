"""진단 한 번 — 계약 0.6 전체를 잇는 자리. khala 는 가짜 전송으로 흉내 낸다."""

import contextlib
import sqlite3
import threading
import time

import pytest

from composer.query import compose, compose_search
from diagnose.context import render
from diagnose.contract import RESPONSE_KEYS
from diagnose.core import GATE_WAIT, Cancelled, diagnose, drain
from diagnose.judge import DiagnoseFailed
from diagnose.store import Busy, Claimed, Done, FirstResultStore
from explainer.client import INCIDENT_EXCLUDED, nexus_client
from receiver.export import read_export

KEY = ("ep-1", 1, "sha256:" + "0" * 64)


def _khala(data, hold=None, on_call=None):
    """`(client, sent)` — `client(answer_context)` 가 설명 경로의 `nexus_client` 를 가짜 전송으로 만든다.
    [hold] 를 주면 전송이 그 사건이 설 때까지 멈춘다(khala 가 생성 중인 흉내). [on_call] 은 부를 때마다 부른다."""
    sent = []

    def transport(method, url, headers, body):
        sent.append(body)
        if on_call is not None:
            on_call()
        if hold is not None:
            hold.wait(5)
        return 200, {"success": True, "data": data}

    def client(answer_context):
        return nexus_client("http://x", token="t", tenant="picasso", transport=transport,
                            exclude_doc_types=INCIDENT_EXCLUDED, identifier_channel=True,
                            answer_context=answer_context)

    return client, sent


def _holder(store):
    """지금 열쇠를 쥔 쪽 — 시험만 쓰는 엿보기."""
    with contextlib.closing(sqlite3.connect(store.path)) as db:
        return db.execute("SELECT owner FROM first_result").fetchone()[0]


class _Gate:
    """동시 한도의 문 흉내 — 드나듦을 적는다. [free] 가 거짓이면 기다려도 안 열린다."""

    def __init__(self, free=True):
        self.log = []
        self.free = free

    def acquire(self, timeout=None):
        self.log.append(("acquire", timeout))
        return self.free

    def release(self):
        self.log.append("release")


def test_권고_한_번(tmp_path, export_dir, diagnose_request, khala_data):
    """질의는 설명 경로의 조립 그대로(사건 첫째 + 탐색 첫째, 재발 수 없음), 자료 칸은 따로 간다.
    khala 는 한 번, 동시 한도의 문 안에서만 불린다. 응답의 칸은 계약 §4 의 순서 그대로다.
    판 칸의 빈 글자 · 공백만인 글자 · 글자가 아닌 값은 모름이라 `null` 로 옮긴다(koshei 는 판 칸이 `null` 이거나
    공백만이 아닌 글자이기를 본다)."""
    export = read_export(export_dir("run-1"))
    incident = next(b for b in export.incidents if b["incidentId"] == "incident-1")
    search = next(s for s in export.searches if s["searchId"] == "search-1")
    payload = diagnose_request(snapshot={"manifest": export.manifest, "incidents": [incident],
                                         "searches": [search]})
    gate = _Gate()
    beats = []
    client, sent = _khala(khala_data(), on_call=lambda: gate.log.append("call"))

    response = diagnose(payload, client=client, store=FirstResultStore(tmp_path / "f.sqlite3"),
                        commit="abc1234", gate=gate, beat=lambda: beats.append(1), clock=lambda: 0.0,
                        poll=0.01)

    assert len(sent) == 1 and gate.log == [("acquire", GATE_WAIT), "call", "release"], "khala 는 문 안에서만"
    assert beats, "잡자마자 한 번은 알린다"
    assert sent[0]["query"] == compose(incident, search).text
    assert sent[0]["answer_context"] == render(payload["candidates"], [], [])
    assert list(response) == list(RESPONSE_KEYS)
    assert response["outcome"] == "RECOMMENDED"
    assert response["candidateId"] == "APPROVE_REMEDY:hum-02:PATROL-1:pick_place"
    assert response["sawCandidatesVersion"] == payload["candidatesVersion"]
    assert response["rationale"].startswith("탐색이 찾은 조치의 전제가 관측과 맞는다")
    assert [item["label"] for item in response["card"]] == ["절차", "먼저", "금지", "갈림", "근거 세기"]
    assert response["cause"] == "## 원인 후보\n후보 ① — 파지물 낙하."
    assert response["uncitedSentences"] == [] and response["unverifiedClaims"] == []
    assert response["versions"] == {"modelId": "claude-sonnet-5", "promptVersion": None,
                                    "corpusVersion": None, "searchFingerprint": None,
                                    "narratorCommit": "abc1234"}
    blank, _ = _khala(khala_data(prompt_version="", corpus_version=" ", search_fingerprint=0,
                                 usage={"model": "\n"}))
    other = diagnose(diagnose_request(episodeId="ep-2", snapshot=payload["snapshot"]), client=blank,
                     store=FirstResultStore(tmp_path / "f.sqlite3"), commit="abc1234", clock=lambda: 0.0, poll=0.01)
    assert other["versions"] == {"modelId": None, "promptVersion": None, "corpusVersion": None,
                                 "searchFingerprint": None, "narratorCommit": "abc1234"}, "빈 글자 · 공백 · 글자 아님은 null"


def test_같은_열쇠의_두번째_요청은_khala_를_부르지_않는다(tmp_path, diagnose_request, khala_data):
    """판 칸은 「배포 없이 판단이 안 바뀐다」를 보증하지 못한다 — 막는 것은 첫 결과 저장소다."""
    store = FirstResultStore(tmp_path / "f.sqlite3")
    client, sent = _khala(khala_data())

    first = diagnose(diagnose_request(), client=client, store=store, commit="c", poll=0.01)
    second = diagnose(diagnose_request(), client=client, store=store, commit="c", poll=0.01)

    assert len(sent) == 1
    assert second == first


def test_남이_묻는_중이면_기다렸다_그_결과를_받는다(tmp_path, diagnose_request, khala_data):
    """같은 열쇠가 동시에 두 번 오면 먼저 잡은 쪽만 khala 를 부른다. 기다리는 동안에도 하트비트를 보낸다."""
    store = FirstResultStore(tmp_path / "f.sqlite3")
    store.claim(KEY, "other", now=0.0)
    theirs = {"outcome": "UNCITED"}
    beats = []

    def sleep(seconds):  # 기다리는 사이 남이 끝낸다
        store.complete(KEY, theirs, raw_pick=None, resolved_pick=None, now=1.0)

    client, sent = _khala(khala_data())
    response = diagnose(diagnose_request(), client=client, store=store, commit="c",
                        beat=lambda: beats.append(1), clock=lambda: 1.0, sleep=sleep, poll=0.01)

    assert response == theirs
    assert sent == [] and beats == [1]


def test_문이_안_열리면_브리지_혼잡으로_재시도할_예외다(tmp_path, diagnose_request, khala_data):
    """**문을 기다리는 것도 StartToClose 안이다.** 사슬(420 → 450 → 510 → 540)은 khala 호출이 곧바로 시작된다고
    잡았으므로, 문 앞에서 오래 서면 시도가 기한을 넘겨 버려지고 그 시도가 또 문을 쥔 곁 스레드가 된다(koshei 지적).
    그래서 [GATE_WAIT] 초만 기다리고, 넘으면 브리지 혼잡(`unavailable`)으로 돌려 기다림을 Temporal 큐
    (ScheduleToClose)로 넘긴다. khala 는 안 불리고 잡은 것은 놓는다."""
    store = FirstResultStore(tmp_path / "f.sqlite3")
    client, sent = _khala(khala_data())
    gate = _Gate(free=False)

    with pytest.raises(DiagnoseFailed) as raised:
        diagnose(diagnose_request(), client=client, store=store, commit="c", gate=gate, clock=lambda: 0.0,
                 poll=0.01)

    assert GATE_WAIT == 20.0
    assert (raised.value.reason, raised.value.retryable) == ("unavailable", True)
    assert sent == [] and gate.log == [("acquire", GATE_WAIT)], "못 연 문은 닫지 않는다"
    assert store.claim(KEY, "next", now=0.0) == Claimed("next")


def test_생성_실패는_잡은_것을_놓고_예외로_올린다(tmp_path, diagnose_request, khala_data):
    """재시도의 주인은 Temporal 이다. 놓아 두면 다음 시도가 임대를 기다리지 않고 바로 잡는다."""
    store = FirstResultStore(tmp_path / "f.sqlite3")
    client, _ = _khala(khala_data(llm_failed=True, llm_failure_reason="timeout", answer=""))

    with pytest.raises(DiagnoseFailed) as raised:
        diagnose(diagnose_request(), client=client, store=store, commit="c", poll=0.01)

    assert raised.value.retryable is True
    assert store.claim(KEY, "next", now=0.0) == Claimed("next")


def test_취소돼도_잡은_것을_놓지_않고_곁_스레드가_끝낸다(tmp_path, diagnose_request, khala_data):
    """**같은 열쇠에 khala 는 한 번이다**(계약 §6). 취소는 대개 Temporal 이 이미 시간을 넘긴 시도를 버리고
    다시 보낼 때 온다. 그때 잡은 것을 놓으면 다시 온 요청이 khala 를 또 부르고, 버려진 곁 스레드는 여전히
    브리지 자리를 문다. 그래서 놓지 않는다 — 곁 스레드가 끝내 결과를 적고, 그동안 임대를 붙든다."""
    store = FirstResultStore(tmp_path / "f.sqlite3", lease=0.3)
    generating = threading.Event()
    client, sent = _khala(khala_data(), hold=generating)

    with pytest.raises(Cancelled):
        diagnose(diagnose_request(), client=client, store=store, commit="c",
                 cancelled=lambda: bool(sent), poll=0.01)
    time.sleep(0.6)  # 임대(0.3초)의 두 배 — 붙드는 고리가 없으면 이 사이에 임대가 끝난다
    holder = _holder(store)
    assert holder != "retry"
    assert store.claim(KEY, "retry", now=time.time()) == Busy(holder), "취소돼도 잡은 것을 쥐고 있다"

    assert drain(timeout=0.05) is False, "곁 스레드는 아직 khala 를 기다린다"
    generating.set()
    deadline = time.time() + 5
    state = store.claim(KEY, "retry", now=time.time())
    while not isinstance(state, Done) and time.time() < deadline:
        time.sleep(0.01)
        state = store.claim(KEY, "retry", now=time.time())
    assert isinstance(state, Done) and state.response["outcome"] == "RECOMMENDED"
    assert len(sent) == 1
    assert drain(timeout=5) is True, "답을 적고 끝났다"


def test_기다리다_잡은_시도는_늦었거나_취소됐으면_khala_를_부르지_않는다(tmp_path, diagnose_request, khala_data):
    """**잡기를 기다린 시간도 문 몫(20초)에 든다**(계약 §2). 앞 시도가 죽어 임대가 끝난 뒤에야 잡았는데 이미
    20초가 지났으면, 지금 khala 를 시작해도 이 시도는 기한을 넘겨 버려진다 — 놓고 브리지 혼잡으로 돌려보낸다.
    기다리는 사이 취소됐으면 잡았어도 부르지 않는다(묶음 4 검토)."""
    client, sent = _khala(khala_data())

    late = FirstResultStore(tmp_path / "late.sqlite3")
    late.claim(KEY, "dead", now=0.0)
    times = iter([0.0, 0.0, 31.0, 31.0])  # 시작 · 첫 잡기(남이 쥠) · 임대가 끝난 뒤 잡기 · 기다린 시간
    with pytest.raises(DiagnoseFailed) as raised:
        diagnose(diagnose_request(), client=client, store=late, commit="c",
                 clock=lambda: next(times), sleep=lambda seconds: None, poll=0.01)
    assert (raised.value.reason, raised.value.retryable) == ("unavailable", True)
    assert late.claim(KEY, "next", now=32.0) == Claimed("next"), "늦게 잡은 것은 놓는다"

    cancelled = FirstResultStore(tmp_path / "cancelled.sqlite3")
    cancelled.claim(KEY, "dead", now=0.0)
    times = iter([0.0, 0.0, 31.0, 31.0])
    flags = iter([False, True])  # 기다리는 동안은 아니다가, 잡고 보니 취소됐다
    with pytest.raises(Cancelled):
        diagnose(diagnose_request(), client=client, store=cancelled, commit="c", cancelled=lambda: next(flags),
                 clock=lambda: next(times), sleep=lambda seconds: None, poll=0.01)
    assert cancelled.claim(KEY, "next", now=32.0) == Claimed("next")
    assert sent == []


def test_사건_줄이_없으면_탐색_줄_그_자체로_묻는다(tmp_path, export_dir, diagnose_request, khala_data):
    """근거 없음 · 후보 밖 예제의 모양 — 에피소드를 연 것이 탐색 줄이다(계약 §3 「질의의 주체」)."""
    export = read_export(export_dir("run-1"))
    search = next(s for s in export.searches if s["searchId"] == "search-4")
    payload = diagnose_request(snapshot={"manifest": export.manifest, "incidents": [],
                                         "searches": [search]})
    client, sent = _khala(khala_data(
        answer="권고: A\n이유:\n절차: 먼저 본다 [출처: SOP-02 안착 실패와 품번 불일치, §5]."))

    response = diagnose(payload, client=client, store=FirstResultStore(tmp_path / "f.sqlite3"), commit="c",
                        poll=0.01)

    assert sent[0]["query"] == compose_search(search).text
    assert response["rationale"] is None and response["uncitedSentences"] == [], \
        "빈 「이유:」 줄은 이유를 안 댄 것이다 — 빈 글자로 적지 않는다"
