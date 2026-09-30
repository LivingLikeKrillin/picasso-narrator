"""답의 머리 줄 — 진단 계약 0.6 §4.

**파싱은 결정적이다.** 표지가 없으면 없는 것이고 지어내지 않는다. 앞 [HEAD_LINES] 줄만 본다 — khala
프롬프트의 규칙 둘(약한 근거는 첫 문장에서 · 여러 부분이면 몇 부분인지)이 표지 앞에 줄을 세울 수 있어
첫 줄만 보면 안 되고, 본문 한가운데의 「권고:」는 머리 줄이 아니라 끝까지 보면 안 된다. 다섯 표지는
설명 경로의 카드 파서(`recorder/card.py`)를 그대로 쓴다.
"""

import re

from recorder.card import HEAD_LINES, LABELS, parse_card

#: 머리 두 줄. 카드 파서와 같은 꾸밈(글머리표 · 굵게)에 더해 **줄머리의 제목 기호(#)를 받는다** — ⛔ 첫 실물 진단에서
#: 모델이 표지 줄을 「## 권고: ESCALATE」로 꾸몄다(2026-09-30). 다섯 표지는 설명 경로의 카드 파서 그대로라 여기서 안
#: 넓힌다 — 설명 측정의 카드 완결 수가 같은 파서를 쓴다. **값이 비어도 표지 줄이다** — 첫 표지 줄이 정하고, 비었다고 뒤의
#: 줄로 넘어가지 않는다(계약 §4 판정 5).
_HEAD = re.compile(r"^\s*(?:#{1,6}\s*)?(?:[-*]\s*)?(?:\*\*)?(권고|이유)(?:\*\*)?\s*[:：]\s*(?:\*\*)?\s*(.*?)\s*$")

#: 다섯 표지 줄의 머리 — 본문에서 뺄 줄을 알아보는 데만 쓴다. 표지는 카드 파서의 것 그대로다.
_CARD = re.compile(r"^\s*(?:[-*]\s*)?(?:\*\*)?(?:" + "|".join(map(re.escape, LABELS)) + r")(?:\*\*)?\s*[:：]")

#: 가리킨 값에서 벗길 꾸밈 — 굵게 · 코드 · 따옴표 · 괄호. 벗긴 자리는 빈칸이 된다.
_DECOR = re.compile(r"[`*\"'“”‘’「」『』<>\[\]()（）]")

#: 낱말의 경계 — 빈칸 · 가운뎃점 · 쉼표.
_SPLIT = re.compile(r"[\s·,，、]+")

#: 낱말 끝의 한글 — 토씨(「A를」 · 「ESCALATE도」). 떼고 본다. 한글만인 낱말은 통째로 빠진다.
_PARTICLE = re.compile(r"[가-힣]+$")

#: 후보를 가리키려 한 낱말의 모양 — 글자 별칭 하나, ESCALATE, 후보 종류로 시작하는 식별자. **대소문자를
#: 가리지 않는다** — 「Escalate」 · 「b」 도 가리키려 한 것이다. 망설임을 알아보는 쪽은 넓게 본다.
_PICKLIKE = re.compile(r"[A-Z]|ESCALATE|(?:APPROVE_REMEDY|CHOOSE_SOURCE|OPERATOR_DECISION):\S+", re.I)

#: 머리와 본문 사이의 구분선.
_RULE = re.compile(r"\s*-{3,}\s*")


def head_value(answer, label):
    """앞 [HEAD_LINES] 줄 가운데 줄머리가 `label:` 인 첫 줄의 값. 그런 줄이 없으면 `None`, 있는데 비었으면 `""`."""
    for line in (answer or "").splitlines()[:HEAD_LINES]:
        match = _HEAD.match(line)
        if match and match.group(1) == label:
            return match.group(2)
    return None


def card_items(answer):
    """다섯 표지를 `[{label, text}]` 로. **표지 순서대로, 있는 것만.**"""
    card = parse_card(answer)
    return [{"label": label, "text": card[label]} for label in LABELS if label in card]


def body(answer):
    """표지 줄들 **뒤의** 본문 — 응답의 `cause`(계약 §4). 비면 `None`.

    머리는 앞 [HEAD_LINES] 줄 안의 첫 표지 줄(권고 · 이유 · 다섯)에서 시작해 표지 줄과 빈 줄이 이어지는
    데까지다 — **글이 있는 다른 줄이 오면 머리가 끝난다.** 그래서 본문 첫머리의 「- 먼저: …」 같은 글머리표
    줄이 머리로 끌려가지 않는다. 표지 앞 머리말(「세 부분입니다」 같은)은 khala 프롬프트 규칙이 세운 줄이라
    본문이 아니다. 머리와 본문 사이의 빈 줄과 구분선(`---`)도 뺀다. 표지 줄이 없으면 답 전체가 본문이다.
    """
    lines = (answer or "").splitlines()
    head = [i for i, line in enumerate(lines[:HEAD_LINES]) if _marker(line)]
    last = -1
    if head:
        last = head[0]
        for i in range(head[0] + 1, min(len(lines), HEAD_LINES)):
            if _marker(lines[i]):
                last = i
            elif lines[i].strip():
                break
    rest = lines[last + 1:]
    while rest and (not rest[0].strip() or _RULE.fullmatch(rest[0])):
        rest = rest[1:]
    text = "\n".join(rest).strip()
    return text or None


def resolve(value, table):
    """표지 값이 가리키는 후보 식별자. 못 찾으면 `None`.

    **하나만 가리켜야 한다.** 첫 낱말(끝의 한글 토씨를 뗀 것)이 별칭(`A`)이나 식별자 전체와 **글자 그대로**
    맞고, 나머지 낱말 가운데 후보를 가리키려 한 것(토씨를 떼고 대소문자를 가리지 않고 본 글자 별칭 ·
    ESCALATE · 식별자 모양)이 **모두 같은 후보**일 때만 그 후보다. 「A 아니면 ESCALATE」 · 「A 또는 B를」 ·
    「A 아니면 Escalate」에서 A 를 고르면 모델이 망설인 것을 이 층이 정한 것이 되고, 후보 밖 비율이 그만큼
    가려진다. 같은 후보를 풀어 적은 것(「A (APPROVE_REMEDY:…)」)은 받는다. ⚠ 낱말로만 망설인 것(「A, 아니면
    사람에게 넘긴다」)은 못 가른다 — 알려진 한계다.

    :param table: `{별칭: 식별자}` (`diagnose.context.aliases`).
    """
    tokens = [t.rstrip(".。:;") for t in _SPLIT.split(_DECOR.sub(" ", value or ""))]
    tokens = [t for t in tokens if t]
    if not tokens:
        return None
    # 첫 낱말은 제자리에서 본다 — 토씨만 떼고, 한글뿐인 낱말(「후보 A」의 「후보」)은 그대로 둬 후보 밖이 된다
    first = _lookup(_PARTICLE.sub("", tokens[0]) or tokens[0], table)
    if first is None:
        return None
    for token in tokens[1:]:
        core = _PARTICLE.sub("", token)
        if core and _PICKLIKE.fullmatch(core) and _lookup(core, table) != first:
            return None
    return first


def _marker(line):
    return bool(_HEAD.match(line) or _CARD.match(line))


def _lookup(token, table):
    if token in table:
        return table[token]
    return token if token in table.values() else None
