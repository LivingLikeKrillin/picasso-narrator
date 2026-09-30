"""권고 측정기 — 설계서 `docs/superpowers/specs/2026-09-30-권고-측정.md` §6. khala 는 가짜 전송으로 흉내 낸다."""

import json
import os
import subprocess

import pytest

from eval import recommend as m
from eval.recommend_score import load_cases

ANSWER = ("권고: ESCALATE\n이유: 사람이 먼저 본다 [출처: SOP-01 파지 실패와 잔여 파지 처리, §5.1].\n"
          "절차: a\n먼저: b\n금지: c\n갈림: d\n근거 세기: e")


def data(**over):
    """khala 답변의 `data` 하나 — 표지가 ESCALATE 인 권고, 검증된 인용 하나, 판 칸 셋."""
    base = {"answer": ANSWER, "citations": [{"title": "SOP-01 파지 실패와 잔여 파지 처리", "section": "§5.1",
                                             "verified": True}],
            "abstained": False, "weak_evidence": False, "llm_failed": False, "llm_failure_reason": None,
            "unverified_citations": 0, "unverified_numbers": 0, "numbers": [], "usage": {"model": "claude-sonnet-5"},
            "timing_ms": {}, "evidence_snippets": [], "prompt_version": "73536dc7c9c0",
            "corpus_version": "d462b22017d6", "search_fingerprint": "b071397c854c"}
    base.update(over)
    return base


def failing(reason):
    return data(llm_failed=True, llm_failure_reason=reason, answer="")


def fake(script):
    """`(client, calls)` — 부를 때마다 [script] 의 `data` 를 차례로 돌려준다. 다 쓰면 마지막 것을 되풀이한다. 항목이
    예외면 던진다(전송이 뜻밖에 터진 흉내)."""
    calls = []

    def transport(method, url, headers, body):
        calls.append(body)
        item = script[min(len(calls), len(script)) - 1]
        if isinstance(item, Exception):
            raise item
        return 200, {"success": True, "data": item}

    return m.client_for("http://x", "t", transport=transport), calls


def test_먼저_보기가_깨진_요청에서_khala_를_안_부른다(tmp_path):
    """khala 를 부르기 전에 사례 전부를 읽고 짓는다 — 몇 시간 뒤에 깨진 사례를 만나지 않는다(설계서 §6)."""
    for f in m.REQUESTS.iterdir():
        (tmp_path / f.name).write_bytes(f.read_bytes())
    (tmp_path / "R05.json").write_bytes(b'{"broken": true}')
    with pytest.raises(SystemExit) as stop:
        m.prepare(load_cases(), requests=tmp_path)
    assert "R05" in str(stop.value) and "sha256" in str(stop.value)


def test_워커와_같은_클라이언트_인자를_쓴다(tmp_path):
    """같은 길(계약 §7) — 테넌트 · `top_k` · 식별자 채널 · 자료 칸은 워커와 같고, 빼는 종류에 과거 사례만 더한다."""
    prepared = m.prepare(load_cases(), only=["R11"])
    client, calls = fake([data()])
    m.measure(prepared, client, "abc1234", {}, tmp_path / "out.json")
    body = calls[0]
    assert body["tenant"] == "picasso" and body["top_k"] == 20 and body["identifier_channel"] is True
    assert body["exclude_doc_types"] == ["spec", "design_doc", "case"]
    assert body["answer_context"] == prepared[0]["context"] and body["query"] == prepared[0]["query"]


def test_재시도할_사유에_한_번_더_부르고_시도를_다_적는다(tmp_path):
    prepared = m.prepare(load_cases(), only=["R04"])
    client, calls = fake([failing("rate_limit"), data()])
    rows, complete = m.measure(prepared, client, "abc1234", {"x": 1}, tmp_path / "out.json")
    assert complete and len(calls) == 2
    assert [a["reason"] for a in rows[0]["attempts"]] == ["rate_limit", None], "살아난 첫 실패도 남는다"
    assert rows[0]["response"]["outcome"] == "RECOMMENDED" and rows[0]["resolved"] == "ESCALATE"
    saved = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert saved["complete"] is True and saved["env"] == {"x": 1} and saved["rows"][0]["answer"] == ANSWER
    assert saved["rows"][0]["diagnostics"]["corpus_version"] == "d462b22017d6", "계측을 다 담는다"


def test_한도와_인증은_곧바로_멈추고_기록을_남긴다(tmp_path, monkeypatch):
    """⚠ 윈도에서는 누가 기록을 열어 둔 동안 이름 바꾸기가 `PermissionError` 로 막힌다 — 기다렸다 다시 해 본다."""
    real, blocked = m.os.replace, []

    def replace(src, dst):
        if not blocked:
            blocked.append(dst)
            raise PermissionError(13, "누가 열어 두었다")
        real(src, dst)

    monkeypatch.setattr(m.os, "replace", replace)
    monkeypatch.setattr(m, "WRITE_PAUSE", 0)
    prepared = m.prepare(load_cases(), only=["R04", "R05"])
    client, calls = fake([failing("quota")])
    rows, complete = m.measure(prepared, client, "abc1234", {}, tmp_path / "out.json")
    assert not complete and len(calls) == 1 and [r["id"] for r in rows] == ["R04"]
    assert blocked and json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))["complete"] is False


