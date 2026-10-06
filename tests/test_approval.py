"""자동 승인 시도 — `BOUNDARY.md` §6, `SEQUENCES.md` 불변식 2.

**이 계층은 자동 승인 자격을 판단하지 않는다.** 시도하고, 허락이든 거부든 받아 적는다.
"""

import pathlib

import pytest

from receiver.approval import Attempt, candidates, try_approve, AttemptStore, LedgerEmpty, pending
from receiver.approval_reply import Outcome


def test_조치_열이_있는_것에만_시도한다(export_dir):
    """`WITHHELD` 줄에는 `steps` 키가 없다 — 걸음을 모르면 파라미터를 만들 수 없어
    **부를 수가 없다.** 다른 자리에서 찾아오면 그 순간 가림이 풀린다.

    `NONE` 은 조치 자체가 없다. 시도할 것이 없는 것과 자동 승인 자격이 없는 것은 다르다.
    """
    searches = _searches(export_dir, "run-1")

    picked = [s["searchId"] for s in candidates(searches)]

    assert picked == ["search-1"]


def test_거부는_실패가_아니라_정상_응답이다(export_dir):
    """자동 승인 자격이 없으면 사람에게 남는다. 그것이 설계된 경로다 — 거부를 오류로 적으면
    「자격 없음」과 「시스템 고장」이 같아 보인다."""
    search = candidates(_searches(export_dir, "run-1"))[0]

    result = try_approve(search, approve=lambda req: Outcome(granted=False, reason="선언 목록에 없다"))

    # 거부도 **무엇에 대한 거부였는지**를 함께 적는다. 그 두 칸이 P5 의 재료다.
    assert result == Attempt(searchId="search-1", granted=False, reason="선언 목록에 없다",
                             robotId="hum-02", sawSkillTypes=["pick_place"])


def test_허락도_그대로_적는다(export_dir):
    search = candidates(_searches(export_dir, "run-1"))[0]

    result = try_approve(search, approve=lambda req: Outcome(granted=True))

    assert result.granted is True


def test_시도가_보내는_것은_신원과_조치뿐이다(export_dir):
    """**자동 승인 자격은 승인 API 가 판정한다**(불변식 2). 이 계층이 「나는 자격이 있다」를
    실어 보내면 그 순간 우회가 성립한다."""
    sent = {}
    search = candidates(_searches(export_dir, "run-1"))[0]

    try_approve(search, approve=lambda req: sent.update(req) or Outcome(granted=True), approver_id="narrator-1")

    assert sent["approverId"] == "narrator-1"
    assert sent["approverKind"] == "AGENT"
    assert sent["robotId"] == "hum-02"
    assert sent["jobOrderId"] == "PATROL-1"
    assert sent["sawSkillTypes"] == ["pick_place"]

    # **값도 주문도 걸음도 실을 칸이 없다**(ADR 44). 있으면 그건 승인 API 표면이
    # 아니라 접수 API 표면이고, 이 계층이 조치를 기술하게 된다.
    assert "parameters" not in sent
    assert "steps" not in sent
    assert "order" not in sent
    assert "entitled" not in sent


