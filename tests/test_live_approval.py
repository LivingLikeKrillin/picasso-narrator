"""승인 창구에 실제로 걸어 보는 시험.

**창구가 없으면 건너뛴다.** 기본 시험군은 픽스처로 돌아야 한다. 띄우는 법은
picasso 저장소에서:

    ./gradlew :picasso:runApprovalHost --args="--port 8770 --seconds 900"
"""

import httpx
import pytest

from explainer.transport import http_transport
from receiver.approval import try_approve
from receiver.approval_reply import read_outcome

URL = "http://127.0.0.1:8770/approvals"

# **APPROVED 는 여기 없다.** 허락이 제안을 소모하므로 새로 띄운 입에서만 한 번
# 되고, 두 번째부터 NO_PROPOSAL 이다. 시험에 넣으면 순서와 재실행에 흔들린다 —
# 그 갈래는 `tests/fixtures/approvals/01-approved.json` 이 든다.

pytestmark = pytest.mark.live


def _approve(request):
    status, body = http_transport("POST", URL, {"Content-Type": "application/json"}, request)
    # ⛔ **Outcome 을 통째로 돌려준다**(2026-09-22). 전에는 갈래를 산문 칸에 실어
    # 보냈고, 아래 단언이 `reason == refusal` 로 그 모양을 못박고 있었다.
    return read_outcome(status, body)


def _search(robot, order):
    return {
        "searchId": f"live-{robot}",
        "robotId": robot,
        "jobOrderId": order,
        "outcome": "FOUND",
        "steps": [{"skillType": "pick_place"}],
    }


@pytest.fixture(autouse=True)
def _host_up():
    try:
        httpx.post(URL, json={}, timeout=3)
    except httpx.HTTPError:
        pytest.skip("승인 창구가 안 떠 있다 — runApprovalHost 로 띄운다")


@pytest.mark.parametrize(
    "robot, order, refusal",
    [
        ("hum-04", "PATROL-WITHHELD", "WITHHELD"),
        ("hum-05", "PATROL-OUT-OF-SCOPE", "ROBOT_OUT_OF_SCOPE"),
        ("hum-03", "PATROL-NO-REMEDY", "NO_PROPOSAL"),
    ],
)
def test_거절이_갈래로_돌아온다(robot, order, refusal):
    """**세 거절이 다 다른 값이다.** 다음 행동이 다르므로 갈려야 한다 —
    가려진 것은 사람의 진단을 기다리고, 범위 밖은 선언을 고쳐야 하고,
    제안 없음은 애초에 승인할 것이 없다."""
    result = try_approve(_search(robot, order), approve=_approve)

    assert result.granted is False
    assert result.refusal == refusal


@pytest.mark.parametrize(
    "approver, refusal",
    [
        ("narrator-1", "ROBOT_OUT_OF_SCOPE"),
        ("narrator-2", "NOT_DECLARED"),
        ("narrator-3", "EXPIRED"),
        ("narrator-4", "REVOKED"),
    ],
)
def test_같은_자리에서_승인자만_바꾸면_넷이_갈린다(approver, refusal):
    """⛔ **셋만 본 것은 구동기가 승인자를 하나만 세워 뒀기 때문이다** (picasso `ADR 45`).

    이 층은 「실물에서 본 값이 셋」이라 적고 **「셋 중 어느 것도 강등을 안 가른다」**고
    요청을 보냈다. 그런데 거절 어휘에는 값이 열넷 있었고 그중 둘(`NOT_DECLARED`·
    `EXPIRED`)이 **이미 와이어로 나가고 있었다.** 관측은 맞았고 **일반화가 틀렸다** —
    이 실물 시험이 승인자 하나만 걸었으므로, 시험이 덮은 범위가 내가 생각한 것보다 좁았다.

    **칸은 있는데 시나리오가 안 채운 자리**이고, 오늘 이 저장소가 제 대장에서 세 번 본
    것과 같은 모양이다. 그래서 자리를 넓히는 것으로 고친다.

    거절은 제안을 소모하지 않으므로 **자리 하나로 넷을 다 보고 순서도 상관없다.**
    """
    result = try_approve(_search("hum-05", "PATROL-OUT-OF-SCOPE"), approve=_approve,
                         approver_id=approver)

    assert result.granted is False
    assert result.refusal == refusal
    assert result.schemaVersion == "2"
