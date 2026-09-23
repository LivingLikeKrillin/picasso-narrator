"""승인 시도 — `BOUNDARY.md` §6, `SEQUENCES.md` 불변식 2.

**이 층은 자격을 판단하지 않는다.** 시도하고, 허락이든 거부든 받아 적는다.
스스로 판단하면 그 순간 우회가 성립한다.
"""

import json
from dataclasses import dataclass, field

from receiver.approval_reply import read_outcome

FOUND = "FOUND"
AGENT = "AGENT"


class LedgerEmpty(Exception):
    """대장이 비어 있어 **「없었다」와 「모른다」가 같아지는 자리.**

    ⛔ **적어 두는 것으로는 안 걸렸다**(2026-09-22). 주석에도 `BOUNDARY.md` 에도
    「읽는 쪽이 대장의 길이를 함께 봐야 한다」고 적어 뒀지만 **그건 읽는 쪽이 읽어야
    걸린다.** 거짓을 돌려주면 그대로 「전에 허락된 적 없다」로 읽히고, 그 길은 사람을
    **선언 수정하러** 보낸다 — 강등된 뒤였으면 틀린 출구다.

    khala 가 같은 결함 한 벌을 고치며 보낸 처방이 이것이다: 값을 적는 것만으로는
    모자라고 **그 값이 참인 판이 하나라도 있어야 한다.** 저쪽은 요청이 0 건인 판을
    스스로 접게 했다. **답할 수 없으면 답하지 않는다.**
    """


@dataclass(frozen=True)
class Attempt:
    """시도 한 번의 결과. **거부도 정상 응답이다.**"""

    searchId: str
    granted: bool
    reason: str = ""
    #: 거절의 갈래. 허락이면 `None`. **다음 행동이 여기서 갈린다.**
    refusal: str = None
    #: 무엇에 대한 시도였나. **`granted_before` 가 이 둘로 돌아본다.**
    robotId: str = ""
    sawSkillTypes: list = field(default_factory=list)
    #: 어느 판의 승인 창구가 답했나. ⛔ **`REVOKED` 를 낼 수 있는 창구와 못 내는 창구를
    #: 가른다**(판 2 가 그 값을 냈다). 안 적으면 「철회가 아니었다」와 「철회를 말할 수
    #: 없는 창구였다」가 대장에서 같아진다.
    schemaVersion: str = ""
    #: 어느 구동의 시도인가. **같은 시드의 재구동은 `searchId` 가 그대로 반복된다**
    #: (`BOUNDARY.md` §3.4). 설명의 열쇠가 `(runId, digest)` 인 것과 같은 이유로 여기도
    #: 구동이 앞자리다. ⚠ **빈 칸은 이 칸이 생기기 전(2026-09-22)에 적힌 줄**이고 「모른다」와
    #: 다르다 — 옛 줄은 새 구동의 같은 줄을 막지 않는다.
    runId: str = ""


def candidates(searches):
    """승인을 시도할 수 있는 줄. **자격이 있는 줄이 아니라 부를 수 있는 줄이다.**

    - `WITHHELD` 는 `steps` 키가 없다. 걸음을 모르면 부를 수가 없고, 다른 자리에서
      찾아오면 그 순간 가림이 풀린다. **못 부르는 것이지 자격을 판단한 것이 아니다**
    - `NONE` 은 조치 자체가 없다. 시도할 것이 없는 것과 자격이 없는 것은 다르다
    """
    return [s for s in searches if s.get("outcome") == FOUND and s.get("steps")]


def pending(proposals, run_id, seen):
    """부를 수 있는 줄 중 **이 구동에서 아직 안 부른 것.**

    `seen` 은 대장의 `(runId, searchId)` 집합이다(`AttemptStore.seen`). **설명이 붙었는지는
    보지 않는다** — 설명은 사건 처리의 옆이지 앞이 아니다(`SEQUENCES.md` 불변식 3). 설명의
    커서로 고르면 설명이 늦을 때 승인도 늦고, 그 순간 LLM 이 운영 경로에 들어간 것이다.
    """
    return [s for s in proposals if (run_id, s["searchId"]) not in seen]