def _searches(export_dir, run):
    import json

    path = export_dir(run) / "remedy-searches.jsonl"
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_시도는_기록에_남는다(tmp_path):
    """**§6.1 이 감사를 요구하는데 지금 아무 데도 안 남는다.**

    「이 층이 승인한 건도 사후 검토 대상이며, 이의율은 사람 승인과 따로 집계한다」고
    적어 놓고 `Attempt` 를 버리고 있었다. 버리면 사후 검토할 것이 없다.

    **거절도 남긴다.** 거절은 오류가 아니라 정상 응답이고(`ADR 44`), 무엇이 왜
    거절됐는지가 §6.6 의 두 출구(근본 원인 항목 / 자동 승인 후보)를 가르는 재료다.
    """
    store = AttemptStore(tmp_path / "approvals.jsonl")
    store.append(Attempt(searchId="search-1", granted=False, reason="",
                         refusal="NOT_DECLARED", robotId="hum-03",
                         sawSkillTypes=["pick_place"]))
    # 버전 3 의 소모 거절은 누가 소모했는지를 함께 남긴다 — 사후 검토가 「누가 먼저 눌렀나」를 읽을 재료다
    record = {"approverId": "narrator-1", "approverKind": "AGENT", "executionId": "exec-1"}
    store.append(Attempt(searchId="search-2", granted=False, refusal="CONSUMED", robotId="hum-02",
                         sawSkillTypes=["pick_place"], schemaVersion="3", consumed=record))

    # 버전 4 는 답한 인스턴스를 함께 남긴다 — `executionId` 와 짝지어야 시도가 갈린다
    store.append(Attempt(searchId="search-3", granted=True, robotId="hum-02", sawSkillTypes=["pick_place"],
                         schemaVersion="4", instanceId="mw-1", executionId="exec-1"))

    back, again, fourth = AttemptStore(tmp_path / "approvals.jsonl").load()

    assert back.searchId == "search-1"
    assert back.granted is False
    assert back.refusal == "NOT_DECLARED"
    assert back.sawSkillTypes == ["pick_place"]
    assert back.consumed is None, "소모가 아닌 거절 — 그리고 그 칸이 생기기 전에 적힌 줄도 같은 빈 값이다"
    assert (again.refusal, again.consumed, again.schemaVersion) == ("CONSUMED", record, "3")
    assert again.instanceId is None, "판 3 의 줄 — 그 칸이 생기기 전이다"
    assert (fourth.granted, fourth.instanceId, fourth.executionId, fourth.schemaVersion) == (True, "mw-1", "exec-1", "4")
    assert again.executionId is None, "거절 줄의 실행은 소모 기록 안에 있다"


def test_전에_허락된_적_있는지를_기록이_답한다(tmp_path):
    """**P5 의 전제다 — 상대 저장소 응답으로는 못 가르는 것을 내 승인 로그가 가른다.**

    자동 승인 자격이 박탈되면 다음 시도가 거절되는데, 그 거절이 **자동 승인 자격 박탈 때문인지 처음부터
    승인 등록에 없었는지** 응답으로는 안 갈린다(`BOUNDARY.md` §6.8). 둘은 후속 조치가
    다르다 — 자동 승인 자격 박탈은 사후 검토로 가고, 승인 등록에 없는 것은 승인 등록을 고치러 간다.

    **내 승인 로그는 그 둘을 가를 재료를 갖는다.** 같은 (로봇, 조치 유형)에 **전에 허락이
    있었으면** 무언가 바뀐 것이고, 한 번도 없었으면 「원래 안 되던 것」이다.

    ⚠ **자동 승인 자격 박탈이라고 단정하지 않는다.** 전에 됐다가 안 되는 이유는 자동 승인 자격 박탈 말고도 만료·
    범위 축소가 있고(§6.2), 그 셋은 이 승인 로그로 안 갈린다. 여기서 답하는 것은
    **「전에 허락된 적 있나」** 하나뿐이고, 그 사실만 적는다.
    """
    store = AttemptStore(tmp_path / "approvals.jsonl")
    store.append(Attempt(searchId="s-1", granted=True, reason="",
                         robotId="hum-03", sawSkillTypes=["pick_place"]))
    store.append(Attempt(searchId="s-2", granted=False, reason="", refusal="NOT_DECLARED",
                         robotId="hum-03", sawSkillTypes=["pick_place"]))

    assert store.granted_before("hum-03", ["pick_place"]) is True
    assert store.granted_before("hum-09", ["pick_place"]) is False
    assert store.granted_before("hum-03", ["navigate_to"]) is False


