"""번들에서 질의를 만든다 — `BOUNDARY.md` §1.

**새 사실을 만들지 않는다.** 번들은 각자의 자리가 이미 답한 것을 모은 파생값이고
(`ADR 40`), 이 층이 하는 일은 그 사실을 옮겨 싣는 것뿐이다. 없는 것을 「없음」이라는
사실로 바꾸지도 않는다 — 널은 「못 물어봤다·판정 못 했다」이지 「아니다」가 아니다.

**예외는 하나다 — `recurrenceSeen`.** 이 층이 본 기록 안에서 같은 기체·같은 분류가 몇 번
앞서 있었나를 센 값이고 번들에 없다. 세는 것이지 판정이 아니며 `BOUNDARY.md` §1 이 그것을
선언한다(`receiver/history.py`). **0 은 「없었다」가 아니라 「이 층이 본 것 중에는 없다」다.**

**그리고 하나를 추린다 — `resolution`.** 판 5 의 사람의 걸음에서 결정과 가상 시각만 싣고
실 시계를 뺀다(2026-09-23). 값을 바꾸는 것이 아니라 칸을 고르는 것이고, 왜인지는
`RESOLUTION_CARRIED` 가 적는다.
"""

import json
from dataclasses import dataclass

from composer.fields import ABSENT, read_field

#: 질의에 실을 번들의 칸. **여기 없는 칸은 안 싣는다** — 늘리려면 이 목록을 늘린다.
#: 검색에 붙는 물음. **고정이다.**
#:
#: 사건마다 다르게 지으면 그 문장을 고르는 것이 곧 사건의 성격을 단정하는 것이 되고,
#: 그 판단에는 근거가 없다. 그렇다고 빼서도 안 된다 — 사실만 나열해 보내면 모델이
#: 그것을 **용어 해설 요청으로 받는다**(2026-09-18 실물에서 확인). 필드마다 뜻을
#: 풀어 주는 답이 오고, 사건은 설명되지 않는다.
#:
#: 물음이 답을 담지 않는 것이 조건이다. 원인을 지목하는 낱말이 여기 들어가면
#: 그건 묻는 것이 아니라 판정하는 것이다.
#: **운영자 화면에는 번들이 이미 있다.** `BOUNDARY.md` §3.3 대로 `t0+δ` 에 사건이
#: 화면에 나타나고 설명은 나중에 채워지는 칸이다. 답이 사실을 다시 나열하면 같은
#: 것이 화면에 두 번 실리고, **출력 생성이 비용이므로 그 중복이 곧 지연이다**
#: (2026-09-19 — 답 3,000자에 176초가 들었고 그중 상당량이 재나열과 요약표였다).
SCREEN_NOTE = "사실은 운영자 화면에 이미 있다. 다시 나열하지 말고 요약도 따로 두지 마라."

#: **이것은 줄이지 않는다.** 「설계와 직접 일치」와 「인과는 미확정」을 가르는 것이
#: 이 층의 산출물이다. 분량을 줄이려다 이것까지 자르면 빨라진 대신 쓸모가 없어진다.
CERTAINTY_NOTE = "후보마다 근거가 그것을 직접 뒷받침하는지, 아니면 인과가 미확정인지 밝혀라."

