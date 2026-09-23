"""승인 응답 읽기 — picasso `ADR 44`, `BOUNDARY.md` §6.

**거절은 오류가 아니다.** 전부 200 으로 오고, 갈래는 `refusal` 열거값으로 갈린다.
산문 사유는 사람이 읽을 것이지 기계가 대조할 것이 아니다 — 문장은 바뀌고, 바뀌면
조용히 안 걸린다.
"""

from dataclasses import dataclass, field

OK = 200
APPROVED = "APPROVED"

#: 이 층이 읽을 줄 아는 승인 표면의 판. ⛔ **둘을 받는다** (2026-09-22).
#:
#: picasso 가 `ADR 45` 로 판을 2 로 올렸다. **응답의 모양은 안 바뀌었고** 늘어난 것은
#: `refusal` 이 들 수 있는 값이다(`REVOKED` 신설). 저쪽이 판을 올린 이유도 그것이다 —
#: 「칸이 느는 것과 달리 refusal 로 분기하는 코드는 모르는 값을 만나므로 그 자리만 판을
#: 보면 된다」. **이 층에는 그 분기가 없다.** 값을 읽어 대장에 적을 뿐이라 둘 다 읽힌다.
SCHEMA_VERSIONS = ("1", "2")


class ApprovalRefused(Exception):
    """승인 표면이 요청을 **못 읽었다.**

    **「자격 없음」이 아니다.** 400 은 내가 잘못 보낸 것이고, 섞으면 내 결함이
    자격 판정 결과로 기록된다 — 그러면 선언 목록을 고치러 가게 된다.
    """


@dataclass(frozen=True)
class Outcome:
    granted: bool
    #: 거절의 갈래. 허락이면 `None`. **다음 행동이 여기서 갈린다.**
    refusal: str = None
    #: 사람이 읽을 사유. 대조하지 않는다.
    reason: str = ""
    #: 허락일 때 값이 채워져 돌아온 걸음. **이 층이 지어낸 값은 없다.**
    steps: list = field(default_factory=list)
    #: 어느 판의 창구가 답했나. ⚠ **둘을 말없이 받으면 기록에서 둘이 같아진다** —
    #: `REVOKED` 를 낼 수 있는 창구와 못 내는 창구가 섞이고, 그러면 「안 왔다」와
    #: **「올 수 없었다」**가 접힌다. 오늘 이 저장소가 세 번 데인 자리와 같은 모양이다.
    schemaVersion: str = ""


def read_outcome(status, body):
    """승인 응답 하나를 갈래로 옮긴다."""
    if status != OK:
        # 못 닿은 전송은 `error` 가 아니라 `detail` 로 온다(`explainer/transport.py`). 사유를
        # 안 실으면 「못 닿았다」와 「내가 잘못 보냈다」가 같은 문장이 된다.
        raise ApprovalRefused(f"{status}: {body.get('error') or body.get('detail')}")
    found = body.get("schemaVersion")
    if found not in SCHEMA_VERSIONS:
        raise ApprovalRefused(
            f"읽을 줄 아는 판은 {list(SCHEMA_VERSIONS)} 인데 {found!r} 가 왔다")
    if body.get("outcome") == APPROVED:
        return Outcome(granted=True, steps=list(body.get("steps") or []),
                       schemaVersion=found)
    return Outcome(
        granted=False,
        refusal=body.get("refusal"),
        reason=body.get("reason", ""),
        schemaVersion=found,
    )