def test_잇단_실패_둘에_멈추고_뜻밖의_예외도_실패로_적는다(tmp_path):
    """뜻밖의 예외가 몇 시간짜리 판을 죽이지 않는다 — 사유로 적고(재시도 안 함) 잇단 실패로 센다."""
    prepared = m.prepare(load_cases(), only=["R04", "R05", "R08"])
    client, calls = fake([failing("unreachable"), RuntimeError("전송이 터졌다")])
    rows, complete = m.measure(prepared, client, "abc1234", {}, tmp_path / "out.json")
    assert not complete and [r["id"] for r in rows] == ["R04", "R05"] and len(calls) == 2, "재시도 안 할 사유"
    assert [r["failed"] for r in rows] == ["unreachable", "exception:RuntimeError"]
    assert rows[1]["attempts"][0]["detail"] == "전송이 터졌다"


def test_재시도할_사유로_끝난_사례는_판_끝에_다시_돈다(tmp_path):
    prepared = m.prepare(load_cases(), only=["R04", "R05"])
    client, calls = fake([failing("timeout"), failing("timeout"), data(), data()])
    rows, complete = m.measure(prepared, client, "abc1234", {}, tmp_path / "out.json")
    assert complete and len(calls) == 4
    assert [a["reason"] for a in rows[0]["attempts"]] == ["timeout", "timeout", None]
    assert [a["n"] for a in rows[0]["attempts"]] == [1, 2, 3]
    assert [a.get("rerun", False) for a in rows[0]["attempts"]] == [False, False, True], "maxAttempts 밖의 시도"
    prepared = m.prepare(load_cases(), only=["R04", "R05", "R08"])
    client, calls = fake([failing("timeout"), failing("timeout"), data(), data(), failing("quota")])
    rows, complete = m.measure(prepared, client, "abc1234", {}, tmp_path / "out.json")
    assert not complete and len(calls) == 5, "다시 돌기도 멈춤 규칙을 따르고 사례마다 한 번이다"
    assert rows[0]["failed"] == "quota" and rows[0]["attempts"][-1]["rerun"] is True
    assert json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))["complete"] is False


def test_얼릴_것이_커밋되지_않았거나_기록이_있으면_돌지_않는다(tmp_path, monkeypatch):
    """기록의 해시가 곧 이 판을 잰 규칙이다 — 커밋 안 한 사례 파일이나 고친 채 돈 판은 어느 규칙으로 잰 것인지 말하지
    못한다(설계서 §0). ⚠ 한 번도 커밋 안 한 새 파일은 `--untracked-files=no` 에 안 잡힌다. 빈 저장소를 지어 본다 — 커밋 전
    훅 안에서 돌면 git 이 `GIT_DIR` · `GIT_INDEX_FILE` 을 물려주므로 먼저 지운다. 있는 기록은 덮지 않는다."""
    for name in [n for n in os.environ if n.startswith("GIT_")]:
        monkeypatch.delenv(name)
    repo = tmp_path / "repo"
    repo.mkdir()

    def run(*args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
                       cwd=repo, check=True, capture_output=True)

    run("init", "-q")
    for path in m.FROZEN:
        target = repo / path
        if target.suffix:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x", encoding="utf-8")
        else:
            target.mkdir(parents=True, exist_ok=True)
            (target / "R01.json").write_text("{}", encoding="utf-8")
    assert sum("커밋되지 않았다" in p for p in m.frozen_problems(repo)) == 4, "새 파일은 커밋 전이다"
    run("add", "-A")
    run("commit", "-qm", "x")
    assert m.frozen_problems(repo) == []
    (repo / "eval" / "recommend-requests" / "R99.json").write_text("{}", encoding="utf-8")
    assert m.frozen_problems(repo), "얼린 폴더에 든 새 파일"
    (repo / "eval" / "recommend-requests" / "R99.json").unlink()
    (repo / "eval" / "recommend_score.py").write_text("y", encoding="utf-8")
    assert any("HEAD 와 다르다" in p for p in m.frozen_problems(repo)), "커밋한 뒤 고친 파일"

    monkeypatch.setenv("NEXUS_TOKEN", "t")
    monkeypatch.setattr(m, "measure", lambda *a, **k: pytest.fail("khala 를 부르면 안 된다"))
    monkeypatch.setattr(m, "frozen_problems", lambda root=None: ["eval/goldenset-recommend.json: 커밋되지 않았다"])
    with pytest.raises(SystemExit) as stop:
        m.main(["--out", str(tmp_path / "out.json")])
    assert "커밋" in str(stop.value)
    monkeypatch.setattr(m, "frozen_problems", lambda root=None: [])
    (tmp_path / "out.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit) as stop:
        m.main(["--out", str(tmp_path / "out.json")])
    assert "이미 있다" in str(stop.value), "첫 판의 기록을 덮지 않는다"
    with pytest.raises(SystemExit) as stop:
        m.main(["--out", str(tmp_path / "없는 폴더" / "out.json")])
    assert "폴더가 없다" in str(stop.value)
