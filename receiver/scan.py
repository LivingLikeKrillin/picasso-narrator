"""한 벌을 훑어 설명할 것을 고른다 — `BOUNDARY.md` §3.1.

**처리 표시는 읽는 쪽의 상태다.** 내보내는 쪽은 누가 어디까지 읽었는지 모른다.
"""

from dataclasses import dataclass, field

from receiver.approval import candidates
from receiver.cursor import select_unprocessed
from receiver.export import read_export
from receiver.history import subject


@dataclass(frozen=True)
class Batch:
    """이 한 벌에서 아직 설명이 안 붙은 것.

    **두 줄기를 합치지 않는다**(§4.1) — 둘은 다른 순간을 적고 짝이 대개 없다.
    합쳐 내면 부르는 쪽이 갈래를 다시 나눠야 하고 그 규칙이 두 곳에 생긴다.
    """

    incidents: list
    searches: list
    manifest: dict
    #: 이 한 벌의 **모든** 사건의 주체 — 이미 설명한 것까지. 재발을 셀 이력이다.
    history: list = field(default_factory=list)
    #: 이 한 벌에서 **부를 수 있는 제안 전부** — 설명이 붙었는지와 무관하다. 승인 시도는 설명의
    #: 옆이지 뒤가 아니라(불변식 3) 미처리분(`searches`)이 아니라 전체에서 고른다. 이 중 이
    #: 구동에서 아직 안 부른 것은 `approval.pending` 이 대장으로 거른다.
    proposals: list = field(default_factory=list)


def scan(directory, seen):
    """한 벌을 훑는다. **한 벌이 아직 아니면 `None`.**

    `None` 과 빈 [Batch] 는 다른 답이다 — 앞은 「내보내는 쪽이 아직 쓰는 중」이고
    뒤는 「다 나왔는데 새것이 없다」다. 접으면 스캔이 멈춘 것과 조용한 것이 같아진다.
    """
    export = read_export(directory)
    if export is None:
        return None
    return Batch(
        incidents=select_unprocessed(export.incidents, export.manifest, seen),
        searches=select_unprocessed(export.searches, export.manifest, seen),
        manifest=export.manifest,
        history=[subject(b) for b in export.incidents],
        proposals=candidates(export.searches),
    )
