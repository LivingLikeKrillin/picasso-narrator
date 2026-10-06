"""진단 한 번 — 진단 계약 0.6 전체를 잇는 자리.

[run_diagnosis] 가 **같은 길**이다(계약 §7) — 워커와 권고 측정이 이것을 부른다. 저장소를 모르므로 측정이
같은 함수를 그대로 부른다. [diagnose] 는 그 앞뒤에 결과 캐시 · 하트비트 · 취소를 두른 것이다.

**LLM 은 여전히 `explainer` 안에만 있고 진단당 한 번이다** — `receiver.pipeline.ask_and_record` 를 한도 1 로
부른다. 재시도의 주인은 Temporal 하나다(계약 §2).

**같은 멱등성 키에 khala 는 한 번이다(계약 §6).** 결과를 적거나 놓는 것은 khala 를 부른 백그라운드 스레드의 일이고, 부른
쪽이 취소돼 먼저 떠나도 백그라운드 스레드는 끝까지 가서 적는다 — 그동안 임대를 붙든다. 취소는 대개 Temporal 이 이미
시간을 넘긴 시도를 버리고 다시 보낼 때 온다. 그때 잡은 것을 놓으면 다시 온 요청이 khala 를 또 부르고, 버려진
백그라운드 스레드는 여전히 브리지 자리를 문다. khala 의 생성은 끊을 수 없다(브리지가 끊긴 요청을 취소하지 않는다).
"""

import threading
import time
import uuid
from dataclasses import dataclass

from composer.query import compose, compose_search
from diagnose.answer import body, card_items, head_value
from diagnose.context import aliases, render
from diagnose.contract import parse_request, response
from diagnose.fields import uncited_sentences, unverified_claims
from diagnose.judge import DiagnoseFailed, judge
from diagnose.store import Claimed, Done
from receiver.pipeline import ask_and_record

#: 기다리는 쪽이 저장소를 다시 보고, 부르는 쪽이 하트비트와 임대를 알리는 간격(초). 워커는 10 을 준다.
POLL = 2.0

#: 살아 있는 백그라운드 스레드. **워커를 내릴 때 기다린다** — 부른 쪽이 취소돼 떠난 뒤에도 백그라운드 스레드는 khala 의 답을 적고 임대를
#: 붙드는데, 데몬이라 프로세스가 먼저 끝나면 그 답이 버려지고 임대가 끝나 다음 워커가 khala 를 또 부른다(묶음 4 검토).
_IN_FLIGHT = set()
_IN_FLIGHT_LOCK = threading.Lock()


def drain(timeout):
    """살아 있는 백그라운드 스레드가 다 끝나기를 [timeout] 초까지 기다린다. 다 끝났으면 `True`."""
    deadline = time.monotonic() + timeout
    with _IN_FLIGHT_LOCK:
        threads = list(_IN_FLIGHT)
    for thread in threads:
        if thread.is_alive():  # 못 띄운 스레드를 기다리면 `RuntimeError` 라 나머지를 못 기다린다(묶음 5 검토)
            thread.join(max(0.0, deadline - time.monotonic()))
    with _IN_FLIGHT_LOCK:
        return not any(thread.is_alive() for thread in _IN_FLIGHT)


#: khala 호출의 문(동시 한도)을 기다리는 상한(초) — 하트비트 두 주기. **문을 기다리는 것도 StartToClose 안이다.**
#: 넘으면 브리지 혼잡(`unavailable`, 재시도할 예외)으로 돌려 기다림을 Temporal 큐(ScheduleToClose)로 넘긴다.
#: 그래서 StartToClose 540 = 문 20 + 전송 타임아웃 510 + 저장소와 응답 조립 10 이다(계약 §2). **잡기를 기다린 시간도
#: 이 몫에 든다** — 앞 시도가 죽어 임대가 끝난 뒤에야 잡았는데 이미 20초가 지났으면 khala 를 늦게 시작하게 된다.
GATE_WAIT = 20.0


class Cancelled(Exception):
    """부르는 쪽이 취소했다. **잡은 것은 백그라운드 스레드가 끝까지 쥐고 간다** — 놓지 않는다."""


