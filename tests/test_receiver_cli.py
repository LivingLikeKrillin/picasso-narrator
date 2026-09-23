"""한 바퀴를 명령 한 줄로 — `SEQUENCES.md` 1."""

import pytest

from receiver.approval import AttemptStore
from receiver.cli import build_parser, run
from recorder.store import RecordStore


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    """토큰은 저장소 밖에서 온다(`NEXUS_TOKEN`). 시험은 환경에 가짜 값을 둔다."""
    monkeypatch.setenv("NEXUS_TOKEN", "test-token")


def _stack(nexus, approval):
    """가짜 전송 하나가 Nexus 와 승인 창구를 둘 다 답한다. URL 로 가른다."""
    def transport(method, url, headers, payload):
        if url.endswith("/approvals"):
            return approval("12-approved-v2")
        return nexus("05-answer-with-citations")
    return transport


def test_기본은_승인을_끄고_설명만_적는다(tmp_path, export_dir, nexus, approval):
    """`--approve` 를 안 주면 창구를 부르지 않고 대장도 안 선다(`BOUNDARY.md` §6.7)."""
    args = build_parser().parse_args([str(export_dir("run-1")), "--out", str(tmp_path / "out")])

    lines = run(args, transport=_stack(nexus, approval))

    assert len(RecordStore(tmp_path / "out" / "explanations.jsonl").load()) == 13
    assert not (tmp_path / "out" / "approvals.jsonl").exists()
    assert any("기본값 끔" in line for line in lines)


def test_승인_창구를_주면_시도가_대장에_남는다(tmp_path, export_dir, nexus, approval):
    """**시퀀스 1 이 명령 한 줄로 돈다.** 설명 열셋과 승인 시도 하나가 한 바퀴에서 나온다."""
    args = build_parser().parse_args([str(export_dir("run-1")), "--out", str(tmp_path / "out"),
                                      "--approve", "http://127.0.0.1:8770/approvals"])

    lines = run(args, transport=_stack(nexus, approval))

    made, = AttemptStore(tmp_path / "out" / "approvals.jsonl").load()
    assert made.granted is True
    assert any("search-1" in line and "허락" in line for line in lines)


def test_한_벌이_아직_아니면_돌지_않고_말한다(tmp_path):
    """`manifest.json` 이 없으면 내보내는 쪽이 아직 쓰는 중이거나 경로가 틀린 것이다.
    `once` 는 둘 다 0 으로 접는데, 사람이 부르는 자리에서는 그 둘이 갈려야 한다."""
    def never(*args):
        raise AssertionError("한 벌이 아닌데 전송이 불렸다")

    args = build_parser().parse_args([str(tmp_path / "empty"), "--out", str(tmp_path / "out")])

    lines = run(args, transport=never)

    assert "한 벌이 아직 아니다" in lines[0]


def test_창구에_못_닿으면_설명은_남기고_멈춘다(tmp_path, export_dir, nexus):
    """**못 닿음은 거절이 아니다**(`BOUNDARY.md` §6.8). 명령은 설명을 적은 뒤 멈추고, 그 시도가
    대장에 안 남았으므로 다음 바퀴가 다시 부른다고 말한다. 조용히 0 으로 끝내면 사람이
    승인이 나간 줄 안다."""
    def transport(method, url, headers, payload):
        if url.endswith("/approvals"):
            return 599, {"detail": "ConnectError: 거부됨", "llm_failure_reason": "unavailable"}
        return nexus("05-answer-with-citations")

    args = build_parser().parse_args([str(export_dir("run-1")), "--out", str(tmp_path / "out"),
                                      "--approve", "http://127.0.0.1:8770/approvals"])

    with pytest.raises(SystemExit) as stopped:
        run(args, transport=transport)

    assert "못 닿았" in str(stopped.value)
    assert len(RecordStore(tmp_path / "out" / "explanations.jsonl").load()) == 13
    assert AttemptStore(tmp_path / "out" / "approvals.jsonl").load() == []


