"""Temporal 액티비티 — 계약 0.6 §2 · §5. 예외의 모양이 재시도를 정한다."""

import subprocess
import threading
import time
import typing

import pytest

temporalio = pytest.importorskip("temporalio")

from temporalio.exceptions import ApplicationError, CancelledError  # noqa: E402
from temporalio.testing import ActivityEnvironment  # noqa: E402

import diagnose.worker as worker  # noqa: E402
from diagnose.contract import parse_request  # noqa: E402
from diagnose.core import GATE_WAIT, drain  # noqa: E402
from diagnose.store import Done, FirstResultStore  # noqa: E402
from explainer.client import nexus_client  # noqa: E402


def _client(data=None, error=None, hold=None, on_call=None):
    """`client(answer_context)` — 설명 경로의 `nexus_client` 를 가짜 전송으로 만든다. [on_call] 은 부를 때마다 부르고,
    [hold] 를 주면 전송이 그 사건이 설 때까지 멈춘다(khala 가 생성 중인 흉내). 길어야 1초다 — 기본 주기(2초)로 도는
    하트비트는 그 안에 세 번을 못 채운다."""

    def transport(method, url, headers, body):
        if on_call is not None:
            on_call()
        if hold is not None:
            hold.wait(1)
        if error is not None:
            raise error
        return 200, {"success": True, "data": data}

    return lambda context: nexus_client("http://x", token="t", tenant="picasso", transport=transport,
                                        answer_context=context)


class _Gate:
    """동시 한도의 문 흉내 — 드나듦을 적는다."""

    def __init__(self):
        self.log = []

    def acquire(self, timeout=None):
        self.log.append(("acquire", timeout))
        return True

    def release(self):
        self.log.append("release")


def test_액티비티는_계약_응답을_돌려준다(tmp_path, diagnose_request, khala_data):
    """khala 는 워커의 문(동시 한도) 안에서만 부르고, 문을 기다리는 몫은 20초를 넘지 않는다(계약 §2)."""
    gate = _Gate()
    activity = worker.make_activity(_client(khala_data(), on_call=lambda: gate.log.append("call")),
                                    FirstResultStore(tmp_path / "f.sqlite3"), "c", gate)

    response = ActivityEnvironment().run(activity, diagnose_request())

    assert response["outcome"] == "RECOMMENDED"
    (acquire, waited), *rest = gate.log
    assert acquire == "acquire" and 0 < waited <= GATE_WAIT, "문을 기다리는 몫"
    assert rest == ["call", "release"], "khala 는 문 안에서만 부른다"


def test_재시도할_생성_실패는_재시도_가능한_오류다(tmp_path, diagnose_request, khala_data):
    data = khala_data(llm_failed=True, llm_failure_reason="rate_limit", answer="")
    activity = worker.make_activity(_client(data), FirstResultStore(tmp_path / "f.sqlite3"), "c")

    with pytest.raises(ApplicationError) as raised:
        ActivityEnvironment().run(activity, diagnose_request())

    assert (raised.value.type, raised.value.non_retryable) == ("rate_limit", False)


def test_계약_위반과_영원한_실패와_뜻밖의_것은_재시도하지_않는다(tmp_path, diagnose_request, khala_data):
    """다시 보내도 같은 것 — 계약 위반 · `quota` · `auth` · `other` — 은 `non_retryable` 이다. **이 계층의 뜻밖의
    예외도 그렇다** — 모르는 것을 재시도 가능으로 치지 않는다(계약 §5 의 `other` 와 같은 까닭). 재시도마다
    LLM 에 다시 묻게 되기 때문이다. khala 가 글자가 아닌 사유를 주면 글자로 적는다 — 아니면 SDK 가 실패를 못 적고
    재시도할 실패로 바꿔 적는다."""
    store = FirstResultStore(tmp_path / "f.sqlite3")
    quota = worker.make_activity(_client(khala_data(llm_failed=True, llm_failure_reason="quota", answer="")),
                                 store, "c")
    with pytest.raises(ApplicationError) as raised:
        ActivityEnvironment().run(quota, diagnose_request())
    assert (raised.value.type, raised.value.non_retryable) == ("quota", True)

    ok = worker.make_activity(_client(khala_data()), store, "c")
    with pytest.raises(ApplicationError) as raised:
        ActivityEnvironment().run(ok, diagnose_request(contractVersion="0.5"))
    assert (raised.value.type, raised.value.non_retryable) == ("ContractViolation", True)
    # 이 테스트 환경은 입력을 풀지 않아 SDK 의 책임을 못 본다 — 힌트가 있으면 SDK 가 먼저 풀어 객체가 아닌 요청이
    # 계약 위반이 아니라 재시도할 실패가 된다(묶음 5 검토)
    assert "payload" not in typing.get_type_hints(ok), "입력의 모양은 parse_request 가 본다"

    odd = worker.make_activity(_client(error=ValueError("본문이 JSON 이 아니다")), store, "c")
    with pytest.raises(ApplicationError) as raised:
        ActivityEnvironment().run(odd, diagnose_request(episodeId="ep-2"))
    assert (raised.value.type, raised.value.non_retryable) == ("ValueError", True)

    number = worker.make_activity(_client(khala_data(llm_failed=True, llm_failure_reason=5, answer="")), store, "c")
    with pytest.raises(ApplicationError) as raised:
        ActivityEnvironment().run(number, diagnose_request(episodeId="ep-3"))
    assert (raised.value.type, raised.value.non_retryable) == ("5", True)


