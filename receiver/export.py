"""한 벌 읽기 — `BOUNDARY.md` §3.2 의 적재 규약."""

import json
from dataclasses import dataclass

MANIFEST = "manifest.json"
INCIDENTS = "incidents.jsonl"
SEARCHES = "remedy-searches.jsonl"


#: 이 층이 읽을 줄 아는 적재 규약의 판(picasso `LedgerExport.SCHEMA_VERSION`).
#: 내보내는 쪽이 한 벌마다 싣는 이유가 **읽는 쪽이 멈출 수 있게** 하려는 것이다.
#:
#: ⛔ **3 에서 4 로 올랐다 (2026-09-20).** 사건 줄은 그대로다 — 칸 집합도 `digest` 도
#: 안 바뀌었다. 바뀐 것은 탐색 대장뿐이고 **더해지기만 했다**: `outcome` 에
#: `SOURCE_MISSING` 갈래가 생기고, `NONE` 에 `cause`·`unmet` 이, `SOURCE_MISSING` 에
#: `material`·`source`·`observed`·`alternatives` 가 붙었다. 이 층이 요청한 「점유 축으로
#: 계산된 회복이 인계에 닿게」의 답이다(`correspondence/`).
#:
#: ⛔ **4 에서 5 로 올랐다 (2026-09-23).** 사건 줄에 `resolution` 칸이 는다 — 사람이 그 단위에
#: 낸 판단(`decision` REWORK | CONFIRM_DONE · `at` 가상 시계 · `wallClockAt` 실 시계)이고 내기
#: 전에는 null 이다. 「사람이 안 왔다」와 「왔는데 안 적혔다」를 가르려고 키를 안 뺀다. 요약
#: (`digest`)은 안 바뀐다 — 해시에서 빠지는 것이 `wallClockAt` · `review` · `resolution` 셋이다.
#: 탐색 줄은 그대로다. run-4 의 길(사건 → 사람의 재작업 → 탐색)에서 그 걸음이 안 보여 이 층이
#: 물었고 picasso 가 실었다(`correspondence/`). 4 는 이제 안 읽는다 — 네 벌을 다 5 로 다시 받았다.
#:
#: **한 판만 받는다.** 범위로 받으면 모르는 판을 아는 척 읽게 되고, 그때 어긋난 칸이
#: 이 층에서는 「값이 없다」로 보인다 — 형식이 바뀐 것과 관측이 없는 것이 같은 모양이 된다.
SCHEMA_VERSION = "5"


class UnknownSchema(Exception):
    """모르는 판이다. **아는 척 읽지 않는다.**

    모르는 판을 읽으면 필드가 조용히 어긋나고, 그 어긋남이 이 층에서는 「값이 없다」로
    읽힌다 — 형식이 바뀐 것과 관측이 없는 것이 같은 모양이 된다.
    """


@dataclass(frozen=True)
class Export:
    """한 벌. **두 대장을 합치지 않는다** — 합치면 갈래를 나누는 규칙이 두 곳에 생긴다."""

    incidents: list
    searches: list
    manifest: dict


def read_export(directory):
    """한 벌을 읽는다. **한 벌이 아직 아니면 `None`.**

    내보내는 쪽은 임시 파일에 쓰고 이름만 바꾸며, 마지막에 `manifest.json` 이
    나타나는 것이 한 벌이 다 나왔다는 신호다. 그것이 없는 동안 읽으면 반쯤 쓰인
    파일을 읽는다.

    **없음과 빈 것을 접지 않는다** — `None` 은 「한 벌이 아직 아니다」이고, 기록이
    없는 한 벌은 빈 한 벌로 온다.
    """
    manifest_path = directory / MANIFEST
    if not manifest_path.exists():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    found = manifest.get("schemaVersion")
    if found != SCHEMA_VERSION:
        raise UnknownSchema(f"읽을 줄 아는 판은 {SCHEMA_VERSION!r} 인데 {found!r} 가 왔다")
    return Export(
        incidents=_read_lines(directory / INCIDENTS),
        searches=_read_lines(directory / SEARCHES),
        manifest=manifest,
    )


def _read_lines(path):
    """줄 단위. 배열이 아니라 줄인 이유는 덧붙이기가 줄 추가로 그대로 옮겨지기 때문이다."""
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
