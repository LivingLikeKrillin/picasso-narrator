"""한 바퀴 — `BOUNDARY.md` §3.1, §3.4."""

import json

import pytest

from recorder.outcome import Outcome
from recorder.store import RecordStore
from receiver.approval import AttemptStore
from receiver.approval_reply import ApprovalRefused, read_outcome
from receiver.run import once


def _ok(query):
    return 200, {
        "success": True,
        "data": {"llm_failed": False, "answer": "…", "citations": [{"verified": True}]},
    }


def test_같은_한_벌을_두_번_돌려도_설명은_한_벌치다(tmp_path, export_dir):
    """**사건당 한 건이다.** 주기 스캔은 같은 디렉터리를 계속 다시 보므로, 이것이
    안 서면 스캔 주기마다 설명이 하나씩 늘어난다."""
    store = RecordStore(tmp_path / "explanations.jsonl")

    once(export_dir("run-1"), store, search=_ok)
    once(export_dir("run-1"), store, search=_ok)

    assert len(store.load()) == 13


def test_다음_구동은_새로_설명한다(tmp_path, export_dir):
    """digest 도 searchId 도 같은 시드면 반복된다. 실행을 안 보면 두 번째 구동이
    통째로 접히고 설명이 하나도 안 붙는다."""
    store = RecordStore(tmp_path / "explanations.jsonl")

    once(export_dir("run-1"), store, search=_ok)
    once(export_dir("run-2"), store, search=_ok)

    assert len(store.load()) == 26


def test_한_벌이_아직_아니면_아무것도_안_적는다(tmp_path):
    """내보내는 쪽이 쓰는 중일 수 있다. 반쯤 쓰인 파일로 설명을 만들면 그 설명이
    사실과 어긋나는데, 기록은 남는다."""
    (tmp_path / "incidents.jsonl").write_text("", encoding="utf-8")
    store = RecordStore(tmp_path / "explanations.jsonl")

    assert once(tmp_path, store, search=_ok) == 0
    assert store.load() == []


def test_저장소가_본_사건이_다음_바퀴의_이력이_된다(tmp_path, export_dir):
    store = RecordStore(tmp_path / "explanations.jsonl")

    once(export_dir("run-1"), store, search=_ok)

    assert len(store.subjects()) == 9


def _granting(approval):
    """실물 판 2 허락 응답을 그대로 돌려주는 승인 창구. 요청은 보지 않는다."""
    return lambda request: read_outcome(*approval("12-approved-v2"))


def test_승인을_안_켜면_시도하지_않는다(tmp_path, export_dir):
    """**기본값은 끔이다**(`BOUNDARY.md` §6.7). 켜지 않았는데 창구를 부르면 그 순간
    운영자가 모르는 승인이 나간다."""
    store = RecordStore(tmp_path / "explanations.jsonl")

    once(export_dir("run-1"), store, search=_ok)

    assert not (tmp_path / "approvals.jsonl").exists()


def test_한_바퀴가_설명과_승인_시도를_같이_남긴다(tmp_path, export_dir, approval):
    """**시퀀스 1 이다.** 한 벌을 읽어 설명을 붙이고, 부를 수 있는 제안에 승인을 시도하고,
    허락을 대장에 남긴다. 이 층이 보낸 것은 승인 한 번이고 실행은 picasso 가 한다.

    ⛔ **이 경로가 한 줄로 돈 적이 없었다**(2026-09-22 까지). 조각은 다 있었고 잇는 것만
    없었다 — 시험으로는 참이고 운영으로는 꺼진 대표 경로였다."""
    store = RecordStore(tmp_path / "explanations.jsonl")
    attempts = AttemptStore(tmp_path / "approvals.jsonl")

    once(export_dir("run-1"), store, search=_ok, approve=_granting(approval), attempts=attempts)

    assert len(store.load()) == 13
    made, = attempts.load()
    assert made.searchId == "search-1"
    assert made.granted is True
    assert made.schemaVersion == "2"
    # 구동 열쇠는 내보낼 때마다 새 값이다 — 판 5 재복사에서 글자로 박힌 값이 빨개졌다 (2026-09-23).
    # 벌의 manifest 에서 읽어 대본다. 재는 것은 「그 벌의 열쇠가 대장에 실렸나」이지 값 자체가 아니다.
    manifest = json.loads((export_dir("run-1") / "manifest.json").read_text(encoding="utf-8"))
    assert made.runId == manifest["runId"]
    assert attempts.granted_before("hum-02", ["pick_place"]) is True