def test_시도가_대장이_돌아볼_두_칸을_채운다(export_dir, tmp_path):
    """⛔ **`try_approve` 가 그 둘을 안 채워 `granted_before` 가 늘 거짓이었다**
    (2026-09-22 실측).

    `granted_before` 는 `(기체, 조치 유형)` 으로 되읽는데 `try_approve` 는 `searchId`·
    `granted`·`reason` 만 채웠다. 두 값은 여섯 줄 위에서 요청을 지을 때 이미 손에
    있었고 **승인 로그에만 안 실렸다.** 그래서 방금 허락된 건도 「전에 허락된 적 없다」로
    돌아왔다 — P5 의 재료가 **테스트에서만 서 있고 실제 경로에서는 꺼져 있었다.**

    앞선 테스트 둘이 이것을 못 잡았다. 승인 로그 테스트는 `Attempt` 를 손으로 지어 넣었고,
    시도 테스트는 **빠진 그 모양을 그대로 못박고** 있었다.
    """
    search = candidates(_searches(export_dir, "run-1"))[0]
    store = AttemptStore(tmp_path / "approvals.jsonl")

    store.append(try_approve(search, approve=lambda req: Outcome(granted=True)))

    assert store.granted_before("hum-02", ["pick_place"]) is True


def test_거절의_갈래가_산문_칸이_아니라_제_칸에_남는다(export_dir, tmp_path):
    """⛔ **주입 계약이 두 칸짜리라 하위 범주가 산문 칸으로 새고 있었다** (2026-09-22 실측).

    picasso 는 거절을 `refusal` 열거값으로 돌려주고 `read_outcome` 이 그것을 이미
    하위 범주로 옮긴다. 그런데 `try_approve` 가 받는 것이 `(granted, reason)` 이라
    **실제 서비스 테스트가 하위 범주를 산문 칸에 실어** 통과시키고 있었다. 승인 로그의 `refusal` 은 늘
    비고, 값은 「대조하지 않는다」고 적어 둔 칸에 앉는다.

    **후속 조치를 가르는 것이 그 하위 범주다** — 가려진 것은 사람의 진단을 기다리고,
    범위 밖은 승인 등록을 고쳐야 하고, 제안 없음은 애초에 승인할 것이 없다. 산문으로
    대조하면 문장이 바뀌는 날 조용히 안 걸린다.
    """
    search = candidates(_searches(export_dir, "run-1"))[0]
    store = AttemptStore(tmp_path / "approvals.jsonl")

    store.append(try_approve(search, approve=lambda req: Outcome(
        granted=False, refusal="ROBOT_OUT_OF_SCOPE", reason="선언 목록에 없다")))

    back, = store.load()
    assert back.refusal == "ROBOT_OUT_OF_SCOPE"
    assert back.reason == "선언 목록에 없다"


def test_대장이_비면_거짓_대신_멈춘다(tmp_path):
    """⛔ **적어 두는 것으로는 안 걸렸다** (2026-09-22).

    「대장이 비어 있으면 『없었다』와 『모른다』가 같아진다」를 주석에도 경계 문서에도
    적어 뒀는데, **적어 두는 것은 읽는 쪽이 읽어야 걸린다.** 거짓이 돌아오면 그대로
    「전에 허락된 적 없다」로 읽히고, 그 길은 사람을 **승인 등록 수정하러** 보낸다. 자동 승인 자격 박탈된
    뒤였으면 틀린 출구다.

    khala 가 같은 결함 한 벌을 고치며 적어 보낸 처방이다 — **그 값이 참인 실행이 하나라도
    있어야 한다.** 상대 저장소는 요청이 0 건이면 실행이 스스로 멈추게 했다. 여기서는 **답할 수
    없으면 답하지 않는다.**
    """
    store = AttemptStore(tmp_path / "approvals.jsonl")

    with pytest.raises(LedgerEmpty):
        store.granted_before("hum-03", ["pick_place"])


