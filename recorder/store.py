"""기록 저장소 — `BOUNDARY.md` §3.2, §3.4.

**저장소가 곧 커서다.** §3.2 가 「처리 표시는 읽는 쪽의 상태」라 했고, 그 상태를
기록과 따로 두면 「무엇을 처리했나」의 원천이 둘이 된다 — 둘이 갈릴 때 어느 쪽이
참인지 판정할 방법이 없다. **적힌 것이 곧 처리한 것이다.**

형식은 picasso 의 적재면과 같은 모양이다 — 줄 단위 JSON. 덧붙이기가 줄 추가로
그대로 옮겨지기 때문이고, 한 벌 스냅샷이 아니라 시간에 걸쳐 쌓이는 것이라
`manifest` 는 두지 않는다.
"""

import json

from recorder.outcome import Outcome
from recorder.record import Record


class AlreadyRecorded(Exception):
    """같은 열쇠에 두 번째 설명을 적으려 했다.

    **사건당 설명은 한 건이다.** 커서가 이미 막고 있으므로 여기까지 온 것은 결함이고,
    조용히 덮으면 그 결함이 안 보인다.
    """


class RecordStore:
    """설명 기록. 덧붙이기만 하고 지우지 않는다."""

    def __init__(self, path):
        self.path = path

    def append(self, record):
        key = tuple(record.key)
        if key in self.seen():
            raise AlreadyRecorded(f"이미 적힌 열쇠다: {key}")
        line = json.dumps(_encode(record), ensure_ascii=False, sort_keys=True)
        with open(self.path, "a", encoding="utf-8", newline='\n') as out:
            out.write(line + '\n')

    def load(self):
        """적힌 순서대로. 파일이 없으면 빈 목록 — **아직 아무것도 안 적은 것이다.**"""
        try:
            raw = open(self.path, encoding="utf-8").read()
        except FileNotFoundError:
            return []
        return [_decode(json.loads(l)) for l in raw.splitlines() if l.strip()]

    def seen(self):
        """처리한 열쇠. 이것이 수신기의 `seen` 이 된다(`BOUNDARY.md` §3.4)."""
        return {r.key for r in self.load()}

    def subjects(self):
        """이 층이 본 사건의 주체. 재발을 셀 이력이다(`receiver/history.py`)."""
        return [r.subject for r in self.load() if r.subject]


def _encode(record):
    return {
        "key": list(record.key),
        "outcome": record.outcome.value,
        "answer": record.answer,
        "citations": record.citations,
        "attempts": record.attempts,
        "limit": record.limit,
        "reason": record.reason,
        "elapsed": record.elapsed,
        "diagnostics": record.diagnostics,
        "subject": record.subject,
    }


def _decode(row):
    return Record(
        key=tuple(row["key"]),
        outcome=Outcome(row["outcome"]),
        answer=row["answer"],
        citations=row["citations"],
        attempts=row["attempts"],
        limit=row["limit"],
        reason=row.get("reason", ""),
        elapsed=row.get("elapsed", 0.0),
        diagnostics=row.get("diagnostics") or {},
        subject=row.get("subject") or {},
    )
