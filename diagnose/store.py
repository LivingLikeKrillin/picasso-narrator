"""첫 결과 저장소 — 진단 계약 0.6 §6.

**같은 열쇠의 두 번째 요청에는 기록해 둔 첫 결과를 돌려주고 khala 를 다시 부르지 않는다.** 워커가 답을
받은 뒤 완료를 보고하기 전에 죽으면 Temporal 이 같은 요청을 다시 보낸다. 그때 LLM 에 다시 물으면 권고가
바뀔 수 있다 — 판 칸은 그것을 막지 못하고(계약 §4), 막는 것은 여기다.

**저장소는 하나다.** 워커가 여럿이어도 한 파일을 함께 쓴다(SQLite 의 파일 잠금). **그래서 한 호스트의
워커끼리만 나눈다** — 호스트를 넘기려면 저장소를 바꾼다. 같은 열쇠가 동시에 두 번 오면 먼저 잡은 쪽만
khala 를 부르고 다른 쪽은 기다렸다 그 결과를 받는다.

**잡은 것은 임대다.** 잡은 쪽이 [LEASE] 초 안에 알리지(`touch`) 않으면 다른 쪽이 넘겨받는다 — 잡은 채 죽은
워커가 열쇠를 영영 막지 않게. **끝난 것은 바뀌지 않는다** — 먼저 끝낸 쪽의 결과가 첫 결과다.

**추가 전용이다.** 끝난 항목은 지우지 않는다 — 에피소드가 닫힐 때까지 유효하다(계약 §6). 정리는 v1 에 없다.
응답에 안 싣는 이 층의 기록 둘(모든 답의 「권고:」 값과 그 풀이)을 함께 적는다 — 후보 밖 비율을 결과 값이
아니라 이것으로 센다(계약 §4). 별칭표는 요청마다 달라 값만으로는 다시 못 푼다.
"""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass

#: 잡은 쪽이 이만큼 조용하면 넘겨받는다(초). koshei 의 HeartbeatTimeout 과 같다(계약 §2) — 워커가 죽으면
#: Temporal 이 그 기한에 알아채고 다시 보내는데, 그때 임대가 이미 끝나 있어 기다리지 않는다. 하트비트(10 초)가
#: 세 번 빠져야 넘어간다.
LEASE = 30.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS first_result (
    episode_id TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    candidates_version TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('CLAIMED', 'DONE')),
    owner TEXT,
    touched_at REAL,
    response TEXT,
    raw_pick TEXT,
    resolved_pick TEXT,
    done_at REAL,
    PRIMARY KEY (episode_id, attempt, candidates_version)
)
"""

_WHERE = "episode_id = ? AND attempt = ? AND candidates_version = ?"


@dataclass(frozen=True)
class Done:
    """끝났다. 첫 결과를 든다."""

    response: dict


@dataclass(frozen=True)
class Claimed:
    """잡았다. 이 쪽이 khala 를 부른다."""

    owner: str


@dataclass(frozen=True)
class Busy:
    """남이 잡고 있다. 기다린다."""

    owner: str


class FirstResultStore:
    """열쇠 `(episodeId, attempt, candidatesVersion)` 마다 결과 하나."""

    def __init__(self, path, lease=LEASE):
        self.path = str(path)
        self.lease = lease
        with self._tx() as db:
            db.execute(_SCHEMA)

    @contextmanager
    def _tx(self):
        """쓰기 잠금을 먼저 잡는 거래 하나(`BEGIN IMMEDIATE`). 읽고 판단하고 쓰는 사이에 남이 끼지 않는다.

        연결은 부를 때마다 새로 연다 — 워커의 스레드가 여럿이어도 연결을 나눠 쓰지 않는다.
        """
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                db.execute("ROLLBACK")
                raise
            db.execute("COMMIT")
        finally:
            db.close()

    def claim(self, key, owner, now):
        """열쇠를 잡는다. [Done] · [Claimed] · [Busy] 중 하나."""
        with self._tx() as db:
            row = db.execute(f"SELECT state, owner, touched_at, response FROM first_result WHERE {_WHERE}",
                             key).fetchone()
            if row is None:
                db.execute("INSERT INTO first_result (episode_id, attempt, candidates_version, state, owner, "
                           "touched_at) VALUES (?, ?, ?, 'CLAIMED', ?, ?)", (*key, owner, now))
                return Claimed(owner)
            state, holder, touched, response = row
            if state == "DONE":
                return Done(json.loads(response))
            if holder == owner or now - touched > self.lease:
                db.execute(f"UPDATE first_result SET owner = ?, touched_at = ? WHERE {_WHERE}",
                           (owner, now, *key))
                return Claimed(owner)
            return Busy(holder)

    def touch(self, key, owner, now):
        """잡은 쪽이 살아 있다고 알린다. 넘겨받혔거나 끝났으면 `False`."""
        with self._tx() as db:
            cursor = db.execute(f"UPDATE first_result SET touched_at = ? WHERE {_WHERE} "
                                "AND state = 'CLAIMED' AND owner = ?", (now, *key, owner))
            return cursor.rowcount == 1

    def complete(self, key, response, raw_pick, resolved_pick, now):
        """결과를 적고 **적힌 결과**를 돌려준다. 이미 끝났으면 덮지 않고 먼저 적힌 것을 돌려준다.

        칸 순서를 지킨다(정렬하지 않는다) — 계약 §4 의 순서가 Temporal 이력에서 그대로 읽히게.
        """
        text = json.dumps(response, ensure_ascii=False)
        with self._tx() as db:
            row = db.execute(f"SELECT state, response FROM first_result WHERE {_WHERE}", key).fetchone()
            if row is not None and row[0] == "DONE":
                return json.loads(row[1])
            if row is None:
                db.execute("INSERT INTO first_result (episode_id, attempt, candidates_version, state, "
                           "response, raw_pick, resolved_pick, done_at) VALUES (?, ?, ?, 'DONE', ?, ?, ?, ?)",
                           (*key, text, raw_pick, resolved_pick, now))
            else:
                db.execute(f"UPDATE first_result SET state = 'DONE', response = ?, raw_pick = ?, "
                           f"resolved_pick = ?, done_at = ? WHERE {_WHERE}",
                           (text, raw_pick, resolved_pick, now, *key))
        return json.loads(text)

    def release(self, key, owner):
        """잡은 것을 놓는다 — 실패했을 때. 다음 시도가 임대를 기다리지 않게. 남의 것은 못 놓는다."""
        with self._tx() as db:
            db.execute(f"DELETE FROM first_result WHERE {_WHERE} AND state = 'CLAIMED' AND owner = ?",
                       (*key, owner))