def try_approve(search, approve, approver_id="narrator-1", run_id=""):
    """승인을 시도한다. **보내는 것은 신원과 어느 조치인지뿐이다.**

    「나는 자격이 있다」를 실어 보내지 않는다 — 자격은 승인 API 가 선언 목록과
    대조해 정한다(불변식 2 · `ADR 43`).

    **값도 주문도 걸음도 실을 칸이 없다**(picasso `ADR 44`). 승인은 조치를 기술하지
    않고 **제안을 가리킨다** — 기술하면 그건 승인 표면이 아니라 접수 표면이고,
    이 층이 조치를 짜는 것이 된다. `sawSkillTypes` 는 대장에서 **본 것**이지
    무엇을 하라는 지시가 아니다.

    :param approve: `Outcome` 을 돌려주는 것 — `approval_reply.read_outcome` 의 산출을
        그대로 준다. 전송은 주입으로 받는다. 이 조각의 관심사가 아니고, 시험이 실물
        없이 물린다.

        ⛔ **전에는 `(granted, reason)` 두 칸이었다**(2026-09-22). 거절의 갈래를 실을
        자리가 없어 **산문 칸으로 샜고**, 실물 시험이 `reason == refusal` 로 그 모양을
        못박고 있었다. 산문은 바뀌는 날 조용히 안 걸린다. `Outcome` 을 통째로 받으면
        **잃을 자리가 없다.**
    """
    # ⛔ **보낸 것과 적는 것을 한 값에서 가져온다** (2026-09-22). 전에는 `sawSkillTypes`
    # 를 요청에만 지어 넣고 `Attempt` 에는 안 실어서, `granted_before` 가 되읽을 두 칸이
    # 늘 비었다 — **방금 허락된 건도 「전에 허락된 적 없다」로 돌아왔다.**
    saw = [s["skillType"] for s in search["steps"]]
    outcome = approve(
        {
            "approverId": approver_id,
            "approverKind": AGENT,
            "robotId": search["robotId"],
            "jobOrderId": search["jobOrderId"],
            "sawSkillTypes": saw,
        }
    )
    return Attempt(searchId=search["searchId"], granted=outcome.granted,
                   reason=outcome.reason, refusal=outcome.refusal,
                   robotId=search["robotId"], sawSkillTypes=saw,
                   schemaVersion=outcome.schemaVersion, runId=run_id)


