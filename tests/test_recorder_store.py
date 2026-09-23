"""기록 저장소 — `BOUNDARY.md` §3.2, §3.4."""

import pytest

from recorder.outcome import Outcome
from recorder.record import from_answer, from_failure
from recorder.store import AlreadyRecorded, RecordStore

KEY = ("run-1", "9760fe546d")
OTHER = ("run-1", "65a4547a17")


def test_적은_것을_되읽는다(tmp_path):
    store = RecordStore(tmp_path / "explanations.jsonl")
    store.append(from_failure(KEY, attempts=3, limit=3))

    back = RecordStore(tmp_path / "explanations.jsonl").load()

    assert len(back) == 1
    assert back[0].outcome is Outcome.GENERATION_FAILED
    assert (back[0].attempts, back[0].limit) == (3, 3)
    assert back[0].key == KEY


def test_저장소가_곧_커서다(tmp_path):
    """**「무엇을 처리했나」의 원천이 둘이면 안 된다.** 별도 커서 파일을 두면
    둘이 갈릴 때 어느 쪽이 참인지 판정할 수 없다 — 적힌 것이 곧 처리한 것이다."""
    store = RecordStore(tmp_path / "explanations.jsonl")
    store.append(from_failure(KEY, attempts=3, limit=3))

    assert RecordStore(tmp_path / "explanations.jsonl").seen() == {KEY}


def test_사건당_설명은_한_건이다(tmp_path):
    """두 번째 쓰기는 **설명이 둘 생기는 것**이다. 커서가 이미 막고 있으므로
    여기까지 온 것은 결함이고, 조용히 덮으면 그 결함이 안 보인다."""
    store = RecordStore(tmp_path / "explanations.jsonl")
    store.append(from_failure(KEY, attempts=3, limit=3))

    with pytest.raises(AlreadyRecorded):
        store.append(from_failure(KEY, attempts=1, limit=3))


def test_다른_열쇠는_쌓인다(tmp_path, nexus):
    _, body = nexus("06-answer-no-evidence")
    store = RecordStore(tmp_path / "explanations.jsonl")

    store.append(from_failure(KEY, attempts=3, limit=3))
    store.append(from_answer(OTHER, body["data"]))

    assert store.seen() == {KEY, OTHER}
    assert [r.outcome for r in store.load()] == [
        Outcome.GENERATION_FAILED,
        Outcome.NO_EVIDENCE,
    ]


def test_저쪽이_잰_값이_저장을_건너도_남는다(tmp_path):
    """**기록으로 안 넘어가면 재는 의미가 없다.**

    지연 분포는 한 번의 실행이 아니라 여러 날을 겹쳐야 보인다 — 벽이 어디고
    여유가 얼마인지는 한 판으로 안 나온다. 계측이 메모리에만 있으면 실행이
    끝날 때 같이 사라지고, `BOUNDARY.md` §7 의 패턴 감시가 볼 것이 없어진다.
    """
    degraded = {
        "llm_failed": True,
        "llm_failure_reason": "timeout",
        "answer": "답변을 생성할 수 없습니다.",
        "citations": [],
        "timing_ms": {"total_ms": 168, "bm25_ms": 160, "llm_ms": 180002},
        "evidence_snippets": [{"text": "근거"}] * 17,
    }
    store = RecordStore(tmp_path / "explanations.jsonl")
    store.append(from_answer(KEY, degraded, attempts=2, limit=2, elapsed=368.1))

    back, = RecordStore(tmp_path / "explanations.jsonl").load()

    assert back.diagnostics["timing"]["llm_ms"] == 180002
    assert back.diagnostics["evidence"] == 17


def test_주체가_저장을_건너도_남고_주체만_모아_읽는다(tmp_path):
    """저장소가 곧 이력이다. 주체가 없는 줄(탐색 줄·옛 기록)은 이력에 안 든다."""
    from recorder.record import from_answer

    store = RecordStore(tmp_path / "x.jsonl")
    subject = {"robotId": "hum-04", "failureClass": "GRASP_FAILED", "digest": "d1"}
    store.append(from_answer(("r", "d1"), {"answer": "…", "citations": []}, subject=subject))
    store.append(from_answer(("r", "s1"), {"answer": "…", "citations": []}))

    assert store.load()[0].subject == subject
    assert store.subjects() == [subject]
