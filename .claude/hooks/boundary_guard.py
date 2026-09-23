#!/usr/bin/env python3
"""편집 도구가 이 저장소 밖과 정답표를 건드리지 못하게 한다.

Claude Code 의 `PreToolUse` 훅이다. `Edit`·`Write`·`NotebookEdit` 의 대상 경로를 보고 둘을
막는다.

- 형제 저장소. 이 저장소의 부모 폴더 아래이면서 이 저장소 밖인 경로. picasso 와 khala 가
  거기 있다. 서로 참조하지 않는다는 사실이 경계의 증명이고(`BOUNDARY.md`), 편의로 한 번
  넘으면 증명이 소멸한다. 필요한 것은 `correspondence/` 에 자체 완결된 요청으로 쓴다
- 정답표. `tests/fixtures/picasso/ground-truth.jsonl` 은 picasso 의 것이고 채점에서만 읽는다.
  새 판은 저쪽 `handoff/narrator/` 에서 Bash `cp` 로 복사한다(`STATE.md` 함정 1)

부모 폴더 밖(임시 폴더·홈·메모리)은 통과다. 읽기는 막지 않는다. 형제 저장소를 읽는 것은
요청을 쓰기 위해 필요하다.

막을 때는 stdout 에 `permissionDecision: deny` JSON 을 내고 0 으로 끝난다. 판단에 실패하면
통과다(fail-open). 훅이 자기 오류로 편집을 전부 막으면 아무도 못 고친다.

⛔ 순서. 이 스크립트가 먼저 있고 `.claude/settings.json` 이 나중이다(2026-09-20 실측,
`check_commit_format.py` 머리말).
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}

# 저장소 안이지만 편집 도구로 열지 않는 파일. 열쇠는 소문자 posix 상대 경로다.
LOCKED = {
    "tests/fixtures/picasso/ground-truth.jsonl": (
        "정답표는 picasso 의 것이다. 편집하지 않는다(STATE.md 함정 1). 새 판은 picasso 의 "
        "handoff/narrator/ground-truth.jsonl 을 Bash cp 로 복사한다"
    ),
}


def _canon(path: pathlib.Path) -> pathlib.Path:
    """대소문자와 구분자를 정규화한 절대 경로. Windows 에서 같은 파일이 두 글꼴로 오는 것을 막는다."""
    return pathlib.Path(os.path.normcase(str(path.resolve())))


def judge(path_text: str, root: pathlib.Path) -> str | None:
    """막을 이유. 통과면 None."""
    target = pathlib.Path(path_text)
    if not target.is_absolute():
        target = root / target
    target, root = _canon(target), _canon(root)

    try:
        inside = target.relative_to(root).as_posix()
    except ValueError:
        inside = None
    if inside is not None:
        return LOCKED.get(inside)

    try:
        sibling = target.relative_to(root.parent).as_posix()
    except ValueError:
        return None
    return (
        f"저장소 경계: {sibling} 는 이 저장소 밖(형제 저장소)이다. 만들거나 고치지 않는다. "
        "필요한 것은 correspondence/ 에 자체 완결된 요청으로 쓴다(CLAUDE.md 2절)"
    )


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
        if payload.get("tool_name") not in TOOLS:
            return 0
        tool_input = payload.get("tool_input") or {}
        path_text = tool_input.get("file_path") or tool_input.get("notebook_path")
        if not isinstance(path_text, str) or not path_text:
            return 0
        root = pathlib.Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
        reason = judge(path_text, root)
    except Exception:
        return 0
    if reason is None:
        return 0
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    # ASCII 로 낸다. 콘솔 코덱이 cp949 여도 JSON 은 깨지지 않는다.
    sys.stdout.write(json.dumps(out, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
