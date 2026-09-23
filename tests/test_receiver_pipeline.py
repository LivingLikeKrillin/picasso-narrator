"""한 벌을 설명으로 옮긴다 — `BOUNDARY.md` §1.5, §3.4."""

from receiver.pipeline import explain
from receiver.scan import scan
from recorder.outcome import Outcome


def _answers(citations=1):
    def search(query):
        return 200, {
            "success": True,
            "data": {
                "abstained": False,
                "llm_failed": False,
                "answer": "그렇게 된 이유는 …",
                "citations": [{"title": "ADR 40", "verified": True}] * citations,
            },
        }

    return search


def test_두_줄기를_모두_설명한다(export_dir):
    """**사건만 설명하고 탐색 줄을 버리지 않는다.** 「대안 없음」과 「가려졌다」는
    탐색 줄에만 있고, 그 둘이 P2 가 보이려는 것이다."""
    batch = scan(export_dir("run-1"), seen=set())

    records = explain(batch, search=_answers(), limit=3)

    assert len(records) == 13
    assert all(r.outcome is Outcome.GIVEN for r in records)


def test_설명이_통째로_죽어도_한_벌이_다_처리된다(export_dir):
    """**P1 이다.** 설명 경로가 전부 실패해도 빠뜨리는 줄이 없고, 각각에 몇 번
    해봤는지가 남는다. 하나라도 조용히 사라지면 운영자는 그 사건에 설명이
    「아직 안 온 것」인지 「영영 안 올 것」인지 구별하지 못한다."""
    from explainer.ask import NexusUnavailable

    def dead(query):
        raise NexusUnavailable("502")

    batch = scan(export_dir("run-1"), seen=set())

    records = explain(batch, search=dead, limit=3)

    assert len(records) == 13
    assert all(r.outcome is Outcome.GENERATION_FAILED for r in records)
    assert all((r.attempts, r.limit) == (3, 3) for r in records)


def test_검색에는_문장이_간다(export_dir):
    """소비 표면의 `query` 는 문자열이다. 사실 묶음을 그대로 넘기면 실물에서만
    깨지고, 가짜를 쓰는 시험은 초록으로 남는다."""
    sent = []

    def search(query):
        sent.append(query)
        return 200, {"success": True, "data": {"llm_failed": False, "citations": [{"t": 1}]}}

    explain(scan(export_dir("run-1"), seen=set()), search=search, limit=3)

    assert sent
    assert all(isinstance(q, str) for q in sent)
    assert any("PAYLOAD_LOST" in q for q in sent)
    assert any("NO_CAPABILITY" in q for q in sent)


def test_일시적_실패만_다시_해본다(export_dir):
    """`auth` 를 상한까지 태우면 시간만 버리고, 기록에 「재시도 3/3」이 남아
    운영자가 다시 눌러 볼 일처럼 보인다 — 사람이 가서 키를 고칠 일인데."""
    calls = []

    def dead(query):
        calls.append(1)
        return 200, {
            "success": True,
            "data": {"llm_failed": True, "llm_failure_reason": "auth", "citations": []},
        }

    batch = scan(export_dir("run-1"), seen=set())
    records = explain(batch, search=dead, limit=3)

    assert len(calls) == len(records)  # 줄마다 한 번씩만
    assert all(r.outcome is Outcome.GENERATION_FAILED for r in records)
    assert all(r.reason == "auth" for r in records)


def test_사유를_기록에_남긴다(export_dir):
    """「안 끝났다」와 「키가 없다」는 다음 행동이 다르다. 기록이 그걸 들어야
    운영자가 다시 누를지 사람을 부를지 안다."""
    def slow(query):
        return 200, {
            "success": True,
            "data": {"llm_failed": True, "llm_failure_reason": "timeout", "citations": []},
        }

    records = explain(scan(export_dir("run-1"), seen=set()), search=slow, limit=2)

    assert records[0].reason == "timeout"
    assert (records[0].attempts, records[0].limit) == (2, 2)


def test_재발_횟수가_질의에_실린다(export_dir):
    """저장소가 본 것과 이 한 벌의 것을 합쳐 센다. incident-1 은 hum-02 PAYLOAD_LOST 다."""
    sent = []

    def search(query):
        sent.append(query)
        return 200, {"success": True, "data": {"llm_failed": False, "citations": [{"t": 1}]}}

    earlier = {"robotId": "hum-02", "failureClass": "PAYLOAD_LOST", "unitId": "X",
               "at": "2026-09-05T00:00:00Z", "digest": "prior-1"}
    batch = scan(export_dir("run-1"), seen=set())

    records = explain(batch, search=search, limit=3, prior=[earlier])

    # 사건이 열린 순서대로 먼저 설명되므로 첫 질의가 incident-1 이다.
    assert 'recurrenceSeen={"sameRobotSameClass":1,"sameUnitSameClass":0}' in sent[0]
    assert records[0].subject["robotId"] == "hum-02"
