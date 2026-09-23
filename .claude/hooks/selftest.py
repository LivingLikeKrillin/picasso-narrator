#!/usr/bin/env python3
"""훅 셋의 자가 시험. 막아야 할 것과 통과해야 할 것을 둘 다 본다.

`tests/` 밖에 둔다. 거기 더하면 계획서의 기대 시험 수(135)가 어긋난다. 돌리는 법:

    python .claude/hooks/selftest.py

훅이 실제로 불리는 방식 그대로 `python -S -E 스크립트` 로 띄우고 stdin 에 JSON 을 준다.
골든셋 사례는 작업 트리가 아니라 HEAD 판의 사본으로 만든다. 작업 트리는 작업 중에 달라진다.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
# `--root 경로` 는 스크립트를 제자리에 두기 전에 스크래치패드에서 돌릴 때 쓴다.
ROOT = pathlib.Path(sys.argv[sys.argv.index("--root") + 1]) if "--root" in sys.argv else HERE.parent.parent
COMMIT = HERE / "check_commit_format.py"
BOUNDARY = HERE / "boundary_guard.py"
GOLDENSET = HERE / "goldenset_guard.py"
TRAILER = "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
ENV = {**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT)}

GOOD_TITLE = "docs(eval): J 판 결과 수록. 절차 적중 4/8"
GOOD_BODY = (
    "물음에 절차·갈림·금지 요구를 더한 뒤 첫 판입니다. 기준선과 나란히 적습니다.\n\n"
    "- RESULTS.md. 절차 적중 기준선 문서 6/8 수록\n"
    "- README. 지표 5 수록"
)


def run(script: pathlib.Path, payload=None, args=()) -> tuple[int, str, str]:
    done = subprocess.run(
        [sys.executable, "-S", "-E", str(script), *args],
        input=(json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else b""),
        capture_output=True,
        env=ENV,
        cwd=str(ROOT),
    )
    return done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")


def bash(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def edit(path: pathlib.Path) -> dict:
    return {"tool_name": "Edit", "tool_input": {"file_path": str(path), "old_string": "a", "new_string": "b"}}


def multi_m(title: str, body: str, trailer: str | None = TRAILER) -> str:
    parts = [title, body] + ([trailer] if trailer else [])
    return "git add eval && git commit " + " ".join(f'-m "{p}"' for p in parts)


def heredoc(message: str) -> str:
    return f"git commit -F - <<'EOF'\n{message}\nEOF"


def head_goldenset() -> dict:
    done = subprocess.run(["git", "show", "HEAD:eval/goldenset.json"], cwd=str(ROOT), capture_output=True, check=True)
    return json.loads(done.stdout.decode("utf-8"))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="narrator-hooks-"))
    try:
        same = tmp / "same.json"
        same.write_text(json.dumps(head_goldenset(), ensure_ascii=False), encoding="utf-8")
        altered_doc = head_goldenset()
        first = next(e for e in altered_doc["entries"] if "mustNotClaim" in e)
        first["mustNotClaim"] = list(first["mustNotClaim"]) + ["답을 보고 더한 항목"]
        altered = tmp / "altered.json"
        altered.write_text(json.dumps(altered_doc, ensure_ascii=False), encoding="utf-8")
        good_file = tmp / "good.txt"
        good_file.write_text(f"{GOOD_TITLE}\n\n{GOOD_BODY}\n\n{TRAILER}\n# git 이 붙이는 주석 줄\n#\n", encoding="utf-8")
        noscope_file = tmp / "noscope.txt"
        noscope_file.write_text(f"docs: J 판 결과 수록\n\n{GOOD_BODY}\n\n{TRAILER}\n", encoding="utf-8")

        cases = [
            ("커밋 통과. -m 셋", lambda: run(COMMIT, bash(multi_m(GOOD_TITLE, GOOD_BODY)))[0] == 0),
            ("커밋 통과. 헤어독", lambda: run(COMMIT, bash(heredoc(f"{GOOD_TITLE}\n\n{GOOD_BODY}\n\n{TRAILER}")))[0] == 0),
            ("커밋 거부. scope 없음", lambda: run(COMMIT, bash(multi_m("docs: J 판 결과 수록", GOOD_BODY)))[0] == 2),
            ("커밋 거부. 트레일러 없음", lambda: run(COMMIT, bash(multi_m(GOOD_TITLE, GOOD_BODY, None)))[0] == 2),
            ("커밋 거부. 서술형·em-dash·굵게", lambda: run(COMMIT, bash(multi_m("docs(eval): J 판 결과를 수록한다", "결과가 나왔다 — **표**")))[0] == 2),
            ("커밋 아님. 언급만", lambda: run(COMMIT, bash('grep -rn "git commit" docs'))[0] == 0),
            ("커밋 아님. 다른 명령", lambda: run(COMMIT, bash("ls -l"))[0] == 0),
            ("경계 통과. 저장소 안", lambda: run(BOUNDARY, edit(ROOT / "README.md"))[1] == ""),
            ("경계 거부. 형제 저장소", lambda: "deny" in run(BOUNDARY, edit(ROOT.parent / "[projects] picasso" / "README.md"))[1]),
            ("경계 거부. 정답표", lambda: "deny" in run(BOUNDARY, edit(ROOT / "tests/fixtures/picasso/ground-truth.jsonl"))[1]),
            ("경계 통과. 임시 폴더", lambda: run(BOUNDARY, edit(tmp / "x.md"))[1] == ""),
            ("골든셋 조용함. HEAD 와 같음", lambda: run(GOLDENSET, args=("--check", str(same)))[1].strip() == ""),
            ("골든셋 경고. mustNotClaim 넓힘", lambda: "함정 1" in run(GOLDENSET, args=("--check", str(altered)))[1]),
            ("골든셋 조용함. 훅 모드, 다른 파일", lambda: run(GOLDENSET, {"tool_name": "Edit", "tool_input": {"file_path": str(ROOT / "README.md")}})[1] == ""),
            ("git 훅 통과. --file", lambda: run(COMMIT, args=("--file", str(good_file)))[0] == 0),
            ("git 훅 거부. --file scope 없음", lambda: run(COMMIT, args=("--file", str(noscope_file)))[0] == 1),
        ]

        passed = 0
        for name, check in cases:
            try:
                ok = bool(check())
            except Exception as e:  # noqa: BLE001
                ok, name = False, f"{name} ({type(e).__name__}: {e})"
            passed += ok
            print(("통과  " if ok else "실패  ") + name)
        print(f"{passed}/{len(cases)} 통과")
        return 0 if passed == len(cases) else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
