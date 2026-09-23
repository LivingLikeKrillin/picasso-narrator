"""기록 하나를 스택 없이 되감아 보인다 — `RESULTS.md` 「다시 재는 법」의 옆."""

from eval.replay import card_lines, replay, summary_line

NEW = {"id": "G3", "kind": "incident", "outcome": "GIVEN", "reason": "", "latencies": [118.2],
       "citations": 12, "verified": 12, "answerLen": 3309, "violations": ["파지", "적재"],
       "truthHit": [], "answer": "**절차:** SOP-05 …",
       "card": {"절차": "SOP-05 다", "먼저": "적재 상태부터", "금지": "수동 이동 금지",
                "갈림": "recurrenceSeen", "근거 세기": "E0"}}
OLD = {"id": "G1", "outcome": "GENERATION_FAILED", "reason": "timeout", "answer": ""}


def test_요약_줄은_옛_판의_빈_칸을_견딘다():
    """I 판 기록(`722bebe`)에는 `card` 가 없고 가장 이른 판(`653defc`)에는 `latencies` 도 `kind` 도
    없다(2026-09-22 실측). 한 모양만 읽으면 기준선 판을 되감을 수 없다 — `rescore.rows_of` 가
    두 모양을 읽는 것과 같은 이유다."""
    line = summary_line(OLD)

    assert line.startswith("G1")
    assert "GENERATION_FAILED" in line
    assert "사유=timeout" in line
    assert "카드 0/5" in line


def test_요약_줄이_어긋남과_카드_수를_든다():
    line = summary_line(NEW)

    assert "인용 12/12" in line
    assert "카드 5/5" in line
    assert "어긋남:파지,적재" in line


def test_카드는_있는_그대로_보이고_없으면_없다고_말한다():
    """지어내지 않는다. 표지가 없는 줄에 카드를 만들어 보이면 되감기가 기록보다 낫게 보인다."""
    assert card_lines(NEW)[0] == "G3 절차: SOP-05 다"
    assert len(card_lines(NEW)) == 5
    assert card_lines(OLD) == ["G1: 카드 없음"]


def test_되감기는_요약과_카드와_고른_본문을_차례로_낸다():
    lines = replay([NEW, OLD], env={"arm": "T2"}, show={"G3"})

    assert lines[0].startswith("환경 ")
    assert any(line.startswith("G3 ") and "incident" in line for line in lines)
    assert "G3 절차: SOP-05 다" in lines
    assert "===== G3 본문 =====" in lines
    assert not any("G1 본문" in line for line in lines)


def test_모르는_줄을_고르면_그렇게_말한다():
    """⛔ **Chunk 2 검토가 찾았다 (2026-09-22).** `--show` 가 여럿을 받으므로 경로를 그 뒤에 적으면
    경로가 id 로 읽히고 기본 기록이 되감긴다 — 엉뚱한 판의 그럴듯한 되감기가 아무 말 없이 나온다.
    기록에 없는 id 는 이름을 들어 멈춘다."""
    from eval.replay import unknown_ids

    assert unknown_ids([NEW, OLD], {"G3", "ZZZ", "eval/old.json"}) == ["ZZZ", "eval/old.json"]
    assert unknown_ids([NEW, OLD], set()) == []
