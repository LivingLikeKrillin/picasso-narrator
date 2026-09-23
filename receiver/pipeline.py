"""한 벌을 설명으로 옮긴다 — `BOUNDARY.md` §1.5.

네 조각을 잇는 자리다. **LLM 은 `explainer` 안에만 있고**, 여기는 무엇을 언제
부르는지만 정한다.
"""

from composer.query import compose, compose_search
from explainer.ask import ask_once
from receiver.history import count_recurrence, subject
from receiver.idempotency import idempotency_key
import time

from receiver.retry import Exhausted, with_retries
from recorder.outcome import retryable
from recorder.record import from_answer, from_failure


def explain(batch, search, limit=3, prior=()):
    """한 벌의 **두 줄기를 모두** 설명한다. 순서는 열린 순서 그대로다.

    **빠뜨리는 줄이 없다.** 설명 경로가 통째로 죽어도 줄마다 한 건이 남고, 그
    건에 몇 번 해봤는지가 들어간다 — 하나라도 조용히 사라지면 운영자는 그 사건에
    설명이 「아직 안 온 것」인지 「영영 안 올 것」인지 구별하지 못한다.

    **사건만 설명하고 탐색 줄을 버리지 않는다**(§4.1). 「대안 없음」과 「가려졌다」는
    탐색 줄에만 있다.

    :param prior: 저장소가 본 사건의 주체. 이 한 벌의 것(`batch.history`)과 합쳐
        재발을 센다 — 둘 중 하나만 보면 같은 한 벌 안의 앞선 사건이나 지난 벌의 사건이
        빠진다.
    """
    history = list(prior) + list(batch.history)
    records = []
    for bundle in batch.incidents:
        query = compose(bundle, recurrence=count_recurrence(bundle, history))
        records.append(_one(bundle, query, batch.manifest, search, limit, who=subject(bundle)))
    for record in batch.searches:
        records.append(_one(record, compose_search(record), batch.manifest, search, limit))
    return records


def ask_and_record(key, text, search, limit, who=None):
    """한 번 물어 한 건을 만든다. **부르는 길이 하나여야 한다.**

    평가 하네스가 자기 경로를 따로 가지면 재는 것이 도는 것과 달라진다 — 재시도를
    안 하거나 사유를 안 남기면 평가표의 실패율이 실제 운영의 것이 아니게 되고,
    원천이 둘이면 갈릴 때 어느 쪽이 참인지 모른다.
    """
    started = time.monotonic()
    try:
        answer = with_retries(lambda: ask_once(text, search), limit, again=retryable)
    except Exhausted as exhausted:
        return from_failure(
            key,
            exhausted.attempts,
            exhausted.limit,
            reason=exhausted.reason or "unreachable",
            elapsed=round(time.monotonic() - started, 1),
            subject=who,
        )
    # **다시 할 만한 것만 상한까지 간다.** `auth` 는 설정 전까지 영원히 실패하므로
    # 한 번에 멈추고, 기록의 「재시도 n/n」이 그 사실을 그대로 든다.
    attempts = limit if retryable(answer) else 1
    return from_answer(
        key, answer, attempts=attempts, limit=limit, elapsed=round(time.monotonic() - started, 1),
        subject=who,
    )


def _one(record, query, manifest, search, limit, who=None):
    return ask_and_record(idempotency_key(record, manifest), query.text, search, limit, who=who)