#: 물음에 더한 셋 — **절차 · 갈림 · 금지.**
#:
#: ⛔ **답이 「무엇이 일어났나」에서 끝나고 「무엇을 하나」를 안 담았다**(2026-09-20 실측).
#: 위치 상실 사건의 답이 SOP-05 를 인용하지 않고 다른 SOP 넷을 「해당 없음」으로
#: 인용하는 데 2,923자를 썼다. 물음이 원인 후보만 물었기 때문이다. 코퍼스에는 절차가
#: 있었다.
#:
#: **문서 이름을 부르지 않는다.** 「절차 문서」라고만 한다 — 제목을 넣으면 그 픽스처에
#: 맞추는 것이고 지표가 그것을 센다. **원인도 조치도 말하지 않는다.** 근거가 말하는
#: 것을 옮기라고 할 뿐이다. 근거가 없으면 없다고 하라는 문장이 뒤에 그대로 있다.
#:
#: **「파지 상태 기준」은 문장에 넣지 않는다.** 「파지」는 G3 의 금칙어이고 「파지 실패」는
#: G5 의 것이라 금칙어 누수 시험이 빨개진다. 파지 상태는 사실 칸(`observedHold` ·
#: `residualHold`)에 이미 실려 있어 모델이 본다.
#:
#: ⚠ **검색에도 들어간다.** 이 문장은 합성뿐 아니라 검색 질의에도 실리므로 「절차」·
#: 「문서」·「관측」이 bm25 에 걸린다. `LOOKUP` 이 낱말 넷에 밀린 그 취약함이다 —
#: 정지 코드 문서가 상위 20 에서 밀리는지를 J 판에서 G4·G7~G9 로 본다.
PROCEDURE_NOTE = (
    "이 실패를 다루는 절차 문서가 근거에 있으면 그 절차의 첫 걸음을 인용하라. "
    "상위 두 후보를 가를 관측 하나와 그것이 어디에 있는지를 근거가 말하면 적어라. "
    "근거가 하지 말라고 적은 것이 있으면 적어라."
)

#: 답의 앞 다섯 줄. 표지는 `recorder/card.py` 의 것과 같아야 한다 — 파서가 그것을 읽는다.
#: 저쪽 시스템 프롬프트(khala `nexus/nexus/llm/prompts.py` 의 「답변 형식」 절)가 「핵심
#: 답변을 먼저 제시하세요」를 요구하므로 이 요구와 부딪히지 않는다(2026-09-20 확인).
CARD_NOTE = (
    "답의 첫 다섯 줄은 「절차:」「먼저:」「금지:」「갈림:」「근거 세기:」 표지로 시작한다. "
    "표지마다 한 문장과 인용 하나. 근거가 없는 표지는 「근거 없음」이라 적는다. 그 뒤에 본문."
)

#: 탐색 짝이 있을 때만 뜻이 있는 문장. 짝이 없으면 모델이 볼 `remedy*` 칸이 없어 조용히
#: 지나간다. **「맞는가」를 묻지 않는다** — 전제를 사실과 나란히 적으라고만 한다.
REMEDY_NOTE = "제안된 조치가 실려 있으면 그 조치의 전제를 사실과 나란히 적어라."

#: 검색에 붙는 물음. **고정이다.**
#:
#: 사건마다 다르게 지으면 그 문장을 고르는 것이 곧 사건의 성격을 단정하는 것이 되고,
#: 그 판단에는 근거가 없다. 그렇다고 빼서도 안 된다 — 사실만 나열해 보내면 모델이
#: 그것을 **용어 해설 요청으로 받는다**(2026-09-18 실물에서 확인).
#:
#: 물음이 답을 담지 않는 것이 조건이다. 원인을 지목하는 낱말이 여기 들어가면
#: 그건 묻는 것이 아니라 판정하는 것이다.
ASK = (
    "아래는 한 건의 실패에 대해 시스템이 이미 판정해 둔 사실이다. "
    "이 사실들로 좁혀지는 원인 후보를 순위와 근거 인용과 함께 제시하라. "
    + CERTAINTY_NOTE + " "
    + PROCEDURE_NOTE + " "
    + CARD_NOTE + " "
    + REMEDY_NOTE + " "
    + SCREEN_NOTE + " "
    "근거가 없으면 없다고 답하라. 사실에 없는 것을 추측하지 마라. "
    "사실: "
)

CARRIED = (
    # 누가·무엇을·어디서
    "robotId",
    "route",
    "step",
    "intent",
    # 무엇이 일어났고 무엇으로 판정됐나
    "failureClass",
    "fault",
    "blockedBy",
    "preconditionSubjects",
    "residualHold",
    "expectedHold",
    "observedHold",
    "effectMismatch",
    "unresolved",
    # 그 판정이 얼마나 센가
    "requiredEvidence",
    "reachedEvidence",
    "verification",
    # 관측이 온전했나
    "observation",
    "windowTruncated",
    # 그때 무슨 모델이었나
    "profileRevision",
    "contractSemver",
)

