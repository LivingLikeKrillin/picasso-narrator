#!/usr/bin/env python3
"""골든셋의 채점 규칙이 답을 보고 넓혀지면 알린다.

Claude Code 의 `PostToolUse` 훅이다. `Edit`·`Write` 가 `eval/goldenset.json` 을 건드린 뒤 HEAD
의 판과 대조해, 이미 있던 사건의 `mustNotClaim` 이나 `procedure` 가 바뀌거나 사라졌으면
`decision: block` 으로 사유를 돌려준다. 편집은 이미 됐다. 되돌리는 것이 아니라 알리는 것이다.
정말 바꿔야 하면 근거를 커밋 본문에 적는다(`CLAUDE.md` 3절).

새 사건을 더하거나 없던 열쇠(`procedure` 를 처음 적을 때)를 더하는 것은 통과다. 막는 것은
있던 값을 답에 맞춰 고치는 것이다(`STATE.md` 함정 1. 답을 보고 채점 규칙을 넓힌다).

`--check 경로` 는 같은 대조를 그 파일에 돌리고 사유를 stdout 에 낸다. 자가 시험이 쓴다.
판단에 실패하면 통과다(fail-open).
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

TARGET = "eval/goldenset.json"
WATCHED = ("mustNotClaim", "procedure")
TOOLS = {"Edit", "Write", "MultiEdit"}


def entries(doc) -> dict:
    items = doc.get("entries", []) if isinstance(doc, dict) else doc
    return {e["id"]: e for e in items if isinstance(e, dict) and "id" in e}


def drift(before, after) -> list[str]:
    """HEAD 에 있던 사건의 감시 열쇠가 바뀐 자리. 더한 것은 세지 않는다."""
    old, new = entries(before), entries(after)
    out: list[str] = []
    for id_, was in old.items():
        now = new.get(id_)
        if now is None:
            out.append(f"{id_}: 사건이 사라짐")
            continue
        for key in WATCHED:
            if key not in was:
                continue
            if key not in now:
                out.append(f"{id_}.{key}: 사라짐")
            elif now[key] != was[key]:
                out.append(
                    f"{id_}.{key}: 이전 {json.dumps(was[key], ensure_ascii=False)} "
                    f"지금 {json.dumps(now[key], ensure_ascii=False)}"
                )
    return out


def head_version(root: pathlib.Path):
    done = subprocess.run(["git", "show", f"HEAD:{TARGET}"], cwd=str(root), capture_output=True)
    if done.returncode != 0:
        return None
    return json.loads(done.stdout.decode("utf-8"))


def reason_for(path: pathlib.Path, root: pathlib.Path) -> str | None:
    before = head_version(root)
    if before is None:
        return None
    after = json.loads(path.read_text(encoding="utf-8"))
    changes = drift(before, after)
    if not changes:
        return None
    return (
        "골든셋 경고(STATE.md 함정 1): HEAD 에 있던 채점 규칙이 바뀌었다. 답을 보고 넓힌 것이 아닌지 본다. "
        "정말 바꿔야 하면 근거를 커밋 본문에 적는다.\n" + "\n".join(f"  - {c}" for c in changes)
    )


def _canon(path: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(os.path.normcase(str(path.resolve())))


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    root = pathlib.Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    try:
        if len(argv) == 3 and argv[1] == "--check":
            reason = reason_for(pathlib.Path(argv[2]), root)
            if reason:
                print(reason)
            return 0

        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
        if payload.get("tool_name") not in TOOLS:
            return 0
        path_text = (payload.get("tool_input") or {}).get("file_path")
        if not isinstance(path_text, str) or not path_text:
            return 0
        target = pathlib.Path(path_text)
        if not target.is_absolute():
            target = root / target
        try:
            rel = _canon(target).relative_to(_canon(root)).as_posix()
        except ValueError:
            return 0
        if rel != TARGET:
            return 0
        reason = reason_for(target, root)
    except Exception:
        return 0
    if reason is None:
        return 0
    sys.stdout.write(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
