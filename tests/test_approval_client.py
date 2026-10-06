"""승인 응답을 읽는다 — picasso `ADR 44`. 실제 서비스 응답으로 고정한다."""

import pytest

from receiver.approval_reply import ApprovalRefused, read_outcome


def test_거절은_열거값으로_갈린다(approval):
    """**산문을 대조하지 않는다.** 사유 문장은 바뀌고, 바뀌면 조용히 안 걸린다.
    거절마다 후속 조치가 다르므로 값으로 봐야 갈린다."""
    assert read_outcome(*approval("02-withheld")).refusal == "WITHHELD"
    assert read_outcome(*approval("03-out-of-scope")).refusal == "ROBOT_OUT_OF_SCOPE"
    assert read_outcome(*approval("04-no-proposal")).refusal == "NO_PROPOSAL"


def test_거절은_오류가_아니다(approval):
    """전부 200 이다. 오류로 받으면 「자격 없음」과 「시스템 고장」이 같아진다."""
    status, _ = approval("02-withheld")

    assert status == 200
    assert read_outcome(*approval("02-withheld")).granted is False


def test_허락에는_값이_채워진_걸음이_온다(approval):
    """**내가 지어낸 값이 하나도 없다.** `destination` 은 사람의 승인 등록에서,
    `object_id` 는 로봇의 관측에서 온다(ADR 44)."""
    result = read_outcome(*approval("01-approved"))

    assert result.granted is True
    assert result.refusal is None
    assert result.steps[0]["parameters"] == {
        "destination": "DROP-01",
        "object_id": "SEQ-IN-02.BIN-A",
    }


def test_못_읽는_요청은_오류다(approval):
    """400 은 「자격 없음」이 아니라 **내가 잘못 보낸 것**이다. 섞으면 내 결함이
    자동 승인 자격 판정 결과로 기록된다."""
    with pytest.raises(ApprovalRefused):
        read_outcome(*approval("05-bad-request"))


def test_판_둘을_읽고_어느_판이_답했는지_적는다(approval):
    """⛔ **picasso 가 버전을 2 로 올렸다** (`ADR 45` · 2026-09-22).

    응답의 **모양은 안 바뀌었고** `refusal` 이 들 수 있는 값이 늘었다(`REVOKED` 신설).
    버전 하나만 받고 있으면 이 계층은 **새 입의 답을 전부 거부한다** — 고치기 전이 그랬다.

    **어느 버전이 답했는지도 같이 적는다.** 둘을 말없이 받으면 `REVOKED` 를 낼 수 있는
    승인 엔드포인트와 못 내는 승인 엔드포인트가 승인 로그에서 같아지고, 그러면 「철회가 아니었다」와 **「철회를 말할 수
    없는 창구였다」**가 접힌다.

    ⚠ **이 버전 2 입력은 내가 지은 것이다.** 붙잡아 둔 픽스처는 전부 버전 1 이고 버전 2 의
    실제 서비스 응답은 아직 못 받았다 — 상대 저장소 승인 엔드포인트를 띄워야 받는다. 그러니 이 테스트가 말하는 것은
    **「이렇게 오면 이렇게 읽는다」**이지 「저쪽이 이렇게 보낸다」가 아니다. 뒤쪽은
    `test_live_approval.py` 가 실제 서비스로 볼 일이다.
    """
    revoked = read_outcome(200, {"schemaVersion": "2", "outcome": "REFUSED",
                                 "refusal": "REVOKED", "reason": "회수됨"})

    assert revoked.refusal == "REVOKED"
    assert revoked.schemaVersion == "2"
    assert read_outcome(*approval("02-withheld")).schemaVersion == "1"


def test_모르는_판은_그대로_거부한다():
    """**버전을 넓힌 것이지 안 보는 것이 아니다.** 모르는 버전을 읽으면 그 뒤의 모든 칸이
    추측이 된다. (버전 3 이 서서 모르는 버전의 예를 4 로, 버전 4 가 서서 5 로 옮겼다, 2026-10-01 · 10-02.)"""
    with pytest.raises(ApprovalRefused):
        read_outcome(200, {"schemaVersion": "5", "outcome": "REFUSED", "refusal": "REVOKED", "consumed": None,
                           "instanceId": "mw-1"})


