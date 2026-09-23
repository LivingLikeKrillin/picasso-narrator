"""실물 전송 — `BOUNDARY.md` §3.

**얇다.** 판단이 여기 들어가면 시험이 못 닿는 자리에 규칙이 생긴다 — 상태를 보고
무엇을 할지는 `ask_once` 가 정하고, 여기는 주고받기만 한다.

**다만 끊긴 것은 여기서 답의 모양으로 바꾼다.** 전송 예외가 그대로 올라가면 부르는
쪽의 재시도도 기록도 지나치고, **한 줄의 실패가 한 벌을 통째로 죽인다**(2026-09-19
실측 — 골든셋 한 벌이 `httpx.ReadTimeout` 하나로 중단됐다).
"""

import httpx

#: 답변 합성이 얼마나 걸리는지는 **편차가 크다.** 같은 항목이 실행마다 94초와 180초
#: 사이를 오간다(2026-09-19 실측). 180초로 두었을 때 절반이 잘렸는데, 그건 느린 것을
#: 걸러낸 것이 아니라 **편차 한가운데를 자른 것**이라 데이터가 절반씩 버려졌다.
#:
#: 올리면 느림이 가려질까 — **안 가려진다.** `Record.elapsed` 가 몇 초 걸렸는지를
#: 남기므로 3분짜리 설명은 3분으로 보인다. 감추는 것과 다른 점이 그것이다.
TIMEOUT = 360.0

#: 전송이 끊긴 것을 답의 모양으로 옮길 때 쓰는 상태. HTTP 가 준 값이 아니라
#: **이 층이 붙인 값**이고, 그래서 599 다(표준에 없는 자리).
TRANSPORT_FAILED = 599


def http_transport(method, url, headers, payload, timeout=TIMEOUT):
    """`(status, body)`. **4xx·5xx 에 예외를 던지지 않는다.**

    던지면 상태가 사라지고, 부르는 쪽이 「오류」와 「답이 아닌 것」을 구별할 근거를
    잃는다. 오류의 본문(`detail`)도 함께 와야 기록에 사유가 남는다.

    전송이 끊기면 [TRANSPORT_FAILED] 와 사유를 돌려준다 — `timeout` 은 **안 끝난
    것**이라 다시 해볼 만하고, 끊긴 것은 줄여도 안 되므로 `unavailable` 이다
    (Nexus `llm/failure.py` 와 같은 가름).
    """
    try:
        response = httpx.request(method, url, headers=headers, json=payload, timeout=timeout)
    except httpx.TimeoutException as timed_out:
        return TRANSPORT_FAILED, _failure("timeout", timed_out)
    except httpx.HTTPError as broken:
        return TRANSPORT_FAILED, _failure("unavailable", broken)
    return response.status_code, response.json()


def _failure(reason, error):
    return {
        "detail": f"{type(error).__name__}: {error}",
        "llm_failure_reason": reason,
    }