#: 사람의 걸음(판 5, 2026-09-23). 실을 칸은 결정과 가상 시각뿐이다 — 실 시계는 사건의
#: `wallClockAt` 과 같은 이유로 안 싣는다(구동마다 다르고, 모델이 오늘과 섞는다 — S1 의 답이 그랬다).
#:
#: ⛔ **없던 칸이라 설명이 그 걸음을 말할 수 없었다 (2026-09-22, 골든셋 판 7 측정).** run-4 의 길은
#: 사건 → 사람의 재작업 → 탐색인데 번들이 그 사이를 안 실어 읽는 쪽이 「자동으로 회복했다」로
#: 메울 수 있었다. 이 층이 물었고 picasso 가 사실로 실었다(`correspondence/`). null 은 「사람이
#: 안 왔다」이고 키 부재는 「이 판이 안 낸다」인데 둘 다 안 싣는다 — 「사람 없음」을 지어내지 않는다.
#: 재는 것은 판독이다 — 질의에 `REWORK` 가 실리므로 낱말을 세면 복창이 통과한다.
RESOLUTION_CARRIED = ("decision", "at")

#: 탐색 대장에서 실을 칸. `outcome` 마다 있는 칸이 다르다 — `FOUND` 에는 `cause` 가
#: 없고 `WITHHELD` 에는 둘 다 없다. **키 부재가 곧 답이므로 채우지 않는다.**
#:
#: ⛔ **전제를 안 실으면 회복이 인계에 닿아도 없는 것과 같다 (2026-09-20 실측).** picasso 가
#: 점유 축으로 계산한 대안 자리를 대장에 실어 보냈는데(적재 규약 판 4) 이 층이 `outcome` 만
#: 옮기고 나머지를 버리고 있었다. `SOURCE_MISSING` 은 결과가 아니라 **전제 넷**이 값이다 —
#: 무엇이 없고 · 어디가 비었고 · 무엇을 관측했고 · 대안이 어디인가.
#:
#: **옳은지는 말하지 않는다.** 대안 자리가 맞는 선택인지는 이 층의 판단이 아니다. 사실로
#: 실어 읽는 사람에게 넘긴다(`BOUNDARY.md` §1).
CARRIED_SEARCH = {
    "outcome": "remedyOutcome",
    "cause": "remedyCause",
    "steps": "remedySteps",
    # `NONE` 이 왜 없는지. `cause` 하나로는 손댈 자리가 안 보인다.
    "unmet": "remedyUnmet",
    # `SOURCE_MISSING` 의 전제 넷. `observed` 가 널이면 안 싣는다 — 「못 봤다」이지
    # 「없었다」가 아니고, 그 구별은 `read_field` 가 지킨다.
    "material": "remedyMaterial",
    "source": "remedySource",
    "observed": "remedyObserved",
    "alternatives": "remedyAlternatives",
}


#: 불투명한 벤더 정지 코드를 들고 있을 때 **앞에 세우는 고정 문장.**
#:
#: ⛔ **번들 1,600자가 희귀 토큰을 덮는다** (실측 2026-09-19). `X_FIXTURE_E4412` 를
#: 단독으로 치면 그 코드를 설명하는 문서가 bm25 1위인데, 번들 질의에 섞으면 **상위 20
#: 에도 안 든다.** 검색이 「이 코드를 설명하는 문서」 대신 「picasso 에 관한 문서」를
#: 집어 오고, 답은 「어댑터가 매핑 못 해서 UNCLASSIFIED」라는 메타 설명으로 끝난다.
#: 골든 넷이 그래서 전부 빗나갔다.
#:
#: **코드를 한 번 더 반복하는 것으로는 안 살아났다.** 살린 것은 문서의 산문과 맞는
#: 의도어다 — 4위로 올라왔다. 검색 예산(top_k)을 20 으로 올려도 안 들어온다.
#:
#: ⚠ **이 문장은 부서지기 쉽다.** 네 낱말을 더한 것만으로 다시 사라졌다:
#:
#:     "… 의 뜻"                          4위
#:     "… 의 뜻을 벤더 문서에서 찾아라."     없음
#:     "합성 기체 정지 코드 표면 …"          3위   ← **문서 제목이다. 안 쓴다**
#:
#: 제목을 넣으면 제일 잘 되는데 그건 **이 픽스처 문서에 맞추는 것**이라 안 한다.
#: 근본은 **검색과 합성이 같은 텍스트를 쓴다**는 것이고, 그 이음매는 저쪽 API 에
#: 아직 없다. 여기 있는 것은 **그때까지의 받침목**이다.
#:
#: ⚠ **문장은 고정이다.** 번들이 정하는 것은 **걸리는지 여부와 코드 값**뿐이다.
#: 사건마다 물음을 지어내면 그 문장을 고르는 것이 곧 판정이 된다([Query.text]).
#: 그리고 **원인을 말하지 않는다** — 필요한 조회의 종류를 말할 뿐이다.
LOOKUP = "벤더 정지 코드 {code} 의 뜻. "