def test_같은_한_벌을_두_번_돌려도_시도는_한_번이다(tmp_path, export_dir, approval):
    """주기 스캔은 같은 디렉터리를 계속 다시 본다. 이것이 안 서면 바퀴마다 같은 제안에
    승인이 다시 나간다 — 허락은 제안을 소모하므로 두 번째는 `NO_PROPOSAL` 이겠지만,
    그 줄이 대장에 쌓이는 것 자체가 거짓 이력이다."""
    store = RecordStore(tmp_path / "explanations.jsonl")
    attempts = AttemptStore(tmp_path / "approvals.jsonl")
    calls = []

    def approve(request):
        calls.append(request)
        return read_outcome(*approval("12-approved-v2"))

    once(export_dir("run-1"), store, search=_ok, approve=approve, attempts=attempts)
    once(export_dir("run-1"), store, search=_ok, approve=approve, attempts=attempts)

    assert len(calls) == 1
    assert len(attempts.load()) == 1


def test_다음_구동은_새로_시도한다(tmp_path, export_dir, approval):
    """searchId 는 같은 시드에서 반복된다. 구동을 안 보면 두 번째 구동의 제안이 통째로 접힌다."""
    store = RecordStore(tmp_path / "explanations.jsonl")
    attempts = AttemptStore(tmp_path / "approvals.jsonl")

    once(export_dir("run-1"), store, search=_ok, approve=_granting(approval), attempts=attempts)
    once(export_dir("run-2"), store, search=_ok, approve=_granting(approval), attempts=attempts)

    assert len(attempts.load()) == 2
    assert len({a.runId for a in attempts.load()}) == 2


def test_설명이_죽어도_승인_시도는_간다(tmp_path, export_dir, approval):
    """**설명은 사건 처리의 옆이다**(불변식 3). 설명 경로가 통째로 죽어도 승인 시도는
    나가야 한다 — 안 나가면 설명을 기다려야 회복이 도는 것이고, 그 순간 LLM 이 운영
    경로에 들어간 것이다."""
    from explainer.ask import NexusUnavailable

    def dead(query):
        raise NexusUnavailable("502")

    store = RecordStore(tmp_path / "explanations.jsonl")
    attempts = AttemptStore(tmp_path / "approvals.jsonl")

    once(export_dir("run-1"), store, search=dead, approve=_granting(approval), attempts=attempts)

    assert all(r.outcome is Outcome.GENERATION_FAILED for r in store.load())
    assert len(attempts.load()) == 1


def test_창구에_못_닿은_것은_거절로_적지_않는다(tmp_path, export_dir):
    """**못 닿음과 거절은 다르다**(`BOUNDARY.md` §6.8). 거절은 200 이고 정상 응답이라
    대장에 남지만, 못 닿은 것은 대장에 안 남고 이 바퀴가 멈춘다 — 그래야 다음 바퀴가
    같은 줄을 다시 부른다. 설명은 이미 적혔으므로 잃는 것이 없다."""
    def unreachable(request):
        raise ApprovalRefused("599: 못 닿았다")

    store = RecordStore(tmp_path / "explanations.jsonl")
    attempts = AttemptStore(tmp_path / "approvals.jsonl")

    with pytest.raises(ApprovalRefused):
        once(export_dir("run-1"), store, search=_ok, approve=unreachable, attempts=attempts)

    assert len(store.load()) == 13
    assert attempts.load() == []


def test_승인을_켜면_대장이_있어야_한다(tmp_path, export_dir):
    """§6.1 이 감사를 요구한다. 대장 없이 켜면 시도가 나가는데 남는 것이 없다. 켜기 전에
    막는다 — 설명이 붙은 뒤에 막으면 반쪽만 돈 바퀴가 된다."""
    store = RecordStore(tmp_path / "explanations.jsonl")

    with pytest.raises(ValueError):
        once(export_dir("run-1"), store, search=_ok, approve=lambda request: None)

    assert store.load() == []
