#!/usr/bin/env python3
"""커밋 메시지의 형식을 강제한다.

picasso 의 `.claude/hooks/check-commit-pr-format.py` 를 이 저장소에 맞게 줄인 것이다. 같은
검사가 두 자리에서 돈다.

- Claude Code 의 `PreToolUse` 훅. `Bash` 를 가로채 `git commit` 이 명령 자리에 서면 메시지를
  뽑아 검사한다. 어기면 종료 코드 2 로 막고 사유를 stderr 로 돌려준다
- git 의 `commit-msg` 훅(`scripts/hooks/commit-msg`). `--file 경로` 로 같은 검사를 돌리고 어기면
  1 로 끝낸다. 편집기로 쓰든 다른 도구가 쓰든 같은 문이 닫힌다

picasso 와 다른 것 둘. scope 를 비우지 못한다(`docs:` 가 아니라 `docs(eval):`). 트레일러는
`Claude Opus 5` 로 고정이다. 이력 56건이 전부 그 줄이고, 실행 모델이 무엇이든 이력을 두 갈래로
가르지 않는다. `-m` 이 여럿이면 git 처럼 빈 줄로 이어 하나의 메시지로 본다.

**막는 것만 검사한다.** 거짓 실패를 내는 검사는 곧 꺼진다.

⛔ 순서. 이 스크립트가 먼저 있고 `.claude/settings.json` 이 나중이다. 설정을 먼저 쓰면 감시기가
그 자리에서 훅을 켜고, 없는 스크립트를 부르는 python 이 2 로 끝나 모든 Bash 와 편집이 막힌다
(2026-09-20 실측. 사람이 빈 스크립트를 만들어 줘야 풀렸다).
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import traceback

TYPES = "feat|fix|docs|refactor|perf|test|build|ci|chore|style|revert"

# scope 는 필수다. picasso 는 `(\(…\))?` 로 비워 둘 수 있게 했고, 이 저장소는 그 자리를 닫는다.
COMMIT_TITLE = re.compile(rf"^({TYPES})\([a-z0-9,\-]+\): \S")

# 금지 문자. em-dash 와 겹화살괄호·낫표는 초안에만 나타나고 정렬된 이력에는 없다.
BANNED_CHARS = {
    "—": "em-dash(—)",
    "–": "en-dash(–)",
    "«": "겹화살괄호(«)",
    "»": "겹화살괄호(»)",
    "「": "낫표(「)",
    "」": "낫표(」)",
    "『": "겹낫표(『)",
    "』": "겹낫표(』)",
}

TRAILER = "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"

FENCE = re.compile(r"^\s*```")
INLINE_CODE = re.compile(r"`[^`]*`")
# 합니다체가 아닌 서술형 종결. 명사형 항목은 `다` 로 끝나지 않으므로 걸리지 않는다.
PLAIN_TAIL = re.compile(r"(?<!니)다$")
# git 이 `-v` 로 붙이는 가위선. 그 아래는 diff 라 메시지가 아니다.
SCISSORS = "# ------------------------ >8 ------------------------"

# `-m "…"` · `-am "…"` · `--message "…"` · `--message="…"`. 앞의 `(?<![\w-])` 는
# `--allow-empty-message` 같은 긴 옵션 안의 글자를 집지 않기 위한 것이다.
MESSAGE_FLAG = re.compile(r"(?:(?<![\w-])-[a-zA-Z]*m|--message)(?:\s+|=)(\"([^\"]*)\"|'([^']*)')")


def heredocs(command: str, owner: "re.Pattern[str] | None" = None) -> list[str]:
    """`<<'EOF' … EOF` 본문. 셸이 아니라 텍스트로 읽는다.

    여는 줄이 누구의 것인지 본다. 한 명령에 헤어독이 여럿일 수 있고(파일을 쓰고 이어서
    커밋하는 경우), 첫 것을 무조건 집으면 엉뚱한 본문을 검사한다.
    """
    owned, other = [], []
    lines = command.split("\n")
    i = 0
    while i < len(lines):
        opened = re.search(r"<<-?\s*'?([A-Za-z_][A-Za-z0-9_]*)'?", lines[i])
        if not opened:
            i += 1
            continue
        head, delimiter = lines[i], opened.group(1)
        body, i = [], i + 1
        while i < len(lines) and lines[i].strip() != delimiter:
            body.append(lines[i])
            i += 1
        (owned if owner and owner.search(head) else other).append("\n".join(body))
        i += 1
    return owned or other


def AT_COMMAND(verb: str) -> "re.Pattern[str]":
    """명령 자리에 선 것만. 줄머리이거나 `;` `&&` `||` `|` `(` `&` 뒤다.

    따옴표 안의 인자로 적힌 `git commit` 까지 발동하면 이 규칙을 다루는 문서를 쓸 때마다 막힌다.
    """
    return re.compile(rf"(?:^|[\n;&|(]|&&|\|\|)\s*(?:sudo\s+)?{verb}\b", re.M)


def shell_part(command: str) -> str:
    """헤어독 본문을 걷어낸 명령. 여는 줄은 남긴다. 거기 명령이 적혀 있다."""
    out, lines, i = [], command.split("\n"), 0
    while i < len(lines):
        out.append(lines[i])
        opened = re.search(r"<<-?\s*'?([A-Za-z_][A-Za-z0-9_]*)'?", lines[i])
        if not opened:
            i += 1
            continue
        delimiter = opened.group(1)
        i += 1
        while i < len(lines) and lines[i].strip() != delimiter:
            i += 1
        i += 1
    return "\n".join(out)


def quoted_all(command: str) -> str | None:
    """`-m "…"` 전부. 여럿이면 git 처럼 빈 줄로 잇는다.

    picasso 의 `quoted` 는 첫 것만 집는다. 이 저장소의 계획서는 제목·본문·트레일러를 `-m` 셋으로
    주므로 하나만 보면 트레일러가 없다는 거짓 실패가 난다.
    """
    parts = [
        hit.group(2) if hit.group(2) is not None else hit.group(3)
        for hit in MESSAGE_FLAG.finditer(command)
    ]
    return "\n\n".join(parts) if parts else None


def from_file(command: str, flag: str) -> str | None:
    """`-F 경로` 처럼 파일로 준 본문. `-` 는 표준 입력이므로 헤어독이 답한다."""
    hit = re.search(rf"(?<![\w-]){flag}\s+(\"([^\"]+)\"|'([^']+)'|([^\s]+))", command)
    if not hit:
        return None
    path = hit.group(2) or hit.group(3) or hit.group(4)
    if not path or path == "-":
        return None
    try:
        return pathlib.Path(path).read_text(encoding="utf-8")
    except OSError:
        return None


def prose_lines(text: str) -> list[tuple[int, str]]:
    """펜스 밖의 줄만. 코드 블록 안의 문장은 문체 검사 대상이 아니다."""
    out, fenced = [], False
    for n, line in enumerate(text.split("\n"), 1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced:
            out.append((n, INLINE_CODE.sub("`…`", line)))
    return out


def banned(text: str, where: str, bad: list[str]) -> None:
    for ch, name in BANNED_CHARS.items():
        if ch in text:
            bad.append(f"{where}: {name} 를 쓰지 않는다")


def check_commit(message: str, bad: list[str]) -> None:
    lines = message.split("\n")
    title = lines[0].strip()

    if not COMMIT_TITLE.match(title):
        bad.append(f"커밋 제목: `type(scope): 명사구` 형식이 아니다. scope 를 비우지 않는다. {title!r}")
    if PLAIN_TAIL.search(title.rstrip(".")):
        bad.append(f"커밋 제목: 서술형으로 끝난다. 명사로 끝낸다(구현·처리·추가·정비·수록). {title!r}")

    banned(message, "커밋", bad)
    if "**" in message:
        bad.append("커밋: 굵게(**)를 쓰지 않는다")

    for n, line in prose_lines(message):
        if n == 1 or line.startswith("Co-Authored-By"):
            continue
        if PLAIN_TAIL.search(line.rstrip().rstrip(".")):
            bad.append(f"커밋 {n}행: 서술형 종결. 합니다체나 명사형으로 적는다. {line.strip()[:60]!r}")

    if TRAILER not in message:
        bad.append(f"커밋: 트레일러가 없거나 다르다. 실행 모델과 무관하게 이 줄이다. {TRAILER}")


def message_from(command: str, shell: str) -> str | None:
    bodies = heredocs(command, AT_COMMAND(r"git\s+commit"))
    return (
        quoted_all(shell)
        or (bodies[0] if bodies else None)
        or from_file(shell, r"-F")
        or from_file(shell, r"--file")
    )


def check_command(command: str) -> list[str]:
    """Bash 명령 하나에서 찾은 위반. 커밋이 아니면 빈 목록."""
    shell = shell_part(command)
    if AT_COMMAND(r"git\s+commit").search(shell) is None:
        return []
    if "--amend" in shell and "-m" not in shell and "-F" not in shell:
        return []
    bad: list[str] = []
    message = message_from(command, shell)
    if message is None:
        bad.append("커밋: 메시지를 못 읽었다. -m 이나 -F - 와 헤어독으로 준다")
    else:
        check_commit(message, bad)
    return bad


def message_file(path: str) -> str:
    """git 이 commit-msg 훅에 넘긴 파일. `#` 줄과 가위선 아래는 git 도 버린다."""
    raw = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    kept: list[str] = []
    for line in raw.split("\n"):
        line = line.rstrip("\r")
        if line.startswith(SCISSORS):
            break
        if line.startswith("#"):
            continue
        kept.append(line)
    return "\n".join(kept).strip("\n")


def report(bad: list[str]) -> str:
    return (
        "커밋 형식 위반. 규약은 CLAUDE.md 4절과 STATE.md 의 쓰는 규약 절이다.\n"
        + "\n".join(f"  - {b}" for b in bad)
        + "\n\n형식: 제목은 `type(scope): 명사구` 이고 scope 를 비우지 않는다. 본문은 합니다체 산문 뒤에"
        " `명사구. 부연 ~함/~임` 목록이다. 마지막 줄은 " + TRAILER
    )


def main(argv: list[str]) -> int:
    # 인코딩을 못 박는다. Windows 의 기본 코덱이 cp949 라 그대로 쓰면 한글이 깨진다.
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    try:
        if len(argv) == 3 and argv[1] == "--file":
            message = message_file(argv[2])
            # git 이 스스로 만드는 제목은 규약 밖이다. 빈 메시지는 git 이 알아서 거절한다.
            if not message or message.startswith(("Merge ", 'Revert "')):
                return 0
            bad: list[str] = []
            check_commit(message, bad)
            if not bad:
                return 0
            print(report(bad), file=sys.stderr)
            return 1

        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
        if payload.get("tool_name") != "Bash":
            return 0
        command = payload.get("tool_input", {}).get("command", "")
        if not isinstance(command, str) or not command:
            return 0
        bad = check_command(command)
        if not bad:
            return 0
        print(report(bad), file=sys.stderr)
        return 2
    except Exception:
        # 훅 자신의 오류로 모든 Bash 를 막지 않는다. 사유는 보이게 남긴다.
        traceback.print_exc(file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