@dataclass(frozen=True)
class Query:
    """검색에 넘길 것.

    [facts] 의 값은 둘을 빼고 번들에서 그대로 온 것이다 — `recurrenceSeen` 은 이 층이
    센 것이고 `resolution` 은 결정과 가상 시각만 추린 것이다. 모듈 머리말이 왜인지를
    적는다.
    """

    facts: dict
    #: 앞에 세울 조회 지시. 번들이 불투명한 코드를 들 때만 값이 있다.
    lookup: str = ""

    @property
    def text(self):
        """검색이 받는 문장. **사실을 나열할 뿐 질문을 지어내지 않는다.**

        물음은 [ASK] 로 **고정**이고 사실은 번들에서 온 것뿐이다 — `recurrenceSeen` 은
        이 층이 센 것, `resolution` 은 칸을 추린 것이고 둘 다 모듈 머리말에 있다. 물음을
        빼면 모델이 사실 나열을 용어 해설 요청으로 받고(2026-09-18 실물 확인), 사건마다
        지어내면 그 문장을 고르는 것이 곧 판정이 된다.
        """
        return self.lookup + ASK + " ".join(
            f"{k}={_flat(v)}" for k, v in self.facts.items()
        )


#: 널을 적는 말. **거짓과 구별돼야 한다.**
#:
#: 이 적재면의 널은 「못 물어봤다·아직 못 봤다」이지 「아니다」가 아니다
#: (`progressObservable` 이 3값인 것이 그 예다). 그냥 빼면 읽는 쪽이 값이 있었던 것처럼
#: 읽고, `false` 로 적으면 못 물어본 것이 못 재는 것이 된다 — 둘 다 이 계열이 막으려는
#: 접힘이다(`AGENT-01` §3 원칙 2).
UNKNOWN = "모름"