#: 버전 3 의 소모 기록 — 칸 이름은 picasso 인계본(2026-10-01)의 것이고 값은 이 테스트가 지었다.
CONSUMED_RECORD = {"approverId": "narrator-1", "approverKind": "AGENT", "at": "2026-09-06T00:00:01Z",
                   "wallClockAt": "2026-10-01T10:20:00Z", "executionId": "exec-1",
                   "steps": [{"skillType": "pick_place", "parameters": {"destination": "DROP-01"}}]}


def test_판_3_의_소모_거절은_누가_무엇을_보냈는지_싣는다(approval):
    """⛔ **picasso 가 버전을 3 으로 올렸다** (`ADR 46` · 2026-10-01).

    같은 자리에 다시 온 승인이 둘로 갈린다 — `CONSUMED`(이미 소모됐다)와 `NO_PROPOSAL`(이 프로세스가 뜬 뒤로
    제안이 선 적이 없다). 소모 거절은 **누가 · 언제 · 어느 실행으로 · 무엇을 보냈는지**를 `consumed` 칸에 싣고,
    다른 거절은 그 키를 빼지 않고 `null` 이며, 허락은 그 칸을 싣지 않는다. 버전 둘만 받고 있으면 이 계층은 상대 저장소가
    버전을 올린 순간 **모든 승인 답을 「못 읽음」으로 막는다.**

    **버전 3 을 밝힌 거절이 버전 3 의 모양이 아니면 문 앞에서 막는다** — 칸이 없거나, 소모인데 기록이 없거나,
    소모가 아닌데 기록이 있으면 그 몸의 다른 칸도 추측이 된다.

    ⚠ **이 버전 3 입력은 내가 지은 것이다**(버전 2 때와 같다). 칸 이름은 상대 저장소 인계본에서 왔고 실제 서비스 응답은 상대 저장소
    승인 엔드포인트를 띄워야 받는다. 이 테스트가 말하는 것은 「이렇게 오면 이렇게 읽는다」이다.
    """
    from receiver.approval import approval_client, try_approve

    body = {"schemaVersion": "3", "outcome": "REFUSED", "refusal": "CONSUMED", "reason": "이미 소모됐다",
            "consumed": CONSUMED_RECORD}
    consumed = read_outcome(200, body)
    assert (consumed.granted, consumed.refusal, consumed.consumed, consumed.schemaVersion) == (
        False, "CONSUMED", CONSUMED_RECORD, "3")
    other = read_outcome(200, {"schemaVersion": "3", "outcome": "REFUSED", "refusal": "NO_PROPOSAL", "reason": "",
                               "consumed": None})
    assert other.refusal == "NO_PROPOSAL" and other.consumed is None
    granted = read_outcome(200, {"schemaVersion": "3", "outcome": "APPROVED", "steps": CONSUMED_RECORD["steps"]})
    assert granted.granted is True and granted.consumed is None
    assert read_outcome(*approval("09-revoked-v2")).consumed is None, "판 2 에는 그 칸이 없다 — 생기기 전이다"

    for bad in ({"refusal": "NO_PROPOSAL"}, {"refusal": "CONSUMED", "consumed": None},
                {"refusal": "NO_PROPOSAL", "consumed": CONSUMED_RECORD}):
        with pytest.raises(ApprovalRefused):
            read_outcome(200, {"schemaVersion": "3", "outcome": "REFUSED", "reason": "", **bad})

    search = {"searchId": "search-1", "robotId": "hum-02", "jobOrderId": "PATROL-APPROVES",
              "steps": [{"skillType": "pick_place"}]}
    attempt = try_approve(search, approval_client("http://127.0.0.1:8770/approvals", lambda *sent: (200, body)),
                          run_id="run-1")
    assert (attempt.refusal, attempt.consumed, attempt.schemaVersion) == ("CONSUMED", CONSUMED_RECORD, "3")


