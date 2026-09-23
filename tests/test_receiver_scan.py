"""한 벌을 훑어 설명할 것을 고른다 — `BOUNDARY.md` §3.1, §4.1."""

from receiver.scan import scan


def test_두_줄기를_각각_낸다(export_dir):
    """**합쳐 내지 않는다.** 사건과 탐색은 다른 순간을 적고 짝이 대개 없다(§4.1).
    한 목록으로 내면 부르는 쪽이 갈래를 다시 나눠야 하고 그 규칙이 두 곳에 생긴다."""
    batch = scan(export_dir("run-1"), seen=set())

    # **manifest 가 센 수와 맞아야 한다.** 숫자를 여기 박으면 한 벌이 늘 때마다
    # 고쳐야 하고, 고치는 동안 「내가 몇 개를 빠뜨렸나」는 아무도 안 본다.
    assert len(batch.incidents) == batch.manifest["counts"]["incidents"]
    assert len(batch.searches) == batch.manifest["counts"]["remedySearches"]


def test_한_벌이_아니면_훑지_않는다(tmp_path):
    """`None` 과 빈 결과는 다른 답이다 — 앞은 「내보내는 쪽이 아직 쓰는 중」이고
    뒤는 「다 나왔는데 새것이 없다」다. 접으면 **스캔이 멈춘 것과 조용한 것이
    같아진다.**"""
    (tmp_path / "incidents.jsonl").write_text("", encoding="utf-8")

    assert scan(tmp_path, seen=set()) is None


def test_다_본_한_벌은_비어서_돌아온다(export_dir):
    """`None` 이 아니다. 한 벌은 다 나왔고 새것이 없을 뿐이다."""
    first = scan(export_dir("run-1"), seen=set())
    seen = {k for k in _keys(first)}

    again = scan(export_dir("run-1"), seen=seen)

    assert again is not None
    assert again.incidents == []
    assert again.searches == []


def test_다음_구동은_같은_내용이라도_새것이다(export_dir):
    """`digest` 도 `searchId` 도 같은 시드면 그대로 반복된다. 실행을 안 보면
    두 번째 구동이 통째로 접히고 설명이 하나도 안 붙는다."""
    seen = {k for k in _keys(scan(export_dir("run-1"), seen=set()))}

    nxt = scan(export_dir("run-2"), seen=seen)

    assert len(nxt.incidents) == nxt.manifest["counts"]["incidents"]
    assert len(nxt.searches) == 4


def _keys(batch):
    from receiver.idempotency import idempotency_key

    for record in batch.incidents + batch.searches:
        yield idempotency_key(record, batch.manifest)


def test_한_벌의_주체를_전부_든다(export_dir):
    """이미 설명한 사건도 이력이다. 안 그러면 같은 한 벌 안의 앞선 사건이 안 세진다."""
    from receiver.scan import scan

    batch = scan(export_dir("run-1"), seen=set())
    assert len(batch.history) == 9
    assert {"robotId", "failureClass", "digest"} <= set(batch.history[0])


def test_부를_수_있는_제안은_설명_여부와_무관하게_든다(export_dir):
    """승인 시도는 설명의 뒤가 아니라 옆이다(불변식 3). 이미 설명한 줄도 시도 대상이므로
    `searches`(미처리분)가 아니라 한 벌 전체에서 고른다 — `history` 와 같은 이유다."""
    from receiver.idempotency import idempotency_key

    first = scan(export_dir("run-1"), seen=set())
    seen = {idempotency_key(r, first.manifest) for r in first.incidents + first.searches}

    again = scan(export_dir("run-1"), seen=seen)

    assert again.searches == []
    assert [s["searchId"] for s in again.proposals] == ["search-1"]
