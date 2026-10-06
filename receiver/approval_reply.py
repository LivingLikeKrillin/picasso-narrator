"""승인 응답 읽기 — picasso `ADR 44`, `BOUNDARY.md` §6.

**거절은 오류가 아니다.** 전부 200 으로 오고, 하위 범주는 `refusal` 열거값으로 갈린다.
산문 사유는 사람이 읽을 것이지 기계가 대조할 것이 아니다 — 문장은 바뀌고, 바뀌면
조용히 안 걸린다.
"""

from dataclasses import dataclass, field

OK = 200
APPROVED = "APPROVED"

#: 이 계층이 읽을 줄 아는 승인 API 표면의 버전. ⛔ **둘을 받는다** (2026-09-22).
#:
#: picasso 가 `ADR 45` 로 버전을 2 로 올렸다. **응답의 모양은 안 바뀌었고** 늘어난 것은
#: `refusal` 이 들 수 있는 값이다(`REVOKED` 신설). 상대 저장소가 버전을 올린 이유도 그것이다 —
#: 「칸이 느는 것과 달리 refusal 로 분기하는 코드는 모르는 값을 만나므로 그 자리만 판을
#: 보면 된다」. **이 계층에는 그 분기가 없다.** 값을 읽어 승인 로그에 적을 뿐이라 둘 다 읽힌다.
#:
#: ⛔ **셋을 받는다** (2026-10-01, picasso `ADR 46`). 같은 자리에 다시 온 승인이 `CONSUMED` 와
#: `NO_PROPOSAL` 로 갈렸고, 거절 답에 `consumed` 칸이 생겼다 — 소모면 누가 · 언제 · 어느 실행으로 ·
#: 무엇을 보냈는지의 기록, 다른 거절이면 `null`, 허락에는 없다. 이 계층은 그 기록을 승인 로그에 옮겨 적는다.
#:
#: ⛔ **넷을 받는다** (2026-10-02, picasso `ADR 48` 머지 전 알림). 모든 답에 답을 낸 미들웨어 인스턴스(`instanceId`)가
#: 붙고 — `executionId` 가 인스턴스 안의 셈이라 둘을 짝지어야 시도가 갈린다 — 허락의 걸음과 소모 기록의 걸음마다
#: 단위 식별자(`unitId`)가 붙는다. 거절 값과 `consumed` 칸의 규칙은 버전 3 그대로다. 이 계층은 인스턴스를 승인 로그에 옮겨 적는다.
SCHEMA_VERSIONS = ("1", "2", "3", "4")
CONSUMED = "CONSUMED"
#: `consumed` 칸을 늘 싣는 버전들(`ADR 46` 부터).
WITH_CONSUMED = ("3", "4")


class ApprovalRefused(Exception):
    """승인 API 표면이 요청을 **못 읽었다.**

    **「자격 없음」이 아니다.** 400 은 내가 잘못 보낸 것이고, 섞으면 내 결함이
    자동 승인 자격 판정 결과로 기록된다 — 그러면 승인 등록 목록을 고치러 가게 된다.
    """


@dataclass(frozen=True)
class Outcome:
    granted: bool
    #: 거절의 하위 범주. 허락이면 `None`. **후속 조치가 여기서 갈린다.**
    refusal: str = None
    #: 사람이 읽을 사유. 대조하지 않는다.
    reason: str = ""
    #: 허락일 때 값이 채워져 돌아온 걸음. **이 계층이 지어낸 값은 없다.**
    steps: list = field(default_factory=list)
    #: 어느 버전의 승인 엔드포인트가 답했나. ⚠ **둘을 말없이 받으면 기록에서 둘이 같아진다** —
    #: `REVOKED` 를 낼 수 있는 승인 엔드포인트와 못 내는 승인 엔드포인트가 섞이고, 그러면 「안 왔다」와
    #: **「올 수 없었다」**가 접힌다. 오늘 이 저장소가 세 번 데인 자리와 같은 모양이다.
    schemaVersion: str = ""
    #: 버전 3 의 소모 기록 — `CONSUMED` 일 때만 찬다. 「누가 먼저 눌렀나」가 사후 검토의 재료다(`ADR 46`).
    consumed: dict = None
    #: 버전 4 의 답한 미들웨어 인스턴스(`ADR 48`). 버전 3 까지는 `None` — 그 칸이 생기기 전이다.
    instanceId: str = None
    #: 허락이 연 실행. 인스턴스 안의 셈이라 `instanceId` 와 짝지어야 시도가 갈린다(인계본 승인 절, 2026-10-03).
    #: 거절이면 `None` — 소모 기록의 실행은 `consumed` 안에 있다.
    executionId: str = None


def read_outcome(status, body):
    """승인 응답 하나를 하위 범주로 옮긴다."""
    if status != OK:
        # 못 닿은 전송은 `error` 가 아니라 `detail` 로 온다(`explainer/transport.py`). 사유를
        # 안 실으면 「못 닿았다」와 「내가 잘못 보냈다」가 같은 문장이 된다.
        raise ApprovalRefused(f"{status}: {body.get('error') or body.get('detail')}")
    found = body.get("schemaVersion")
    if found not in SCHEMA_VERSIONS:
        raise ApprovalRefused(
            f"읽을 줄 아는 판은 {list(SCHEMA_VERSIONS)} 인데 {found!r} 가 왔다")
    instance = None
    if found == "4":
        # 버전 4 를 밝힌 답은 허락이든 거절이든 인스턴스를 싣는다. 없으면 버전 4 의 몸이 아니다 — 문 앞에서 막는다
        instance = body.get("instanceId")
        if not isinstance(instance, str) or not instance:
            raise ApprovalRefused(f"판 4 답인데 instanceId 가 없다: {instance!r}")
    if body.get("outcome") == APPROVED:
        steps = list(body.get("steps") or [])
        if found == "4":
            _units("허락의 걸음", steps)
        return Outcome(granted=True, steps=steps, schemaVersion=found, instanceId=instance,
                       executionId=body.get("executionId"))
    consumed = None
    if found in WITH_CONSUMED:
        # 버전 3 부터 거절은 그 칸을 늘 싣는다. 없거나 하위 범주와 안 맞으면 그 버전의 몸이 아니다 — 문 앞에서 막는다
        if "consumed" not in body:
            raise ApprovalRefused(f"판 {found} 거절인데 consumed 칸이 없다")
        consumed = body["consumed"]
        fits = isinstance(consumed, dict) if body.get("refusal") == CONSUMED else consumed is None
        if not fits:
            raise ApprovalRefused(
                f"판 {found} 의 consumed 칸이 거절 갈래와 안 맞는다: {body.get('refusal')!r} · {type(consumed).__name__}")
        if found == "4" and consumed is not None:
            _units("소모 기록의 걸음", consumed.get("steps") or [])
    return Outcome(
        granted=False,
        refusal=body.get("refusal"),
        reason=body.get("reason", ""),
        schemaVersion=found,
        consumed=consumed,
        instanceId=instance,
    )


def _units(where, steps):
    """버전 4 의 걸음마다 단위 식별자가 있나 — 없으면 버전 4 의 몸이 아니다."""
    missing = [i for i, step in enumerate(steps) if not (isinstance(step, dict) and step.get("unitId"))]
    if missing:
        raise ApprovalRefused(f"판 4 의 {where}에 unitId 가 없다: {missing}")
