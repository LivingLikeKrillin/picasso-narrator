"""수신기가 한 벌을 읽는 규율 — `BOUNDARY.md` §3.2."""

import pytest

from receiver.export import UnknownSchema, read_export


def test_manifest가_없으면_한_벌이_아니다(tmp_path):
    """내보내는 쪽이 아직 쓰는 중일 수 있다. 반쯤 쓰인 파일을 읽지 않는다."""
    (tmp_path / "incidents.jsonl").write_text(
        '{"incidentId": "incident-1", "digest": "abc"}\n', encoding="utf-8"
    )
    # manifest.json 이 없다 — 한 벌이 다 나오지 않았다는 뜻이다

    assert read_export(tmp_path) is None


def test_기록이_없는_한_벌도_한_벌이다(tmp_path):
    """빈 한 벌과 「한 벌이 아직 아니다」는 다른 상태다. 접으면 구별이 사라진다."""
    (tmp_path / "manifest.json").write_text(
        '{"schemaVersion": "5", "runId": "run-1"}', encoding="utf-8"
    )
    (tmp_path / "incidents.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "remedy-searches.jsonl").write_text("", encoding="utf-8")

    export = read_export(tmp_path)

    assert export is not None
    assert export.incidents == []
    assert export.searches == []


def test_모르는_판은_읽지_않는다(tmp_path):
    """한 벌마다 `schemaVersion` 이 실린다. 모르는 판을 아는 척 읽으면 필드가
    조용히 어긋나고, 그 어긋남이 「값이 없다」로 읽힌다 — 멈추는 쪽이 맞다."""
    (tmp_path / "manifest.json").write_text(
        '{"schemaVersion": "99", "runId": "run-1"}', encoding="utf-8"
    )

    with pytest.raises(UnknownSchema):
        read_export(tmp_path)
