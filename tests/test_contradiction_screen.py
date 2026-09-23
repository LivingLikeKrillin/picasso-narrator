"""어긋남 지표가 무엇을 못 잡는지 못 박는다 — `RESULTS.md` 「지표 2」.

⛔ **이 지표는 지표가 아니라 선별기다 (2026-09-20 판정).** 판 넷에서 일곱 번 걸렸고 일곱 번 다
배제 문맥이었다(「빈손으로 실패한 것이 아니라」·「파지 문제의 대상도 아니다」). 참 양성은 아직
하나도 없다.

그래서 물어야 할 것이 하나 남는다. **참 양성이 0 인 것이 이 층이 안 어긋나서인가, 아니면
다르게 쓰면 안 걸려서인가.** 구별하지 않으면 「어긋나지 않았다」가 근거 없는 안심이 된다.

여기 있는 시험은 **일부러 어긋난 답**을 써서 선별기에 먹인다. 답은 번들과 정반대인데 골든셋의
금칙어를 **하나도 쓰지 않는다.** 실제 판의 답이 아니라 내가 지어낸 것이라 골든셋을 건드리지
않고, 답을 보고 채점을 고치는 함정(`STATE.md` 함정 1)에도 안 걸린다.

**결과를 고치려고 쓰는 시험이 아니다.** 한계를 수치가 아니라 시험으로 적어 두는 것이 목적이다.
"""

from eval.score import score
from recorder.outcome import Outcome
from recorder.record import Record

GIVEN = Outcome.GIVEN


def _entry(id_, must_not_claim):
    return {"id": id_, "kind": "incident", "mustNotClaim": must_not_claim}


def _answer(text):
    return Record(key=("red", "x"), outcome=GIVEN, answer=text)


#: 번들과 정반대인 답 셋. 괄호 안이 그 번들의 관측이다.
#: **셋 다 골든셋의 금칙어를 하나도 안 쓴다.**
PARAPHRASED = [
    # G2 — expectedHold·observedHold 가 둘 다 HOLDING 인데 적재물을 잃었다고 주장한다.
    (["떨어뜨", "놓쳤", "빈손", "EMPTY"],
     "그리퍼가 대상을 끝까지 유지하지 못한 채 동작이 종료되었습니다. "
     "적재물은 로봇의 손을 벗어난 것으로 보입니다."),
    # G6 — linkBroken=true 인데 관측이 온전했다고 주장한다.
    (["관측이 완전", "모두 관측", "끊김 없"],
     "사건 구간의 이벤트 열은 처음부터 끝까지 빠짐없이 수신되었으므로, "
     "이 판정은 관측의 공백 없이 내려진 것입니다."),
    # G9 — lateEvents 가 비어 있고 windowTruncated 가 거짓인데 이벤트를 놓쳤다고 주장한다.
    (["이벤트 유실", "늦게 도착", "이벤트가 누락"],
     "일부 전이 기록이 시간창 밖에서 도착해 창 안에 담기지 못했습니다. "
     "그래서 지금 보이는 열은 실제로 일어난 것의 일부입니다."),
]


def test_금칙어를_피해_어긋나면_선별기가_못_잡는다():
    """⛔ **낱말을 바꾸면 통과한다 (2026-09-20 실측).** 셋 다 번들과 정반대인데 만점이다.

    그러니 **어긋남 만점은 「안 어긋났다」가 아니라 「이 낱말들로는 안 어긋났다」다.**
    판 넷의 참 양성 0 이 이 층의 안전을 뜻한다고 읽으면 안 된다.

    이 시험이 빨개지면(선별기가 셋 중 하나라도 잡으면) 그것은 좋은 소식이고, 그때
    `RESULTS.md` 의 「지표 2」 절과 이 시험의 기대를 같이 고친다.
    """
    entries = [_entry(f"R{i}", words) for i, (words, _) in enumerate(PARAPHRASED)]
    records = [_answer(text) for _, text in PARAPHRASED]

    result = score(entries, records)

    assert result.contradiction_free == 1.0, "선별기가 낱말 밖의 어긋남을 잡기 시작했다"
    assert result.counted_checked == 3


def test_금칙어를_그대로_쓰면_잡는다():
    """재현율이 0 은 아니다. 목록에 있는 낱말을 그대로 쓰면 걸린다 — 선별기가 도는 것은
    맞고, 못 보는 자리가 낱말 밖이라는 뜻이다."""
    entries = [_entry("R0", ["떨어뜨"])]
    records = [_answer("로봇이 적재물을 떨어뜨렸습니다.")]

    assert score(entries, records).contradiction_free == 0.0


def test_배제_문맥도_똑같이_잡는다():
    """**실제로 걸린 일곱이 전부 이 꼴이다.** 「아니라고 말한 것」과 「말한 것」을 안 가른다.
    정밀도가 0 인 자리이고, 여기를 고치려면 답을 보고 채점을 고치게 되므로 안 고친다."""
    entries = [_entry("R0", ["떨어뜨"])]
    records = [_answer("관측상 쥔 채였으므로 떨어뜨린 것이 아닙니다.")]

    assert score(entries, records).contradiction_free == 0.0