class AttemptStore:
    """승인 시도의 대장. **추가만 한다.**

    ⛔ **§6.1 이 감사를 요구하는데 `Attempt` 를 버리고 있었다**(2026-09-19). 「이 층이
    승인한 건도 사후 검토 대상이며 이의율은 사람 승인과 따로 집계한다」고 적어 놓고
    적는 자리가 없었다. 버리면 사후 검토할 것이 없다.

    **거절도 적는다.** 거절은 오류가 아니라 정상 응답이고(`ADR 44`), 무엇이 왜
    거절됐는지가 §6.6 의 두 출구를 가르는 재료다.

    설명 대장과 **따로 둔다.** 열쇠가 다르고(사건은 `(runId, digest)`, 시도는 탐색 줄),
    적히는 순간도 다르다. 한 파일에 섞으면 둘 중 하나를 세는 일이 매번 거르기가 된다.
    """

    def __init__(self, path):
        self.path = path

    def append(self, attempt):
        line = json.dumps(_encode(attempt), ensure_ascii=False, sort_keys=True)
        with open(self.path, "a", encoding="utf-8", newline="\n") as out:
            out.write(line + "\n")

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as src:
                return [_decode(json.loads(l)) for l in src if l.strip()]
        except FileNotFoundError:
            return []

    def seen(self):
        """이미 부른 `(구동, 줄)`. 이것이 시도의 커서다 — 설명의 커서가 `RecordStore.seen` 인
        것과 같은 이유로 **대장이 곧 커서다**(`BOUNDARY.md` §3.2.1). 따로 두면 둘이 갈릴 때
        어느 쪽이 참인지 판정할 수 없다."""
        return {(a.runId, a.searchId) for a in self.load()}

    def granted_before(self, robotId, skill_types):
        """이 (기체, 조치 유형)에 **전에 허락이 있었나.**

        **P5 의 재료였다.** 자격이 강등되면 다음 시도가 거절되는데, 그 거절이 강등
        때문인지 처음부터 선언에 없었는지 **응답으로는 안 갈렸다**(§6.8).

        ⛔ **2026-09-22 에 갈렸다.** picasso 가 `ADR 45` 로 `REVOKED` 를 냈고, 이제
        `NOT_DECLARED`·`REVOKED`·`EXPIRED`·`ROBOT_OUT_OF_SCOPE` 넷이 다음 행동을 가른다.
        **그래서 이 되읽기는 추론의 재료가 아니라 대조의 재료다** — 저쪽이 말한 것과
        이 대장이 본 것이 어긋나면 그 자리가 물어볼 자리다.

        ⚠ **여전히 안 갈리는 것이 하나 있다 — 범위 축소.** 「범위에서 빠졌다」와 「원래
        범위 밖이었다」가 둘 다 `ROBOT_OUT_OF_SCOPE` 로 온다(저쪽 §15.184 에 열려 있다).
        **거기서는 이 대장이 아직 유일한 재료다.** 그리고 여기서 답하는 것은 여전히
        **「전에 허락된 적 있나」** 하나뿐이다 — 판정은 이 층의 일이 아니다(`ADR 43`).

        ⛔ **대장이 비어 있으면 `LedgerEmpty` 다.** 거짓을 돌려주면 「없었다」와
        「모른다」가 같아진다 — 읽는 쪽에 맡기지 않고 여기서 멈춘다.
        """
        rows = self.load()
        if not rows:
            raise LedgerEmpty("대장이 비어 있다 — 「없었다」가 아니라 「모른다」다")
        want = set(skill_types)
        return any(
            a.granted and a.robotId == robotId and want <= set(a.sawSkillTypes)
            for a in rows
        )


def _encode(attempt):
    return {
        "searchId": attempt.searchId,
        "granted": attempt.granted,
        "reason": attempt.reason,
        "refusal": attempt.refusal,
        "robotId": attempt.robotId,
        "sawSkillTypes": list(attempt.sawSkillTypes),
        "schemaVersion": attempt.schemaVersion,
        "runId": attempt.runId,
    }


def _decode(row):
    return Attempt(
        searchId=row["searchId"],
        granted=row["granted"],
        reason=row.get("reason", ""),
        refusal=row.get("refusal"),
        robotId=row.get("robotId", ""),
        sawSkillTypes=row.get("sawSkillTypes") or [],
        # ⚠ **빈 칸은 「판 1」이 아니다.** 그 칸이 생기기 전(2026-09-22)에 적힌 줄이라는
        # 뜻이고, 「판을 못 읽었다」와도 다르다 — 판을 안 밝힌 몸은 문 앞에서 막힌다.
        # 셋을 접으면 `ADR 45` 가 갈라 준 넷이 한 층 위에서 다시 접힌다.
        schemaVersion=row.get("schemaVersion", ""),
        # ⚠ 위 `schemaVersion` 과 같은 셋째 값이다. 그 칸이 생기기 전에 적힌 줄은 빈 칸이다.
        runId=row.get("runId", ""),
    )


def approval_client(url, transport):
    """`try_approve` 에 넘길 `approve` 를 만든다. **전송은 주입받는다** — `nexus_client` 와
    같은 이유다. 이 조각의 관심사가 아니고, 그래야 시험이 실물 창구 없이 물린다.

    보내는 것은 요청 그대로이고 헤더는 JSON 하나뿐이다. 응답은 `read_outcome` 이 갈래로
    옮긴다 — 200 의 거절은 `Outcome` 으로, 400 과 못 닿음은 `ApprovalRefused` 로.
    """

    def approve(request):
        return read_outcome(*transport("POST", url, {"Content-Type": "application/json"}, request))

    return approve
