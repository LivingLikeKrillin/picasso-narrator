"""이 층이 본 사건 안에서의 재발 — `BOUNDARY.md` §4 「사건 이력」.

**세는 것이지 판정하는 것이 아니다.** 같은 기체·같은 분류(그리고 같은 자리·같은 분류)가
이 층이 본 것 안에서 몇 번 있었나를 센다. 해석은 문서의 것이고 여기서 하지 않는다 — 수를
실으면 근거가 그것을 받는다.

⛔ **코퍼스의 해석이 하나가 아니다 (2026-09-20 실측).** 두 문서가 같은 첫 구절로 다른 결론을
낸다 — SOP-05 §6 은 「한 번은 사건이고, 반복은 **환경의 문제**다」, SOP-04 §4 는 「한 번은
사건이고, 반복은 **동선 설계의 문제**다」. 어느 쪽인지는 실패 분류가 정하고 그 표는 각 문서의
§2 에 있다. **그러니 이 층이 수에 말을 붙이면 둘 중 하나를 고르는 것이 되고, 그것이 판정이다.**
수만 싣고 고르지 않는다.

**이 층이 보태는 유일한 사실이다.** 번들에 없고 화면에도 없다. 그래서 이름에 「본 것」이
들어간다(`recurrenceSeen`) — 0 은 「없었다」가 아니라 **「이 층이 본 것 중에는 없다」**다.

**같은 사건의 재실행은 재발이 아니다.** `digest` 는 시드와 가상 시계에서 나오는 결정적
값이라 같은 시나리오를 다시 돌리면 그대로 반복된다(§3.4). 그래서 `digest` 가 다른 것만
세고, 같은 `digest` 는 한 번만 센다. **현재 사건과 같거나 뒤의 것은 안 센다** — 재발은
앞에 있었던 것이다.

⛔ **같은 시각을 「앞」으로 세면 둘이 서로를 센다 (2026-09-20 실측).** `at` 은 picasso 의
가상 시계이고 초 단위라 한 초에 사건이 여럿 들어올 수 있다(픽스처의 `at` 은 이미 1초 간격으로
붙어 있다). 부등호가 엄격하면 같은 초의 두 사건이 **서로를 앞선 사건으로 세어 둘 다 1 을
싣는다** — 먼저 난 쪽에게는 거짓이고, 그 거짓은 **미래에 대한 것**이다. 그래서 같으면 안 센다.
덜 세는 쪽으로 틀린다.
"""

#: 재발을 가르는 데 필요한 칸. 이것만 기록에 남긴다 — 번들 전체를 다시 적을 이유가 없다.
SUBJECT_KEYS = ("robotId", "failureClass", "unitId", "at", "digest")


def subject(bundle):
    """번들에서 주체만. **없는 칸은 안 싣는다** — 널을 값으로 바꾸지 않는다."""
    return {key: bundle[key] for key in SUBJECT_KEYS if bundle.get(key) is not None}


def count_recurrence(current, prior):
    """`current` 앞에 같은 기체·같은 분류 / 같은 자리·같은 분류가 몇 번 있었나.

    :param prior: 주체 사전들 — 저장소가 본 것과 지금 한 벌의 것을 합친 목록.
    :returns: ``{"sameRobotSameClass": n, "sameUnitSameClass": m}``
    """
    me = subject(current)
    counted = set()
    same_robot = same_unit = 0
    for other in prior:
        digest = other.get("digest")
        if not digest or digest == me.get("digest") or digest in counted:
            continue
        if other.get("failureClass") != me.get("failureClass"):
            continue
        if me.get("at") and other.get("at") and other["at"] >= me["at"]:
            continue
        counted.add(digest)
        if other.get("robotId") == me.get("robotId"):
            same_robot += 1
        if other.get("unitId") and other.get("unitId") == me.get("unitId"):
            same_unit += 1
    return {"sameRobotSameClass": same_robot, "sameUnitSameClass": same_unit}