#: 버전 4 의 걸음 — 걸음마다 단위 식별자(`remedy-{n}-{skillType}`, n 은 1부터)가 붙는다. 값은 이 테스트가 지었다.
STEPS_V4 = [{"skillType": "pick_place", "unitId": "remedy-1-pick_place", "parameters": {"destination": "DROP-01"}}]


def test_판_4_는_답한_인스턴스와_걸음의_단위를_싣는다():
    """⛔ **picasso 가 버전을 4 로 올린다** (`ADR 48` · 2026-10-02 머지 전 알림).

    모든 답(허락 · 거절)에 답을 낸 미들웨어 인스턴스(`instanceId`)가 붙는다 — `executionId` 가 인스턴스 안의 셈이라
    둘을 짝지어야 시도가 갈린다. 허락의 걸음과 소모 기록의 걸음마다 `unitId` 가 붙는다. 거절 값과 `consumed` 칸의
    규칙은 버전 3 그대로다. 버전 셋만 받고 있으면 이 계층은 상대 저장소가 버전을 올린 순간 **모든 승인 답을 「못 읽음」으로 막는다.**

    **버전 4 를 밝힌 몸이 버전 4 의 모양이 아니면 문 앞에서 막는다** — 인스턴스가 없거나, 걸음에 단위가 없거나, 버전 3 의
    `consumed` 규칙이 깨지면 그 몸의 다른 칸도 추측이 된다. 승인 로그는 인스턴스를 옮겨 적는다(사후 검토의 열쇠).

    ⚠ **이 버전 4 입력은 내가 지은 것이다**(버전 2 · 3 때와 같다). 칸 이름은 상대 저장소의 머지 전 알림에서 왔고, 머지 뒤 인계본
    문장으로 다시 대조한다.
    """
    from receiver.approval import approval_client, try_approve

    record = dict(CONSUMED_RECORD, steps=STEPS_V4)
    consumed = read_outcome(200, {"schemaVersion": "4", "outcome": "REFUSED", "refusal": "CONSUMED", "reason": "",
                                  "consumed": record, "instanceId": "mw-1"})
    assert (consumed.refusal, consumed.consumed, consumed.instanceId, consumed.schemaVersion) == (
        "CONSUMED", record, "mw-1", "4")
    granted = read_outcome(200, {"schemaVersion": "4", "outcome": "APPROVED", "executionId": "exec-1",
                                 "steps": STEPS_V4, "instanceId": "mw-1"})
    assert (granted.granted, granted.steps, granted.instanceId, granted.executionId) == (True, STEPS_V4, "mw-1", "exec-1")
    other = read_outcome(200, {"schemaVersion": "4", "outcome": "REFUSED", "refusal": "NOT_DECLARED", "reason": "",
                               "consumed": None, "instanceId": "mw-1"})
    assert other.consumed is None and other.instanceId == "mw-1"
    assert read_outcome(200, {"schemaVersion": "3", "outcome": "APPROVED", "steps": CONSUMED_RECORD["steps"]}
                        ).instanceId is None, "판 3 에는 그 칸이 없다 — 생기기 전이다"

    bare = [{"skillType": "pick_place"}]
    for bad in ({"outcome": "REFUSED", "refusal": "NOT_DECLARED", "consumed": None},
                {"outcome": "REFUSED", "refusal": "NOT_DECLARED", "consumed": None, "instanceId": ""},
                {"outcome": "APPROVED", "steps": STEPS_V4},
                {"outcome": "APPROVED", "steps": bare, "instanceId": "mw-1"},
                {"outcome": "REFUSED", "refusal": "CONSUMED", "consumed": dict(record, steps=bare), "instanceId": "mw-1"},
                {"outcome": "REFUSED", "refusal": "NOT_DECLARED", "instanceId": "mw-1"},
                {"outcome": "REFUSED", "refusal": "CONSUMED", "consumed": None, "instanceId": "mw-1"}):
        with pytest.raises(ApprovalRefused):
            read_outcome(200, {"schemaVersion": "4", "reason": "", **bad})

    search = {"searchId": "search-1", "robotId": "hum-02", "jobOrderId": "PATROL-APPROVES",
              "steps": [{"skillType": "pick_place"}]}
    body = {"schemaVersion": "4", "outcome": "APPROVED", "executionId": "exec-1", "steps": STEPS_V4, "instanceId": "mw-1"}
    attempt = try_approve(search, approval_client("http://127.0.0.1:8770/approvals", lambda *sent: (200, body)),
                          run_id="run-1")
    # 인계본(10-03): 시도는 (instanceId, executionId) 쌍으로 잇는다 — 승인 로그에 둘 다 있어야 쌍이 선다
    assert (attempt.granted, attempt.instanceId, attempt.executionId, attempt.schemaVersion) == (
        True, "mw-1", "exec-1", "4")


