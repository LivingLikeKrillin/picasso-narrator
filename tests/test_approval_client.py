"""승인 응답을 읽는다 — picasso `ADR 44`. 실물 응답으로 고정한다."""

import pytest

from receiver.approval_reply import ApprovalRefused, read_outcome


def test_거절은_열거값으로_갈린다(approval):
    """**산문을 대조하지 않는다.** 사유 문장은 바뀌고, 바뀌면 조용히 안 걸린다.
    거절마다 다음 행동이 다르므로 값으로 봐야 갈린다."""
    assert read_outcome(*approval("02-withheld")).refusal == "WITHHELD"
    assert read_outcome(*approval("03-out-of-scope")).refusal == "ROBOT_OUT_OF_SCOPE"
    assert read_outcome(*approval("04-no-proposal")).refusal == "NO_PROPOSAL"


def test_거절은_오류가_아니다(approval):
    """전부 200 이다. 오류로 받으면 「자격 없음」과 「시스템 고장」이 같아진다."""
    status, _ = approval("02-withheld")

    assert status == 200
    assert read_outcome(*approval("02-withheld")).granted is False


def test_허락에는_값이_채워진_걸음이_온다(approval):
    """**내가 지어낸 값이 하나도 없다.** `destination` 은 사람의 선언에서,
    `object_id` 는 기체의 관측에서 온다(ADR 44)."""
    result = read_outcome(*approval("01-approved"))

    assert result.granted is True
    assert result.refusal is None
    assert result.steps[0]["parameters"] == {
        "destination": "DROP-01",
        "object_id": "SEQ-IN-02.BIN-A",
    }


def test_못_읽는_요청은_오류다(approval):
    """400 은 「자격 없음」이 아니라 **내가 잘못 보낸 것**이다. 섞으면 내 결함이
    자격 판정 결과로 기록된다."""
    with pytest.raises(ApprovalRefused):
        read_outcome(*approval("05-bad-request"))


def test_판_둘을_읽고_어느_판이_답했는지_적는다(approval):
    """⛔ **picasso 가 판을 2 로 올렸다** (`ADR 45` · 2026-09-22).

    응답의 **모양은 안 바뀌었고** `refusal` 이 들 수 있는 값이 늘었다(`REVOKED` 신설).
    판 하나만 받고 있으면 이 층은 **새 입의 답을 전부 거부한다** — 고치기 전이 그랬다.

    **어느 판이 답했는지도 같이 적는다.** 둘을 말없이 받으면 `REVOKED` 를 낼 수 있는
    창구와 못 내는 창구가 대장에서 같아지고, 그러면 「철회가 아니었다」와 **「철회를 말할 수
    없는 창구였다」**가 접힌다.

    ⚠ **이 판 2 입력은 내가 지은 것이다.** 붙잡아 둔 픽스처는 전부 판 1 이고 판 2 의
    실물 응답은 아직 못 받았다 — 저쪽 창구를 띄워야 받는다. 그러니 이 시험이 말하는 것은
    **「이렇게 오면 이렇게 읽는다」**이지 「저쪽이 이렇게 보낸다」가 아니다. 뒤쪽은
    `test_live_approval.py` 가 실물로 볼 일이다.
    """
    revoked = read_outcome(200, {"schemaVersion": "2", "outcome": "REFUSED",
                                 "refusal": "REVOKED", "reason": "회수됨"})

    assert revoked.refusal == "REVOKED"
    assert revoked.schemaVersion == "2"
    assert read_outcome(*approval("02-withheld")).schemaVersion == "1"


def test_모르는_판은_그대로_거부한다():
    """**판을 넓힌 것이지 안 보는 것이 아니다.** 모르는 판을 읽으면 그 뒤의 모든 칸이
    추측이 된다."""
    with pytest.raises(ApprovalRefused):
        read_outcome(200, {"schemaVersion": "3", "outcome": "REFUSED", "refusal": "REVOKED"})


