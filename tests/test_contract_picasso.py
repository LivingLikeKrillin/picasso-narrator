"""적재면의 회귀 방벽.

**행동을 모는 시험이 아니라 바깥이 바뀐 것을 잡는 시험이다.** 픽스처는 picasso 의
`ExportFixtureTest` 가 같은 시나리오를 두 번 구동해 낸 두 벌이고, 가공하지 않았다.
"""

from receiver.cursor import select_unprocessed
from receiver.export import read_export
from receiver.idempotency import idempotency_key


def test_실물_한_벌을_읽는다(export_dir):
    export = read_export(export_dir("run-1"))

    assert export is not None
    assert len(export.incidents) == 9
    assert len(export.searches) == 4
    assert export.manifest["counts"] == {"incidents": 9, "remedySearches": 4}


def test_가림_줄에는_조치_열도_사유도_없다(export_dir):
    """**값이 비는 것이 아니라 키가 없는 것이 답이다.** 대장에 걸음을 실으면
    조회 한 번으로 가림이 풀리고, 가리는 일 자체가 무의미해진다."""
    searches = {s["outcome"]: s for s in read_export(export_dir("run-1")).searches}

    assert "steps" not in searches["WITHHELD"]
    assert "cause" not in searches["WITHHELD"]
    assert "steps" in searches["FOUND"]
    assert searches["NONE"]["cause"] == "NO_CAPABILITY"


def test_없는_값은_키를_빼지_않고_null_로_온다(export_dir):
    """키 부재와 `null` 이 갈려야 형식이 바뀐 것을 관측 실패로 안 읽는다."""
    incidents = read_export(export_dir("run-1")).incidents
    unapproved = [b for b in incidents if b["approvedBy"] is None]

    assert len(unapproved) == 8
    assert all("approvedBy" in b and "review" in b for b in incidents)


def test_빈손이_침묵으로_접히지_않는다(export_dir):
    """표준 protobuf JSON printer 였으면 빈 문자열 키가 통째로 빠진다.
    picasso 가 기본값 출력을 켜서 막았고(#36), 실물 줄에서 그것을 확인한다."""
    hold = read_export(export_dir("run-1")).incidents[0]["residualHold"]

    assert hold["kind"] == "HOLD_KIND_EMPTY"
    assert hold["objectRef"] == ""
    assert hold["reason"] == ""


def test_두_벌은_해시가_같고_구동만_다르다(export_dir):
    """**내가 지어낼 수 없는 유일한 것이고, runId 가 존재하는 이유 그 자체다.**"""
    one, two = read_export(export_dir("run-1")), read_export(export_dir("run-2"))

    assert [b["digest"] for b in one.incidents] == [b["digest"] for b in two.incidents]
    assert one.manifest["runId"] != two.manifest["runId"]


def test_한_벌을_다_처리해도_다음_구동은_새_사건이다(export_dir):
    """digest 로만 멱등을 걸었으면 여기서 0 건이 나오고, 설명이 하나도 안 붙는다.
    **그 고장에는 아무 신호가 없다** — 로그도 예외도 없이 설명 칸이 비어 있을 뿐이다."""
    one, two = read_export(export_dir("run-1")), read_export(export_dir("run-2"))
    seen = {idempotency_key(b, one.manifest) for b in one.incidents}

    assert select_unprocessed(one.incidents, one.manifest, seen) == []
    assert len(select_unprocessed(two.incidents, two.manifest, seen)) == 9


def test_사건과_탐색은_대체로_짝이_없다(export_dir):
    """**두 대장은 다른 순간을 적는다.**

    탐색은 접수 관문 안에서 돌고, 관문이 막으면 실행이 안 만들어지므로 **거절은
    사건 번들이 될 수 없다.** 반대로 실행 중에 난 실패는 사건이 되지만 그 자리에서
    탐색이 돌지 않는다. 짝이 생기는 것은 조치가 승인돼 실행이 선 뒤 그 실행이
    다시 실패한 경우뿐이다.

    그래서 이 층은 **둘을 각각 설명 대상으로 다룬다.** 사건마다 탐색을 찾아
    붙이려 하면 대부분 못 찾고, 못 찾은 것을 「대안 없음」으로 적으면 **탐색이
    돌지도 않은 건을 「찾아봤지만 없다」로 지어내게 된다.**
    """
    export = read_export(export_dir("run-1"))
    incidents = {b["jobOrderId"] for b in export.incidents}
    searches = {s["jobOrderId"] for s in export.searches}

    assert len(incidents & searches) == 1
    assert len(incidents - searches) == 8
    assert len(searches - incidents) == 3