def test_선언_쪽_갈래_넷이_판_2_실물로_갈린다(approval):
    """⛔ **`ADR 45` 뒤의 실물이다** (2026-09-22 붙잡음). 위 버전 1 픽스처는 그대로 둔다 —
    갈린 것은 어휘이지 옛 응답이 아니다.

    **자리 하나에 승인자만 바꿔 넷을 본다.** 전에 셋만 본 것은 구동기가 승인자를 하나만
    세워 뒀고 **내 실제 서비스 테스트도 그 하나만 걸고 있었기** 때문이다. 후속 조치가 넷 다 다르다.
    """
    got = {n: read_outcome(*approval(n)) for n in
           ("06-out-of-scope-v2", "07-not-declared-v2", "08-expired-v2", "09-revoked-v2")}

    assert got["06-out-of-scope-v2"].refusal == "ROBOT_OUT_OF_SCOPE"   # 범위를 넓힌다
    assert got["07-not-declared-v2"].refusal == "NOT_DECLARED"         # 승인 등록을 올린다
    assert got["08-expired-v2"].refusal == "EXPIRED"                   # 갱신한다
    assert got["09-revoked-v2"].refusal == "REVOKED"                   # 사후 검토로 간다
    assert {o.schemaVersion for o in got.values()} == {"2"}


def test_판을_안_밝힌_몸은_판_1_이_아니라_거부다():
    """⛔ **셋째 값이 있다** — picasso 가 짚었다(2026-09-22).

    「판 1 이 답했다」와 **「판을 못 읽었다」**를 접으면, `ADR 45` 가 갈라 준 넷이 **한 계층
    위에서 다시 접힌다.** 버전 1 을 아는 입은 `schemaVersion` 을 실어 보내므로, 그 칸이 아예
    없는 몸은 버전 1 이 아니라 **모르는 몸**이다. 문 앞에서 막는다.

    ⚠ 승인 로그의 빈 칸은 또 다른 셋째다 — **그 칸이 생기기 전에 적힌 줄**이지 「판을 못 읽었다」가
    아니다. 옛 줄을 되읽으면 `""` 가 나오고, 그것을 `"1"` 로 읽으면 안 된다.
    """
    with pytest.raises(ApprovalRefused):
        read_outcome(200, {"outcome": "REFUSED", "refusal": "REVOKED"})


def test_못_읽는_몸은_거절이_아니라_사백이다(approval):
    """⛔ **둘을 접으면 「거절당했다」와 「내가 잘못 보냈다」가 승인 로그에서 같아진다.**

    거절은 전부 200 이고 정상 응답이다(`ADR 44`). 400 은 **내가 잘못 보낸 것**이고,
    섞으면 내 결함이 자동 승인 자격 판정 결과로 기록돼 사람을 **승인 등록 목록을 고치러** 보낸다.
    picasso 가 버전 2 를 내면서 이 둘을 같이 붙잡아 두라고 짚었다.
    """
    status, _ = approval("13-bad-request-v2")
    assert status == 400

    with pytest.raises(ApprovalRefused):
        read_outcome(*approval("13-bad-request-v2"))

    # 거절은 그 옆에서 200 으로 선다. 같은 입, 다른 일이다.
    assert approval("09-revoked-v2")[0] == 200


def test_창구_클라이언트는_전송과_읽기를_잇는다(approval):
    """`nexus_client` 와 같은 모양이다 — 전송은 주입받고, 응답은 `read_outcome` 이 하위 범주로
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