@dataclass(frozen=True)
class Diagnosis:
    """응답과, 응답에 안 싣는 이 계층의 기록 — 모든 답의 「권고:」 값과 그 풀이(계약 §4 · §7 지표), 그리고 설명
    경로와 같은 기록(`recorder.record.Record`) 하나. 측정이 근거 문서와 시간을 같은 함수에서 얻게."""

    response: dict
    raw_pick: object
    resolved: object
    record: object


def query_text(snapshot):
    """스냅샷에서 질의 하나(계약 §3 「질의의 주체」).

    사건 첫째를 주체로, 탐색 첫째를 짝으로. 사건이 없으면 탐색 첫째를 그 자체로. **재발 횟수는 안 싣는다** —
    워커는 이 계층이 본 사건 전체를 들고 있지 않고, 스냅샷 안에서만 세면 뜻이 바뀐다.
    """
    incidents, searches = snapshot["incidents"], snapshot["searches"]
    if incidents:
        return compose(incidents[0], searches[0] if searches else None).text
    return compose_search(searches[0]).text


def run_diagnosis(request, client, commit, gate=None, gate_wait=GATE_WAIT):
    """진단 한 번. **저장소를 모른다.**

    :param client: `answer_context -> search` — 답변 컨텍스트를 실어 khala 를 부를 `search` 를 만든다.
    :param commit: 이 계층의 버전(짧은 커밋 해시).
    :param gate: khala 호출을 감쌀 문 — 워커의 동시 한도(`acquire(timeout=)` · `release()` 를 가진 세마포어).
        없으면 막지 않는다.
    :param gate_wait: 문을 기다릴 시간(초). [diagnose] 는 잡기를 기다린 시간을 빼고 준다.
    :raises ContextTooLarge: 답변 컨텍스트를 못 지을 때(재시도 안 함).
    :raises DiagnoseFailed: 생성 실패일 때(사유로 재시도를 가름), 그리고 문이 [GATE_WAIT] 안에 안 열릴 때(`unavailable`).
    """
    table = aliases(request.candidates)
    context = render(request.candidates, request.unknowns, request.history)
    if gate is not None and not gate.acquire(timeout=gate_wait):
        raise DiagnoseFailed("unavailable")  # 브리지 혼잡 — 기다림은 Temporal 큐로 넘긴다
    try:
        record = ask_and_record(request.key, query_text(request.snapshot), client(context), limit=1)
    finally:
        if gate is not None:
            gate.release()
    verdict = judge(record, table)
    rationale = head_value(record.answer, "이유") or None  # 빈 「이유:」 줄은 이유를 안 댄 것이다
    diagnostics = record.diagnostics
    usage = diagnostics.get("usage") or {}
    return Diagnosis(
        response=response(
            request,
            outcome=verdict.outcome,
            candidate_id=verdict.candidate_id,
            picked=verdict.picked,
            rationale=rationale,
            card=card_items(record.answer),
            cause=body(record.answer),
            citations=record.citations,
            unverified_claims=unverified_claims(record.citations, diagnostics),
            uncited_sentences=uncited_sentences(rationale, record.citations),
            versions={"modelId": _known(usage.get("model")),
                      "promptVersion": _known(diagnostics.get("prompt_version")),
                      "corpusVersion": _known(diagnostics.get("corpus_version")),
                      "searchFingerprint": _known(diagnostics.get("search_fingerprint")),
                      "narratorCommit": commit},
            elapsed=record.elapsed,
        ),
        raw_pick=verdict.raw_pick,
        resolved=verdict.resolved,
        record=record,
    )


