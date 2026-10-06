"""결과 넷의 판정 — 진단 계약 0.6 §4 「판정 순서」.

**위에서부터 처음 걸리는 것이 결과다.** 생성 실패는 값이 아니라 예외다 — 값으로 돌리면 Temporal 이
재시도할 기회를 잃고, 예외로 두면 사유로 재시도를 가른다(§5). 하위 범주를 가르는 값은 설명 경로의 기록기가
이미 가른 것(`recorder.outcome.classify`)을 그대로 쓴다 — 약한 근거와 근거 없음의 순서가 같다.
"""

from dataclasses import dataclass

from diagnose.answer import head_value, resolve
from recorder.outcome import TRANSIENT, Outcome

RECOMMENDED = "RECOMMENDED"
NO_GROUNDS = "NO_GROUNDS"
UNCITED = "UNCITED"
OUT_OF_CANDIDATES = "OUT_OF_CANDIDATES"


class DiagnoseFailed(Exception):
    """khala 가 답을 못 냈다. **재시도할 만한지를 들고 올라간다.**

    사유는 khala 의 한 자리(`llm/failure.py`)에서 온 것이고 이 계층은 공급자 문구를 다시 가르지 않는다.
    사유가 비면(`llm_failed` 인데 사유가 없는 답) `unreachable` 로 적는다 — 설명 경로가 요청 거절(4xx)과
    답의 모양이 안 온 실패를 적는 말과 같다(`receiver/pipeline.py`). 재시도하지 않는다.
    """

    def __init__(self, reason):
        self.reason = reason or "unreachable"
        self.retryable = self.reason in TRANSIENT
        super().__init__(self.reason)


@dataclass(frozen=True)
class Verdict:
    outcome: str
    candidate_id: object  # str | None
    picked: object        # str | None — 후보 외 선택일 때만
    #: 모든 답의 「권고:」 값과 그것이 가리키는 후보. 응답에 안 싣고 이 계층의 기록에 남긴다 — 후보 외 선택 비율을
    #: 결과 값이 아니라 이것으로 센다(계약 §4). 별칭표는 요청마다 다르므로 풀이를 함께 남긴다.
    raw_pick: object      # str | None
    resolved: object      # str | None


def judge(record, table):
    """기록 하나(`recorder.record.Record`)를 결과로.

    :param table: `{별칭: 식별자}` (`diagnose.context.aliases`).
    :raises DiagnoseFailed: 생성 실패일 때.
    """
    if record.outcome is Outcome.GENERATION_FAILED:
        raise DiagnoseFailed(record.reason)
    raw = head_value(record.answer, "권고")
    resolved = None if raw is None else resolve(raw, table)
    if record.outcome is Outcome.NO_EVIDENCE:
        return Verdict(NO_GROUNDS, None, None, raw, resolved)
    if not any(c.get("verified") is True for c in record.citations):
        return Verdict(UNCITED, None, None, raw, resolved)
    if raw is None:
        return Verdict(OUT_OF_CANDIDATES, None, None, None, None)
    if resolved is None:
        return Verdict(OUT_OF_CANDIDATES, None, raw, raw, None)
    return Verdict(RECOMMENDED, resolved, None, raw, resolved)
