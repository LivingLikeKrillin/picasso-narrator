"""글 칸 둘 — 인용 없는 문장과 확인 못 한 주장(진단 계약 0.6 §4).

**이 층이 결정적으로 센다.** khala 에 새 검사를 요구하지 않는다. 인용 검증기는 「인용한 제목이 꾸러미에
있었나」만 보고 인용이 안 붙은 문장은 누구도 안 센다 — 그래서 여기서 센다.

**두 목록은 `None` 이 아니다.** koshei 의 자동 승인 조건(`requireClean`)이 「비었다」를 기준으로 삼으므로
비었다는 것이 「확인 못 한 것이 없다」를 뜻해야 한다. 그래서 개수만 아는 것도 항목으로 싣는다.
"""

import re

#: 문장 끝 — 마침표 · 물음표 · 느낌표. **뒤에 빈칸이 오거나 글 조각이 거기서 끝날 때만** 문장이 끝난다.
#: 「§15.90」 · 「2.5」 는 뒤에 글자가 붙어 안 끝나고, 괄호 안(「[출처: SOP-02, §3.2. 파지]」)은 글 조각이 아니다.
_ENDS = ".!?。"

#: 대괄호 한 무리. 닫히지 않은 `[` 는 무리가 아니라 글이다 — khala 도 닫히지 않은 인용은 안 센다.
_GROUP = re.compile(r"\[[^\[\]]*\]")

#: khala 의 인용 표기(`[출처: 제목, 절]`), 닫힌 것만.
_CITATION = re.compile(r"\[출처:[^\]]*\]")

#: 문장에 글이 있나 — 글자나 숫자가 하나라도.
_WORD = re.compile(r"[0-9A-Za-z가-힣]")


def uncited_sentences(rationale, citations):
    """[rationale] 의 문장 가운데 인용이 없는 것, 글 그대로. [rationale] 이 없으면 `[]`.

    **인용 괄호는 앞 문장의 것이다.** 괄호 앞에 이 문장의 글이 있으면 이 문장의 인용이고, 문장이 막 끝난
    자리(「…한다.[출처: …]」 · 「…한다. [출처: …]」)에 오면 끝난 문장의 인용이다. 인용은 닫힌 `[출처: …]` 이거나,
    대괄호 안이 `citations` 의 한 제목으로 시작하는 것이다 — **khala 의 해석보다 좁다**(`[근거 N]` · 제목
    앞부분 · 대소문자를 접은 제목은 안 센다). 좁게 틀리면 인용된 문장을 인용 없다고 적는 쪽이라 자동 승인을
    막는다 — 넓게 틀려 인용 없는 문장을 가리는 것보다 낫다.
    """
    if not rationale:
        return []
    titles = tuple(c["title"] for c in citations if c.get("title"))
    return [text for text, cited in _sentences(rationale.strip(), titles) if not cited]


def unverified_claims(citations, diagnostics):
    """`[{kind, text, foundIn}]`. 비었으면 `[]`.

    `CITATION` — `verified` 가 참이 아닌 인용. `NUMBER` — khala 숫자 항목 가운데, `found_in` 이 있으면
    근거(`evidence`)도 자료 칸(`context`)도 없는 것, 없으면 `grounded` 가 참이 아닌 것. 숫자 항목이 없는
    응답(옛 응답, 또는 기록기가 모르는 모양이라 `None` 으로 둔 것)은 `unverified_numbers` 개수만큼 `text` 가
    `None` 인 항목.
    """
    claims = [{"kind": "CITATION", "text": _cite_text(c), "foundIn": None}
              for c in citations if c.get("verified") is not True]
    numbers = diagnostics.get("numbers")
    if numbers is None:
        count = diagnostics.get("unverified_numbers") or 0
        return claims + [{"kind": "NUMBER", "text": None, "foundIn": None} for _ in range(count)]
    for n in numbers:
        found = n.get("found_in")
        if found is not None:
            if "evidence" in found or "context" in found:
                continue
            claims.append({"kind": "NUMBER", "text": _number_text(n), "foundIn": list(found)})
        elif n.get("grounded") is not True:  # 있었다는 말이 없으면 걸린 수다 — verified 와 같은 쪽
            claims.append({"kind": "NUMBER", "text": _number_text(n), "foundIn": None})
    return claims


def _sentences(text, titles):
    """`[(문장, 인용 있음)]`. 글 조각과 괄호 무리를 차례로 보며 문장을 짓는다."""
    done, cur, cited, pos = [], "", False, 0
    for group in [*_GROUP.finditer(text), None]:
        plain = text[pos:group.start()] if group else text[pos:]
        start = 0
        for i, ch in enumerate(plain):
            if ch in _ENDS and (i + 1 == len(plain) or plain[i + 1].isspace()):
                cur += plain[start:i + 1]
                if _WORD.search(cur):
                    done.append([cur.strip(), cited])
                cur, cited, start = "", False, i + 1
        cur += plain[start:]
        if group is None:
            break
        mark = _is_citation(group.group(0), titles)
        if done and not _WORD.search(cur):  # 문장이 막 끝난 자리의 괄호 — 끝난 문장의 것이다
            done[-1][0] += cur + group.group(0)
            done[-1][1] = done[-1][1] or mark
            cur = ""
        else:
            cur += group.group(0)
            cited = cited or mark
        pos = group.end()
    if _WORD.search(cur):
        done.append([cur.strip(), cited])
    return [(sentence, mark) for sentence, mark in done]


def _is_citation(group, titles):
    if _CITATION.fullmatch(group):
        return True
    return bool(titles) and group[1:-1].strip().startswith(titles)


def _cite_text(c):
    return ", ".join(str(x) for x in (c.get("title"), c.get("section")) if x)


def _number_text(n):
    """khala 의 `value`. ⛔ **끝의 쉼표를 뗀다** — 숫자 뒤 문장부호 쉼표가 붙는 khala 결함(회신 16).
    판정은 정규형이라 맞고 표시만 틀리다. khala 가 고치면 이 줄은 할 일이 없어진다."""
    value = n.get("value")
    return value.rstrip(",") if isinstance(value, str) else value