def diagnose(payload, *, client, store, commit, gate=None, beat=lambda: None, cancelled=lambda: False,
             clock=time.time, sleep=time.sleep, poll=POLL):
    """요청 하나 → 응답 하나. 같은 멱등성 키의 두 번째 요청은 첫 결과를 돌려준다(계약 §6).

    :param gate: khala 호출을 감쌀 문 — 워커의 동시 한도.
    :param beat: 살아 있다고 알릴 때마다 부른다(워커의 하트비트). 잡자마자 한 번 부른다.
    :param cancelled: 참이면 기다림을 멈춘다(워커의 취소).
    :raises ContractViolation · ContextTooLarge · DiagnoseFailed · Cancelled:
    """
    request = parse_request(payload)
    owner = uuid.uuid4().hex
    started = clock()
    while True:
        state = store.claim(request.key, owner, clock())
        if isinstance(state, Done):
            return state.response
        if isinstance(state, Claimed):
            break
        # 남이 같은 멱등성 키를 묻는 중이다 — 그 결과를 기다린다
        if cancelled():
            raise Cancelled(f"기다리다 취소됐다: {request.key}")
        beat()
        sleep(poll)
    waited = clock() - started
    stop = cancelled()
    if stop or waited > GATE_WAIT:
        # 기다리는 사이 취소됐거나, 잡았을 때 이미 문 몫을 다 썼다 — 지금 khala 를 시작하면 이 시도가 기한을
        # 넘겨 버려지고 그 백그라운드 스레드가 또 문을 쥔다(계약 §2). 놓고 돌려보낸다.
        store.release(request.key, owner)
        if stop:
            raise Cancelled(f"기다리다 취소됐다: {request.key}")
        raise DiagnoseFailed("unavailable")
    outcome = {}
    finished = threading.Event()

    def work():
        """khala 를 부르고 **결과를 적거나 놓는 것까지** 한다 — 부른 쪽이 먼저 떠나도. 오류는 먼저 건네 두고
        놓는다 — 놓기가 실패해도 원래 오류가 가려지지 않게."""
        try:
            diagnosis = run_diagnosis(request, client, commit, gate, GATE_WAIT - waited)
        except BaseException as error:
            outcome["error"] = error
            _quietly(store.release, request.key, owner)
        else:
            try:
                outcome["response"] = store.complete(request.key, diagnosis.response, diagnosis.raw_pick,
                                                     diagnosis.resolved, clock())
            except BaseException as error:  # 답은 받았는데 못 적었다 — 놓아 다음 시도가 다시 묻게
                outcome["error"] = error
                _quietly(store.release, request.key, owner)
        finally:
            finished.set()
            with _IN_FLIGHT_LOCK:
                _IN_FLIGHT.discard(threading.current_thread())

    side = threading.Thread(target=work, name=f"diagnose-{request.episode_id}", daemon=True)
    with _IN_FLIGHT_LOCK:
        _IN_FLIGHT.add(side)
    side.start()
    try:
        beat()  # 잡자마자 한 번 — khala 가 빨리 답해도 에피소드가 이 진단이 살아 있음을 본다
        while not finished.wait(poll):
            if cancelled():
                raise Cancelled(f"진단 중 취소됐다: {request.key}")
            beat()
            _quietly(store.touch, request.key, owner, clock())
    except BaseException:
        threading.Thread(target=_hold, args=(store, request.key, owner, finished, clock, poll),
                         name=f"hold-{request.episode_id}", daemon=True).start()
        raise
    if "error" in outcome:
        raise outcome["error"]
    return outcome["response"]


def _hold(store, key, owner, finished, clock, poll):
    """부른 쪽이 떠난 뒤에도 백그라운드 스레드가 끝날 때까지 임대를 붙든다 — 같은 멱등성 키의 다음 시도가 khala 를 다시
    부르지 않고 그 결과를 기다리게."""
    while not finished.wait(poll):
        _quietly(store.touch, key, owner, clock())


def _quietly(action, *args):
    """저장소 일 한 번 — 실패해도 흐름을 끊지 않는다. ⛔ **알리기 한 번의 실패가 임대를 붙드는 고리를 죽이면
    임대가 끝나 다른 시도가 khala 를 또 부른다**(묶음 4 검토, 동시 한도 2 에서 재현). 알리기는 다음 주기에 다시
    하고, 놓기가 실패하면 임대가 끝날 때 풀린다."""
    try:
        action(*args)
    except Exception:
        pass


def _known(value):
    """버전 필드 하나. **빈 글자와 공백만인 글자는 모름이라 `null` 로 옮긴다** — khala 는 코퍼스 버전을 모를 때 빈 글자를
    주고(khala 요청 문서 24), koshei 는 버전 필드가 `null` 이거나 공백만이 아닌 글자이기를 본다(2026-09-30). 글자가 아닌 값도
    `null` 이다. 글자는 떼지 않고 그대로 옮긴다."""
    return value if isinstance(value, str) and value.strip() else None