def test_부르는_동안_하트비트를_보낸다(tmp_path, diagnose_request, khala_data, monkeypatch):
    """잡자마자 한 번, 그 뒤 khala 를 기다리는 동안 주기마다 알린다 — khala 가 빨리 답해도 에피소드가 이 진단이 살아
    있음을 본다. **제때 안 받아진 하트비트는 실패가 아니다** — 다음 주기에 다시 알린다(계약 §5)."""
    monkeypatch.setattr(worker, "BEAT", 0.01)
    beats, generating = [], threading.Event()

    def on_heartbeat(*details):
        beats.append(details)
        if len(beats) == 1:
            raise TimeoutError  # 이벤트 루프가 10초 안에 못 받았을 때 SDK 가 던지는 것
        if len(beats) == 3:
            generating.set()

    env = ActivityEnvironment()
    env.on_heartbeat = on_heartbeat
    activity = worker.make_activity(_client(khala_data(), hold=generating),
                                    FirstResultStore(tmp_path / "f.sqlite3"), "c")

    response = env.run(activity, diagnose_request())

    assert response["outcome"] == "RECOMMENDED"
    assert generating.is_set(), "khala 가 답하기 전에 주기마다 알렸다"


def test_취소는_실패가_아니라_취소로_알린다(tmp_path, diagnose_request, khala_data, monkeypatch):
    """`Cancelled` 를 그대로 올리면 SDK 가 재시도할 실패로 적는다 — 취소로 알려야 에피소드의 인수 · 끄기가
    이력에 맞게 남는다. SDK 의 취소는 기다리는 고리가 `is_cancelled` 로 본다 — 스레드에 던져 넣게 두면
    (`no_thread_cancel_exception` 을 빼면) 뜻밖의 예외가 되어 재시도하지 않는 실패로 적힌다. 백그라운드 스레드는 그래도 답을
    적는다(계약 §6)."""
    monkeypatch.setattr(worker, "BEAT", 0.01)
    store = FirstResultStore(tmp_path / "f.sqlite3")
    env, generating = ActivityEnvironment(), threading.Event()
    activity = worker.make_activity(_client(khala_data(), hold=generating, on_call=env.cancel), store, "c")

    with pytest.raises(CancelledError):
        env.run(activity, diagnose_request())

    generating.set()
    assert drain(timeout=5) is True, "곁 스레드가 답을 적고 끝났다"
    state = store.claim(parse_request(diagnose_request()).key, "다음 시도", time.time())
    assert isinstance(state, Done) and state.response["outcome"] == "RECOMMENDED", "취소돼도 곁 스레드가 답을 적는다"


def test_판_환경_변수의_공백은_판이_아니다(monkeypatch):
    """`NARRATOR_COMMIT` 의 앞뒤 공백은 떼고, 공백만이면 없는 것으로 보고 커밋에서 읽는다. koshei 는 버전 필드가 `null` 이거나
    공백만이 아닌 글자이기를 보므로 공백 버전 하나가 이 워커의 모든 응답을 계약 위반으로 만든다(2026-09-30)."""
    described = []

    def run(args, **kwargs):
        described.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="f71ca2e-dirty\n")

    monkeypatch.setattr(worker.subprocess, "run", run)
    monkeypatch.setenv("NARRATOR_COMMIT", " abc1234 ")
    assert worker._commit() == "abc1234" and not described, "준 판은 앞뒤 공백만 뗀다"
    monkeypatch.setenv("NARRATOR_COMMIT", "   ")
    assert worker._commit() == "f71ca2e-dirty" and described, "공백만이면 커밋에서 읽는다"
