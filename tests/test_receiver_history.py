"""이 층이 본 사건 안에서의 재발 — `BOUNDARY.md` §4 「사건 이력」."""

from receiver.export import read_export
from receiver.history import count_recurrence, subject


def _b(robot, cls, unit, at, digest):
    return {"robotId": robot, "failureClass": cls, "unitId": unit, "at": at, "digest": digest}


def test_같은_기체_같은_분류의_앞선_사건을_센다():
    """같은 자리(unitId)까지 같으면 따로 센다 — SOP-05 §6 이 「같은 구간에서 반복」을
    묻는다."""
    prior = [
        subject(_b("hum-04", "GRASP_FAILED", "RACK-204.S03", "2026-09-06T00:01:00Z", "d1")),
        subject(_b("hum-04", "GRASP_FAILED", "RACK-204.S04", "2026-09-06T00:02:00Z", "d2")),
    ]
    now = _b("hum-04", "GRASP_FAILED", "RACK-204.S03", "2026-09-06T00:03:00Z", "d3")

    assert count_recurrence(now, prior) == {"sameRobotSameClass": 2, "sameUnitSameClass": 1}


def test_같은_digest_는_재실행이지_재발이_아니다():
    """`digest` 는 시드와 가상 시계에서 나오는 결정적 값이라 같은 시나리오를 다시
    돌리면 그대로 반복된다(§3.4). 그것을 세면 재실행마다 재발이 는다."""
    same = _b("hum-04", "GRASP_FAILED", "RACK-204.S03", "2026-09-06T00:01:00Z", "d1")

    assert count_recurrence(same, [subject(same), subject(same)]) == {
        "sameRobotSameClass": 0, "sameUnitSameClass": 0,
    }


def test_뒤에_난_사건은_세지_않는다():
    """재발은 앞에 있었던 것이다."""
    later = subject(_b("hum-04", "GRASP_FAILED", "RACK-204.S03", "2026-09-06T00:09:00Z", "d9"))
    now = _b("hum-04", "GRASP_FAILED", "RACK-204.S03", "2026-09-06T00:03:00Z", "d3")

    assert count_recurrence(now, [later])["sameRobotSameClass"] == 0


def test_다른_분류는_세지_않는다():
    other = subject(_b("hum-04", "PAYLOAD_LOST", "RACK-204.S03", "2026-09-06T00:01:00Z", "d1"))
    now = _b("hum-04", "GRASP_FAILED", "RACK-204.S03", "2026-09-06T00:03:00Z", "d3")

    assert count_recurrence(now, [other]) == {"sameRobotSameClass": 0, "sameUnitSameClass": 0}


def test_실물_두_벌에는_재발이_없다(export_dir):
    """⛔ **픽스처 두 벌에는 같은 기체·같은 분류가 없다**(2026-09-20 실측). 두 벌은
    digest 까지 같아 재실행이다. 그래서 이 시험은 0 을 확인하고, 재발이 있는 시나리오는
    picasso 에 요청해 둔 상태다(`correspondence/`)."""
    incidents = (
        read_export(export_dir("run-1")).incidents + read_export(export_dir("run-2")).incidents
    )
    prior = [subject(b) for b in incidents]

    assert all(
        count_recurrence(b, prior) == {"sameRobotSameClass": 0, "sameUnitSameClass": 0}
        for b in incidents
    )


def test_같은_시각의_사건은_서로의_앞이_아니다():
    """⛔ **`at` 은 가상 시계의 초 단위다** — 한 초에 사건이 여럿 들어올 수 있다. 같은 초를
    「앞」으로 세면 둘이 **서로를 앞선 사건으로 세어 둘 다 1 을 싣는다.** 먼저 난 쪽에게는
    거짓이고 그 거짓은 미래에 대한 것이다. 덜 세는 쪽으로 틀린다."""
    first = _b("hum-04", "GRASP_FAILED", "RACK-204.S03", "2026-09-06T00:01:00Z", "d1")
    second = _b("hum-04", "GRASP_FAILED", "RACK-204.S03", "2026-09-06T00:01:00Z", "d2")

    assert count_recurrence(first, [subject(second)]) == {
        "sameRobotSameClass": 0, "sameUnitSameClass": 0,
    }
    assert count_recurrence(second, [subject(first)]) == {
        "sameRobotSameClass": 0, "sameUnitSameClass": 0,
    }
