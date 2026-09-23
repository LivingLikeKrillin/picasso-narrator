"""미처리분 고르기 — `BOUNDARY.md` §3.2 「처리 표시는 읽는 쪽의 상태」."""

from receiver.cursor import select_unprocessed
from receiver.export import Export

MANIFEST = {"schemaVersion": "1", "runId": "run-A"}


def _export(*digests, run="run-A"):
    return Export(
        incidents=[{"incidentId": f"incident-{i}", "digest": d} for i, d in enumerate(digests, 1)],
        searches=[],
        manifest={"schemaVersion": "1", "runId": run},
    )


def test_이미_본_것은_다시_내지_않는다():
    export = _export("aaa", "bbb")
    seen = {("run-A", "aaa")}

    fresh = select_unprocessed(export.incidents, export.manifest, seen)

    assert [b["digest"] for b in fresh] == ["bbb"]


def test_같은_해시라도_다른_구동이면_새_사건이다():
    """`digest` 는 같은 시드면 같은 값이다. 실행을 안 보면 두 번째 구동이 통째로
    접혀 설명이 하나도 안 붙고, **그 고장에는 아무 신호가 없다.**"""
    seen = {("run-A", "aaa")}

    fresh = select_unprocessed(_export("aaa", run="run-B").incidents, {"runId": "run-B"}, seen)

    assert [b["digest"] for b in fresh] == ["aaa"]