def test_시도는_어느_구동의_것인지를_든다(export_dir, tmp_path):
    """**같은 시드의 재구동은 searchId 가 그대로 반복된다**(`BOUNDARY.md` §3.4). 설명의
    멱등성 키가 `(runId, digest)` 인 것과 같은 이유로, 시도도 실행을 들어야 두 번째 실행의 같은
    줄이 「이미 불러 본 것」으로 접히지 않는다. 허락은 제안을 소모하므로 두 번째 실행의
    시도가 `NO_PROPOSAL` 로 오는 것은 거짓이 아니라 사실이다."""
    search = candidates(_searches(export_dir, "run-1"))[0]
    store = AttemptStore(tmp_path / "approvals.jsonl")

    store.append(try_approve(search, approve=lambda req: Outcome(granted=True), run_id="run-A"))

    back, = store.load()
    assert back.runId == "run-A"
    assert store.seen() == {("run-A", "search-1")}


def test_구동_칸이_없는_옛_줄은_빈_칸으로_읽는다(tmp_path):
    """⚠ 빈 칸은 「모른다」가 아니라 **그 칸이 생기기 전에 적힌 줄**이다 — `schemaVersion` 의
    빈 칸과 같은 셋째 값이다. 옛 줄은 어느 실행의 것인지 말할 수 없으므로 새 실행의 같은
    줄을 막지 않는다."""
    path = tmp_path / "approvals.jsonl"
    path.write_text('{"searchId": "search-1", "granted": true, "reason": ""}\n', encoding="utf-8")

    back, = AttemptStore(path).load()

    assert back.runId == ""
    assert AttemptStore(path).seen() == {("", "search-1")}


def test_이_구동에서_아직_안_부른_줄만_고른다(export_dir):
    """부를 수 있는 줄(`candidates`) 중 이 실행의 승인 로그에 없는 것. **설명이 붙었는지는
    보지 않는다** — 설명은 사건 처리의 옆이지 앞이 아니다(불변식 3)."""
    proposals = candidates(_searches(export_dir, "run-1"))

    assert [s["searchId"] for s in pending(proposals, "run-A", seen=set())] == ["search-1"]
    assert pending(proposals, "run-A", seen={("run-A", "search-1")}) == []
    # 다른 실행의 같은 줄은 새것이다.
    assert len(pending(proposals, "run-B", seen={("run-A", "search-1")})) == 1


def test_실물_두_바퀴의_대장을_되읽는다():
    """⛔ **시퀀스 1 이 실제 서비스 승인 엔드포인트를 지나 돌았다 (2026-09-22 실측).** picasso 가 승인 엔드포인트를 띄운
    미들웨어의 살아 있는 번들에 `python -m receiver … --approve` 로 파이프라인 실행 두 번 돌렸다. 첫 파이프라인 실행이
    search-1 을 허락받고 search-3 을 범위 밖으로 거절받았고, 둘째 파이프라인 실행은 같은 실행이라 아무것도
    다시 안 불렀다. 이 파일이 그 승인 로그 그대로다 — 되읽기가 픽스처가 아니라 실제 서비스에서 서는지 고정한다."""
    store = AttemptStore(pathlib.Path(__file__).parent / "fixtures" / "approvals"
                         / "live-2026-09-22-approvals.jsonl")

    granted, refused = store.load()

    assert (granted.searchId, granted.robotId, granted.granted, granted.schemaVersion) == (
        "search-1", "hum-02", True, "2")
    assert (refused.searchId, refused.robotId, refused.refusal) == ("search-3", "hum-05", "ROBOT_OUT_OF_SCOPE")
    assert granted.runId == refused.runId and granted.runId.endswith("-1")
    assert store.seen() == {(granted.runId, "search-1"), (granted.runId, "search-3")}
    assert store.granted_before("hum-02", ["pick_place"]) is True
    assert store.granted_before("hum-05", ["pick_place"]) is False