def test_선언_쪽_갈래_넷이_판_2_실물로_갈린다(approval):
    """⛔ **`ADR 45` 뒤의 실물이다** (2026-09-22 붙잡음). 위 판 1 픽스처는 그대로 둔다 —
    갈린 것은 어휘이지 옛 응답이 아니다.

    **자리 하나에 승인자만 바꿔 넷을 본다.** 전에 셋만 본 것은 구동기가 승인자를 하나만
    세워 뒀고 **내 실물 시험도 그 하나만 걸고 있었기** 때문이다. 다음 행동이 넷 다 다르다.
    """
    got = {n: read_outcome(*approval(n)) for n in
           ("06-out-of-scope-v2", "07-not-declared-v2", "08-expired-v2", "09-revoked-v2")}

    assert got["06-out-of-scope-v2"].refusal == "ROBOT_OUT_OF_SCOPE"   # 범위를 넓힌다
    assert got["07-not-declared-v2"].refusal == "NOT_DECLARED"         # 선언을 올린다
    assert got["08-expired-v2"].refusal == "EXPIRED"                   # 갱신한다
    assert got["09-revoked-v2"].refusal == "REVOKED"                   # 사후 검토로 간다
    assert {o.schemaVersion for o in got.values()} == {"2"}


def test_판을_안_밝힌_몸은_판_1_이_아니라_거부다():
    """⛔ **셋째 값이 있다** — picasso 가 짚었다(2026-09-22).

    「판 1 이 답했다」와 **「판을 못 읽었다」**를 접으면, `ADR 45` 가 갈라 준 넷이 **한 층
    위에서 다시 접힌다.** 판 1 을 아는 입은 `schemaVersion` 을 실어 보내므로, 그 칸이 아예
    없는 몸은 판 1 이 아니라 **모르는 몸**이다. 문 앞에서 막는다.

    ⚠ 대장의 빈 칸은 또 다른 셋째다 — **그 칸이 생기기 전에 적힌 줄**이지 「판을 못 읽었다」가
    아니다. 옛 줄을 되읽으면 `""` 가 나오고, 그것을 `"1"` 로 읽으면 안 된다.
    """
    with pytest.raises(ApprovalRefused):
        read_outcome(200, {"outcome": "REFUSED", "refusal": "REVOKED"})


def test_못_읽는_몸은_거절이_아니라_사백이다(approval):
    """⛔ **둘을 접으면 「거절당했다」와 「내가 잘못 보냈다」가 대장에서 같아진다.**

    거절은 전부 200 이고 정상 응답이다(`ADR 44`). 400 은 **내가 잘못 보낸 것**이고,
    섞으면 내 결함이 자격 판정 결과로 기록돼 사람을 **선언 목록을 고치러** 보낸다.
    picasso 가 판 2 를 내면서 이 둘을 같이 붙잡아 두라고 짚었다.
    """
    status, _ = approval("13-bad-request-v2")
    assert status == 400

    with pytest.raises(ApprovalRefused):
        read_outcome(*approval("13-bad-request-v2"))

    # 거절은 그 옆에서 200 으로 선다. 같은 입, 다른 일이다.
    assert approval("09-revoked-v2")[0] == 200


def test_창구_클라이언트는_전송과_읽기를_잇는다(approval):
    """`nexus_client` 와 같은 모양이다 — 전송은 주입받고, 응답은 `read_outcome` 이 갈래로
    옮긴다. 보내는 것은 요청 그대로이고 헤더는 JSON 하나뿐이다."""
    from receiver.approval import approval_client

    sent = []

    def transport(method, url, headers, payload):
        sent.append((method, url, headers, payload))
        return approval("09-revoked-v2")

    approve = approval_client("http://127.0.0.1:8770/approvals", transport)
    outcome = approve({"approverId": "narrator-4"})

    assert outcome.refusal == "REVOKED"
    assert sent == [("POST", "http://127.0.0.1:8770/approvals",
                     {"Content-Type": "application/json"}, {"approverId": "narrator-4"})]


def test_못_닿은_전송은_사유를_들고_오류가_된다():
    """`http_transport` 는 끊긴 것을 599 와 `detail` 로 돌려준다. 그 사유가 오류 문장에
    없으면 「못 닿았다」와 「내가 잘못 보냈다」가 같은 문장으로 보인다."""
    with pytest.raises(ApprovalRefused) as caught:
        read_outcome(599, {"detail": "ConnectError: 거부됨", "llm_failure_reason": "unavailable"})

    assert "599" in str(caught.value)
    assert "ConnectError" in str(caught.value)
