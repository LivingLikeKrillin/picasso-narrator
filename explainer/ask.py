"""Nexus 에 한 번 묻는다 — `BOUNDARY.md` §1.5.

**이 저장소에서 LLM 이 들어가는 유일한 자리다.** 그리고 하는 일은 사건당 한 번의
질의-응답이며, 도구 호출은 Nexus 내부의 검색뿐이다. 목표를 향해 도구를 고르며
반복하는 루프는 v1 에 없다 — 넣으려면 조회 횟수와 비용에 상한이 먼저 필요하고,
그때 `BOUNDARY.md` 를 고친다.
"""

OK = 200


class NexusUnavailable(Exception):
    """답을 못 받았다. **「근거 없음」이 아니다.**

    오류에는 `data` 봉투가 없고 `detail` 만 온다. 그것을 답으로 다루면 뒤따르는
    모든 읽기가 키 부재로 무너지고, 무너진 자리는 근거가 없어서 빈 것과 구별되지
    않는다. 여기서 끊어 **「생성 실패」로 기록될 길**로 보낸다.

    **사유를 들고 올라간다.** 「안 끝났다」와 「끊겼다」는 다음 행동이 다르고,
    버리면 기록에 한 값만 남는다.
    """

    def __init__(self, message, reason=""):
        super().__init__(message)
        self.reason = reason


def ask_once(query, search):
    """질의 하나를 던지고 **답의 알맹이**를 돌려준다. 부르는 횟수는 하나다.

    재시도는 이 함수의 일이 아니다 — 여기서 돌면 「한 번」이 규율이 아니라 의도가
    되고, 상한을 세는 자리가 둘로 갈린다. 재시도와 그 상한은 수신기가 든다.

    :param search: `(status, body)` 를 돌려주는 것. 주입받는 이유는 전송(HTTP)이
        이 조각의 관심사가 아니기 때문이고, 시험이 실물 없이 물리기 때문이다.
    :returns: 봉투를 벗긴 `data`. 최상위는 `{success, data, error, meta}` 이고
        **한 겹 벗겨야 한다**(2026-09-18 실측).
    :raises NexusUnavailable: 상태가 200 이 아니거나 봉투가 성공이 아닐 때.
    """
    status, body = search(query)
    if status != OK:
        raise NexusUnavailable(
            f"{status}: {body.get('detail')}", reason=body.get("llm_failure_reason", "")
        )
    if not body.get("success"):
        raise NexusUnavailable(f"성공 봉투가 아니다: {body.get('error')}")
    return body["data"]