def _flat(value):
    """한 값을 적는다. **겹친 것은 되읽을 수 있게 적는다.**

    평평하게 이어 붙이면 경계가 사라진다 — 설비가 셋인데 쉼표로 이으면 어느 것이
    출발이고 어느 것이 도착인지 못 읽고, 읽는 쪽이 잘못 가르면 그럴듯하고 틀린
    설명이 나온다. **충실함이 보기 좋음보다 앞선다.**

    널은 [UNKNOWN] 으로 적는다. 빼면 값이 있었던 것처럼 읽히고 `false` 로 적으면
    못 물어본 것이 못 재는 것이 된다.
    """
    if value is None:
        return UNKNOWN
    if isinstance(value, (dict, list)):
        return json.dumps(_marked(value), ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _marked(value):
    """겹친 값 안의 널도 [UNKNOWN] 으로 바꾼다 — JSON 의 `null` 은 「없다」로 읽히기 쉽다."""
    if value is None:
        return UNKNOWN
    if isinstance(value, dict):
        return {k: _marked(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_marked(v) for v in value]
    return value


def compose(bundle, search=None, recurrence=None):
    """번들 하나를, 짝이 있으면 탐색 하나와 함께 질의로 옮긴다.

    **짝은 대개 없다.** 탐색은 접수 관문 안에서 돌고 관문이 막으면 실행이 안
    생기므로 거절은 사건이 되지 않는다. 반대로 실행 중의 실패는 사건이 되지만 그
    자리에서 탐색이 돌지 않는다. 그래서 `search` 가 `None` 인 것이 정상이고,
    그때 **「대안 없음」이라고 적지 않는다** — 돌지도 않은 탐색을 「찾아봤지만
    없다」로 지어내는 것이 된다.

    **널과 키 부재는 둘 다 안 싣는다.** 앞은 그 자리가 판정하지 못한 것이고 뒤는
    이 판이 그 칸을 안 내는 것인데, 어느 쪽이든 **말할 수 있는 사실이 아니다.**
    실어 보내면 설명이 「어긋남 없음」처럼 없는 판정을 지어낸다.

    사람의 걸음(`resolution`)은 있을 때만, 결정과 가상 시각만 싣는다 — 결정도 시각도
    없는 걸음은 빈 사실이라 안 싣는다.
    """
    facts = {}
    for key in CARRIED:
        value = read_field(bundle, key)
        if value is ABSENT or value is None:
            continue
        facts[key] = value

    # 사람의 걸음. 있을 때만, 실 시계는 빼고.
    resolution = read_field(bundle, "resolution")
    if isinstance(resolution, dict):
        step = {k: resolution[k] for k in RESOLUTION_CARRIED if k in resolution}
        if step:  # 결정도 시각도 없는 걸음은 빈 사실이다 — 안 싣는다
            facts["resolution"] = step

    for key, name in CARRIED_SEARCH.items():
        value = read_field(search or {}, key)
        if value is ABSENT or value is None:
            continue
        facts[name] = value

    # **이 층이 보태는 유일한 사실.** 안 주어지면 안 싣는다 — 0 으로 지어내지 않는다.
    # 주어지면 0 도 싣는다: 「이 층이 본 것 중 없다」도 사실이다(`receiver/history.py`).
    if recurrence is not None:
        facts["recurrenceSeen"] = recurrence

    return Query(facts=facts, lookup=_lookup(bundle))


def _lookup(bundle):
    """불투명한 정지 코드를 들고 있나. 들면 [LOOKUP] 을, 아니면 빈 문자열.

    **분류가 붙었으면 안 세운다** — 매핑된 코드는 이름이 뜻을 말하므로 이미 있는
    답을 문서에서 다시 찾게 만들고 검색 예산을 엉뚱한 데 쓴다. **코드가 없어도
    안 세운다** — 없는 것을 찾으라고 하면 없는 문서를 뒤지고, 그 결과가
    「근거 없음」으로 읽힌다.
    """
    if read_field(bundle, "failureClass") != "UNCLASSIFIED":
        return ""
    fault = read_field(bundle, "fault")
    code = (fault or {}).get("vendorDetail") if isinstance(fault, dict) else None
    return LOOKUP.format(code=code) if code else ""


#: 탐색 줄만으로 질의를 세울 때 싣는 칸. 사건의 칸과 겹치지 않는다.
CARRIED_STANDALONE = ("robotId", "jobOrderId")


def compose_search(record):
    """짝이 되는 사건이 없는 탐색 줄 하나를 질의로 옮긴다.

    **질의 종류가 둘인 이유**(`BOUNDARY.md` §4.1) — 탐색은 접수 관문 안에서 돌고
    관문이 막으면 실행이 안 생기므로 대부분의 탐색 줄에는 사건이 없다. 사건을 억지로
    찾아 붙이려 하면 못 찾고, 못 찾은 자리를 지어내게 된다.

    여기에는 근거 창도 효과 어긋남도 없다. **없는 것을 없다고 적지도 않는다** —
    이 줄이 답한 것은 탐색의 결과 하나뿐이다.
    """
    facts = {}
    for key in CARRIED_STANDALONE:
        value = read_field(record, key)
        if value is not ABSENT and value is not None:
            facts[key] = value
    for key, name in CARRIED_SEARCH.items():
        value = read_field(record, key)
        if value is not ABSENT and value is not None:
            facts[name] = value
    return Query(facts=facts)
