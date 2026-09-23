"""옛 기록을 스택 없이 다시 센다 — `RESULTS.md` 「다시 재는 법」."""

from eval.rescore import records_from_rows, rows_of
from recorder.outcome import Outcome


def test_옛_판과_새_판의_기록_모양을_둘_다_읽는다():
    """⛔ I 판 기록(`722bebe`)은 **줄의 배열**이고 `env` 가 없다 — `measure.py` 가
    `{"env", "rows"}` 로 바뀐 것이 그 2분 뒤다. 한 모양만 읽으면 기준선을 못 낸다."""
    assert rows_of([{"id": "G1"}]) == ([{"id": "G1"}], None)
    assert rows_of({"env": {"top_k": 20}, "rows": [{"id": "G1"}]}) == ([{"id": "G1"}], {"top_k": 20})


def test_기록의_줄을_채점할_기록으로_되돌린다():
    """`last-answers.json` 의 줄에는 인용 객체가 없고 본문과 갈래만 있다. 절차 적중은
    본문으로 세므로 그것으로 충분하다."""
    rows = [
        {"id": "G3", "outcome": "GIVEN", "answer": "[출처: SOP-05 자기 위치 상실 복구, 4. 절차]",
         "diagnostics": {"evidenceDocs": ["SOP-05 자기 위치 상실 복구"]}},
        {"id": "G1", "outcome": "GENERATION_FAILED", "answer": ""},
    ]

    records = records_from_rows(rows)

    assert records[0].outcome is Outcome.GIVEN
    assert "SOP-05" in records[0].answer
    assert records[1].outcome is Outcome.GENERATION_FAILED
    assert records[0].key == ("rescore", "G3")
    # ⛔ 계측을 빠뜨리면 검색이 준 문서를 다시 셀 수 없다(2026-09-20 실측).
    assert records[0].diagnostics["evidenceDocs"] == ["SOP-05 자기 위치 상실 복구"]
    assert records[1].diagnostics == {}, "계측이 없는 줄은 빈 사전이지 None 이 아니다"


def test_골든셋과_안_맞는_기록은_다시_세지_않는다(tmp_path):
    """⛔ **골든셋이 자라면 옛 기록은 다시 셀 수 없다**(2026-09-20 실측 — v6 이 탐색 줄 하나를
    더하자 12줄짜리 L 판 기록이 안 맞았다). 조용히 어긋난 채 세면 엉뚱한 항목에 점수가 붙는다.
    무엇이 안 맞는지를 말하고 멈춘다."""
    import json

    import pytest

    from eval.rescore import load_rows

    path = tmp_path / "answers.json"
    path.write_text(json.dumps({"env": {"goldensetVersion": 5}, "rows": [{"id": "G1"}]}),
                    encoding="utf-8")

    with pytest.raises(SystemExit) as stopped:
        load_rows(path)

    assert "골든셋과 기록이 안 맞는다" in str(stopped.value)