def test_먼저_허락된_시도는_뒤가_못_닿아도_보인다(tmp_path, export_dir, nexus, approval):
    """⛔ **Chunk 1 검토가 찾았다 (2026-09-22).** 제안이 둘인데 첫째는 허락되고 둘째에서 창구가
    끊기면, 멈추는 문장이 「그 시도는 대장에 안 남았다」라고만 말해 사람이 아무것도 안 나간 줄
    안다 — 그런데 허락 하나는 이미 대장에 있고 picasso 는 그것을 실행 중이다. 멈추는 문장이
    이미 적힌 시도를 같이 들고, 안 남은 것은 멈춘 그 줄로 좁혀 말한다."""
    import json
    import shutil

    export = tmp_path / "two"
    shutil.copytree(export_dir("run-1"), export)
    lines = (export / "remedy-searches.jsonl").read_text(encoding="utf-8").splitlines()
    second = json.loads(lines[0])
    second["searchId"] = "search-9"
    second["robotId"] = "hum-04"
    with (export / "remedy-searches.jsonl").open("a", encoding="utf-8") as out:
        out.write(json.dumps(second, ensure_ascii=False) + "\n")
    calls = []

    def transport(method, url, headers, payload):
        if url.endswith("/approvals"):
            calls.append(payload)
            if len(calls) == 1:
                return approval("12-approved-v2")
            return 599, {"detail": "ConnectError: 거부됨", "llm_failure_reason": "unavailable"}
        return nexus("05-answer-with-citations")

    args = build_parser().parse_args([str(export), "--out", str(tmp_path / "out"),
                                      "--approve", "http://127.0.0.1:8770/approvals"])

    with pytest.raises(SystemExit) as stopped:
        run(args, transport=transport)

    message = str(stopped.value)
    assert "search-1" in message and "허락" in message
    assert "search-9" in message and "못 닿" in message
    made, = AttemptStore(tmp_path / "out" / "approvals.jsonl").load()
    assert made.searchId == "search-1"


def test_낯선_판과_구동_열쇠_없는_한_벌은_문장으로_멈춘다(tmp_path, export_dir, nexus):
    """⛔ **Chunk 1 검토가 찾았다 (2026-09-22).** 판이 오르면(3 에서 4 로 한 번 올랐다) 읽는 쪽은
    멈추는 것이 맞는데, 사람이 부르는 명령이 추적 정보로 멈추면 어느 파일의 무엇인지 안 보인다.
    한 벌이 아직 아닐 때처럼 문장으로 멈춘다."""
    import json
    import shutil

    def answers(*args):
        return nexus("05-answer-with-citations")

    strange = tmp_path / "strange"
    shutil.copytree(export_dir("run-1"), strange)
    manifest = json.loads((strange / "manifest.json").read_text(encoding="utf-8"))
    manifest["schemaVersion"] = "9"
    (strange / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    args = build_parser().parse_args([str(strange), "--out", str(tmp_path / "out")])

    with pytest.raises(SystemExit) as stopped:
        run(args, transport=answers)

    assert "읽을 줄 아는 판" in str(stopped.value)
    assert str(strange / "manifest.json") in str(stopped.value)

    keyless = tmp_path / "keyless"
    shutil.copytree(export_dir("run-1"), keyless)
    manifest = json.loads((keyless / "manifest.json").read_text(encoding="utf-8"))
    del manifest["runId"]
    (keyless / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    args = build_parser().parse_args([str(keyless), "--out", str(tmp_path / "out2")])

    with pytest.raises(SystemExit) as stopped:
        run(args, transport=answers)

    assert "runId" in str(stopped.value)


def test_토큰은_저장소_밖에서_온다(monkeypatch, tmp_path):
    """⛔ **측정 하니스가 잴 뿐인 층에 필요 없는 권한이 딸린 신원으로 인증하고 있었다 (khala 실측 2026-09-23).** 코드에
    글자로 박힌 개발 토큰이 그 신원이었다. 값은 저장소에 안 두고
    환경(`NEXUS_TOKEN`)이나 `--token` 으로만 온다 — 없으면 약한 기본값으로 조용히 돌지 않고 문장으로
    멈춘다. 한 벌이 아직 아닌지보다 먼저 본다 — 설정이 틀린 채 기다리는 바퀴는 영영 기다린다."""
    def never(*args):
        raise AssertionError("토큰이 없는데 전송이 불렸다")

    monkeypatch.delenv("NEXUS_TOKEN", raising=False)
    args = build_parser().parse_args([str(tmp_path / "x"), "--out", str(tmp_path / "out")])
    assert args.token is None
    with pytest.raises(SystemExit) as stopped:
        run(args, transport=never)
    assert "NEXUS_TOKEN" in str(stopped.value)

    monkeypatch.setenv("NEXUS_TOKEN", "from-env")
    assert build_parser().parse_args([str(tmp_path / "x"), "--out", str(tmp_path / "out")]).token == "from-env"
    given = build_parser().parse_args([str(tmp_path / "x"), "--out", str(tmp_path / "out"), "--token", "given"])
    assert given.token == "given"
