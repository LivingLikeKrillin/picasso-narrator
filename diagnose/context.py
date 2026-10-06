"""검색에 쓰지 않는 답변 컨텍스트 — 진단 계약 0.6 §3.5.

**`query` 는 설명 경로 그대로 두고 나머지를 여기 싣는다.** 후보 · 확인 불가 · 이력 · 답하는 법 넷뿐이다.
「권고」 · 「후보」 같은 단어가 `query` 에 들어가면 BM25 에 걸려 검색이 측정해 온 경로와 달라진다.
스냅샷은 싣지 않는다 — 사실은 `query` 가 이미 든다.

**별칭에 숫자를 쓰지 않는다.** khala 의 숫자 검증기는 10 이상의 정수와 소수를 본다 — 글자 별칭은 숫자
검증기에도 대괄호 인용 해석에도 안 걸린다(khala 회신 15).
"""

import string

from composer.query import UNKNOWN, _flat
from diagnose.contract import ESCALATE

#: khala 가 받는 상한(파이썬 글자 수). 넘으면 422 이고 자르지 않는다 — 이 계층이 먼저 세어 안 보낸다.
LIMIT = 8000

#: 비었을 때 적는 말. 빈 줄로 두면 모델이 「안 적혔다」와 「없다」를 못 가른다.
NONE = "없음"

HOW = (
    "답하는 법: 다섯 표지 줄 앞에 두 줄을 둔다. 일곱 줄 모두 제목(#) · 목록 기호 · 굵게 없이 줄머리에 그대로 쓰고, "
    "값은 표지와 같은 줄에 쓴다.\n"
    "권고: 별칭 하나. 근거가 어느 후보도 뒷받침하지 않으면 ESCALATE.\n"
    "이유: 한두 문장. 문장마다 근거를 인용한다.\n"
    "목록에 없는 조치를 새로 만들지 않는다."
)


class ContextTooLarge(Exception):
    """답변 컨텍스트가 상한을 넘는다. **자르지 않는다** — 자른 후보 목록은 다른 질문이다. 재시도하지 않는다."""


def aliases(candidates):
    """`{별칭: 후보 식별자}`. 후보 순서대로 `A`, `B`, … 이고 `ESCALATE` 는 그대로다.

    :raises ContextTooLarge: ESCALATE 밖의 후보가 26 을 넘을 때 — 글자 별칭이 모자란다.
    """
    letters = iter(string.ascii_uppercase)
    table = {}
    for c in candidates:
        cid = c["candidateId"]
        if cid == ESCALATE:
            table[ESCALATE] = ESCALATE
            continue
        letter = next(letters, None)
        if letter is None:
            raise ContextTooLarge("후보가 26 을 넘어 글자 별칭이 모자란다")
        table[letter] = cid
    return table


def render(candidates, unknowns, history):
    """답변 컨텍스트의 글. 상한을 넘으면 [ContextTooLarge]."""
    by_id = {c["candidateId"]: c for c in candidates}
    lines = ["후보 (별칭 · 식별자 · 대상)"]
    lines += [f"{alias} · {cid} · {_target(by_id[cid])}" for alias, cid in aliases(candidates).items()]
    lines.append("")
    lines += _listed("확인 불가", [_unknown(u) for u in unknowns])
    lines += _listed("이전 시도", [_attempt(h) for h in history])
    lines.append("")
    lines.append(HOW)
    text = "\n".join(lines)
    if len(text) > LIMIT:
        raise ContextTooLarge(f"자료 칸이 {len(text)}자로 상한 {LIMIT}자를 넘는다")
    return text


def _listed(title, items):
    if not items:
        return [f"{title}: {NONE}"]
    return [f"{title}:"] + [f"- {item}" for item in items]


#: 값 하나를 적는다 — **설명 경로의 질의가 값을 적는 규칙 그대로**(`composer.query._flat`). null 은 「모름」,
#: 겹친 값은 되읽을 수 있는 JSON, 참 · 거짓은 `true` · `false`. 두 곳이 다르게 적으면 같은 값이 두 모양이 되고,
#: 파이썬 표기(`None` · `{'id': …}`)가 모델에게 샌다.
_v = _flat


def _target(c):
    """후보가 무엇을 하는지 한 줄. **값은 `ref` 에서만 온다** — 이 계층이 조치를 기술하지 않는다."""
    ref = c.get("ref") or {}
    kind = c["kind"]
    if kind == "APPROVE_REMEDY":
        seen = c.get("sawSkillTypes")
        skills = UNKNOWN if seen is None else ("+".join(seen) or NONE)
        return f"기체 {_v(ref.get('robotId'))} · 주문 {_v(ref.get('jobOrderId'))} 의 제안 조치({skills})를 승인"
    if kind == "CHOOSE_SOURCE":
        return (f"주문 {_v(ref.get('jobOrderId'))} 의 자재 {_v(ref.get('material'))} 를 "
                f"원래 슬롯 {_v(ref.get('missingSource'))} 대신 대체 위치 {_v(ref.get('alternative'))} 에서")
    if kind == "OPERATOR_DECISION":
        return (f"실행 {_v(ref.get('executionId'))} · 단위 {_v(ref.get('unitId'))} 에 "
                f"운영자 판단 {_v(ref.get('decision'))}")
    return "사람에게 넘긴다"


def _unknown(u):
    """확인 불가 항목 한 줄. **시각(`since`)은 싣지 않는다** — 답변 컨텍스트의 숫자는 khala 가 근거로 세므로
    (`found_in` 의 `context`), 시각 하나가 여러 수를 근거에 넣는 질의의 약점을 여기 다시 들이게 된다."""
    # 탐색 식별자는 추적용이라 싣지 않는다 — 후보 줄(`_target`)과 같은 선이고, 10 이상의 수를 답변 컨텍스트에 들인다
    subject = " · ".join(f"{k}={_v(v)}" for k, v in (u.get("subject") or {}).items()
                         if k != "searchId") or UNKNOWN
    return f"{subject} 의 {_v(u.get('what'))} ({_v(u.get('source'))})"


def _attempt(h):
    diagnosis = h.get("diagnosis") or {}
    approval = h.get("approval")
    dispatch = h.get("dispatch")
    evidence = h.get("evidence")
    parts = [
        f"진단 {_v(diagnosis.get('outcome'))} {diagnosis.get('candidateId') or '-'}",
        f"승인 {_v(approval.get('result'))}/{_v(approval.get('by'))} {_v(approval.get('reason'))}"
        if approval else f"승인 {NONE}",
        f"전송 {_v(dispatch.get('result'))}" if dispatch else f"전송 {NONE}",
        f"근거 {_v(evidence.get('grade'))} {_v(evidence.get('outcome'))}" if evidence else f"근거 {NONE}",
        f"닫힘 {_v(h.get('closedAs'))}",
    ]
    return f"시도 {_v(h.get('attempt'))}: " + " · ".join(parts)
