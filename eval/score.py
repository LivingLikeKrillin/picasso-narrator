"""세 지표 산출 — `AGENT-04` §4.

**채점은 순수 함수다.** 호출과 섞으면 수치를 다시 내려면 매번 스택이 살아 있어야
하고, 그러면 평가가 인프라에 묶인다. 여기 들어오는 것은 이미 받아 둔 기록이다.

**수치는 작아도 되고, 낮게 나오면 낮은 채로 적는다.** 평가 체계가 있다는 것이
산출물이다.
"""

import re
from dataclasses import dataclass

from recorder.card import LABELS, parse_card
from recorder.outcome import Outcome

INCIDENT = "incident"
QUERY = "query"
#: 짝이 되는 사건이 없는 탐색 대장의 줄. **사건과 분모를 합치지 않는다** — 합치면
#: 판 사이 비교가 깨지고, 이 둘은 답해야 할 것이 다르다.
SEARCH = "search"

#: picasso 의 설계 일지 제목. **골든셋 설계가 이 문서 안에 있다.**
#:
#: ⛔ 그 일지(`superpowers/specs/2026-09-05-picasso-design.md`)는 **삭제하지 않는 기록**이라
#: 코퍼스에 남고 검색이 집어 온다. 실제로 답 하나가 벤더 문서 대신 이것을 인용해
#: `E9001` 의 성질을 설명했다 — 「둘 중 하나를 지목하는 답은 근거가 없다」를 거의
#: 그대로 옮겨 적었다. picasso 가 `limits.md` §15.181 로 **제외를 받는 쪽 몫**으로 넘겼다.
#:
#: ⚠ **제목으로 문다.** 인용에 실려 오는 것이 제목뿐이라 그렇다. 저쪽이 제목을 바꾸면
#: 이 배제가 조용히 멈춘다 — 아래 시험이 실물 인용을 쓰지 않으므로 그것도 안 걸린다.
DESIGN_JOURNAL = "picasso — 이기종 로봇 표준 I/F 계약과 운영 변경 체계"


@dataclass(frozen=True)
class Score:
    """세 지표. **잴 것이 없으면 `None` 이고 0 이 아니다.**

    0 은 「해봤는데 못 했다」이고 `None` 은 「잴 것이 없었다」다. 접으면 평가표가
    아무도 안 읽었을 때와 완벽했을 때를 같게 보인다 — `ReviewMetrics` 가 이의율을
    널로 두는 것과 같은 이유다.
    """

    primary_cause_match: float = None
    #: 금칙어가 답에 **없던** 비율. 금칙어는 질의에 없으므로 메아리로 통과할 수 없다.
    #:
    #: ⛔ **이것은 지표가 아니라 선별기다 (2026-09-20 판정).** 처음 설계는 「금칙어는 답이
    #: 번들과 반대로 갔을 때만 쓰는 말」이라는 가정에 섰는데, **그 가정이 측정으로
    #: 뒤집혔다.** 판 넷에서 일곱 번 걸렸고 일곱 번 다 배제 문맥이었다 — 조심하는 답일수록
    #: 무엇을 배제하는지 이름을 부르기 때문이다. 정밀도가 0/7 이다.
    #:
    #: ⛔ **그리고 낱말을 바꾸면 통과한다.** 금칙어를 피해 번들과 정반대로 쓴 답 셋이
    #: 만점을 받는다(`tests/test_contradiction_screen.py`). 그러니 **만점은 「안 어긋났다」가
    #: 아니라 「이 낱말들로는 안 어긋났다」다.** 참 양성 0 을 안전으로 읽으면 안 된다.
    #:
    #: **고치지 않는다.** 배제 문맥을 가르려면 답을 보고 채점을 손보게 되고(`STATE.md`
    #: 함정 1), 한국어 부정 처리를 어설프게 넣으면 재현율이 **조용히** 떨어진다. 대신
    #: 못 보는 자리를 시험으로 못 박고 자동 수치 옆에 판독을 함께 적는다.
    contradiction_free: float = None
    citation_pass: float = None
    admits_no_evidence: float = None
    counted_incidents: int = 0
    #: 설명이 안 선 사건. **분모에서 빼되 수를 드러낸다** — 조용히 빼면 비율이 부푼다.
    #: 정답표와 무관하게 센다. 묶어 두면 정답을 빼는 순간 0 이 된다.
    failed_incidents: int = 0
    #: 답은 냈는데 인용이 0 이던 사건. **실패가 아니라 분모에 남는다** — 그래서
    #: 따로 안 세면 평가표에서 사라지고, 「설명됐다」에 조용히 섞인다. 검증할
    #: 인용이 없는 답과 근거가 붙은 답은 운영자에게 다른 것이다.
    uncited_incidents: int = 0
    #: 설계 일지를 근거로 든 답. **지표 1 의 분모에서 뺀 수다.**
    #: 틀렸다고 세지 않는다 — 추론한 것인지 정답 설계를 되읽은 것인지 밖에서 못 가른다.
    #: 조용히 빼면 비율이 부푸니 수를 드러낸다.
    journal_cited_incidents: int = 0
    #: 근거에 없는 숫자가 있던 답. Nexus 가 답의 유의미한 숫자를 보여준 근거와 값-일치로
    #: 대조한 결과다(`nexus/llm/numbers.py`).
    #:
    #: ⛔ **「지어낸 통계」로 읽으면 안 된다**(실측 2026-09-19). 이 층의 답에는 수치 주장이
    #: 사실상 없다 — 아홉 답을 훑어 단위 붙은 수를 하나도 못 찾았다. 답의 숫자는 거의 전부
    #: **인용의 절 번호**다(§15.148 · §4.4 · §3.2). 그러니 여기서 걸리는 것은 대개
    #: **안 본 절을 짚은 것**이고, 작지만 다른 축이다.
    #:
    #: ⚠ **어느 숫자가 걸렸는지는 못 본다.** 저쪽이 개수만 내보낸다(`numbers` 목록은
    #: 내부에만 있다). 그래서 위 판단도 **답 전체의 숫자 분포에서 미룬 것**이지 걸린
    #: 그 숫자를 본 것이 아니다.
    #:
    #: **비율로 만들지 않는다** — 사람이 열어 볼 수다.
    ungrounded_number_incidents: int = 0
    #: 답이 **그 실패 분류를 다루는 절차 문서**를 인용한 비율. 정답은 코퍼스의 SOP §2
    #: 적용 범위 표와 정지 코드 문서의 조치 절에서 오고(골든셋 `procedure`), **답을
    #: 보고 정하지 않는다.**
    #:
    #: ⛔ **위치 상실 사건의 답이 SOP-05 를 안 인용했는데 네 지표가 만점이었다**
    #: (2026-09-20 실측). 다른 SOP 넷을 「해당 없음」으로 인용하는 데 2,900자를 썼다.
    #: 기존 지표는 안전만 재고 「무엇을 하나」는 안 쟀다.
    #:
    #: ⚠ **제목으로 문다** — `DESIGN_JOURNAL` 과 같은 취약함이다. 저쪽이 제목을 바꾸면
    #: 이 지표가 조용히 0 이 된다. 정지 코드 문서의 H1 은 원문에 백틱이 있지만 인용
    #: 제목에서는 벗겨져 오므로 골든셋은 백틱 없이 적는다.
    procedure_doc_cited: float = None
    #: 그 문서의 **절차 절**까지 인용한 비율. 목적 절만 인용한 답은 여기서 떨어진다.
    #: 상위 절(§3 전체)이나 하위 절(§5.1)은 적중으로 친다 — 저쪽 표기가 섞여 온다.
    procedure_section_cited: float = None
    counted_procedures: int = 0
    #: 검색이 **그 절차 문서를 돌려준** 비율. 위 둘과 나누는 이유가 있다.
    #:
    #: ⛔ **절차 적중은 이 층이 아니라 검색을 재고 있었다 (2026-09-20 K 판 실측).**
    #: 문서 4/8 중 못 짚은 넷은 **검색이 그 문서를 아예 안 줬고**, 받은 넷은 넷 다
    #: 인용했다. 남의 층의 실패를 이 층의 점수로 적으면 안 되고, 저쪽이 검색을 고쳤을 때
    #: 뛴 수를 이 층의 개선으로 오독하게 된다.
    #:
    #: **없으면 `None` 이고 0 이 아니다.** 0 은 「검색이 안 줬다」이고 `None` 은 「검색이
    #: 무엇을 줬는지 기록에 없다」다 — `evidenceDocs` 는 2026-09-20 에 생겨 I·J 판 기록에
    #: 없다.
    #: 탐색 줄이 **그 조치를 쓸 조건을 적은 절**을 인용한 비율. **사건과 분모를 합치지
    #: 않는다** — 합치면 앞 판들과 같은 수가 아니게 되고, 둘은 답해야 할 것이 다르다.
    #: 사건은 「무엇을 하나」이고 탐색 줄은 「그 조치를 쓰려면 무엇이 참이어야 하나」다.
    #:
    #: ⛔ **picasso 가 요청받아 낸 회복이 여기서만 재어진다 (2026-09-20).** 점유 축으로
    #: 계산한 대안 자리가 대장에 실려 오는데, 그것을 재는 자리가 골든셋에 없었다.
    #: 표본이 하나라 `1/1` 이나 `0/1` 로만 적힌다.
    search_procedure_cited: float = None
    counted_searches: int = 0
    procedure_doc_retrieved: float = None
    #: **받은 것 중** 인용한 비율. 이것이 이 층의 몫이다. K 판은 4/4 다.
    procedure_cited_when_retrieved: float = None
    counted_retrieved: int = 0
    counted_citations: int = 0
    counted_queries: int = 0
    counted_checked: int = 0
    #: 답 앞의 카드가 다섯 줄 다 있던 사건 수. **비율로 만들지 않는다** — 형식이 섰는지
    #: 보는 수이지 품질이 아니다.
    cards_complete: int = 0


def score(entries, records, truth=None):
    """골든셋과 그 기록을 나란히 놓고 센다. 순서가 같아야 한다.

    `truth` 는 `incidentId` 로 물린 정답표다(`eval/run.py::load_truth`). **골든셋이
    아니라 거기서 정답을 읽는다** — 정답이 질의 만드는 파일 옆에 살면 언젠가 섞인다.

    **정답표의 `cause` 는 선택적으로 읽는다.** 같은 원인의 다른 표현들이라 하나만
    맞으면 된 것이다. 골든셋에 직접 적던 옛 `expectedCause` 는 접속적이었고
    (기종만 좁힌 답을 틀렸다고 세려던 것), 둘은 다른 종류의 목록이다.
    """
    truth = truth or {}
    incidents = [(e, r) for e, r in zip(entries, records) if e["kind"] == INCIDENT]
    queries = [(e, r) for e, r in zip(entries, records) if e["kind"] == QUERY]
    searches = [(e, r) for e, r in zip(entries, records) if e["kind"] == SEARCH]

    # **튜플의 진위를 보지 않는다.** `_expected` 는 `(말, 선택적인가)` 를 돌려주므로
    # 빈 튜플이 아니고, 그대로 걸면 정답 없는 사건까지 분모에 든다 — 지표가 널이
    # 아니라 **0 에 가까운 수로** 틀려서 눈으로 안 잡힌다(2026-09-19 실측 1/4 → 1/9).
    labelled = [(e, r) for e, r in incidents if _expected(e, truth)[0]]
    # **설계 일지를 근거로 든 답은 뺀다**(picasso `limits.md` §15.181). 그 문서에
    # 골든셋 설계가 있어서, 추론한 답과 되읽은 답이 구별되지 않는다. 과잉 배제다 —
    # 일지를 다른 주장의 근거로 들고 원인은 벤더 문서에서 가져온 답도 같이 빠진다.
    # **표본이 주는 쪽으로 틀리므로 그쪽을 택한다.**
    journal = [(e, r) for e, r in labelled if _spoiled(e, r)]
    labelled = [(e, r) for e, r in labelled if not _spoiled(e, r)]
    # **실패한 건은 분모에서 뺀다.** 답이 없는 것은 틀린 원인이 아니라 원인이 없는
    # 것이다. 그리고 강등 응답은 본문에 근거 목록을 담으므로, 빼지 않으면 기대한
    # 낱말이 그 목록에 우연히 있다는 이유로 **실패가 정답으로 세어진다**.
    answered = [(e, r) for e, r in labelled if r.outcome is not Outcome.GENERATION_FAILED]
    # **정답이 없는 항목의 실패도 실패다.** 옛 지표에 묶어 두면 정답을 빼는 순간
    # 실패 수가 0 이 되고, 평가표가 「전부 설명됐다」로 읽힌다.
    failed = sum(1 for _, r in incidents if r.outcome is Outcome.GENERATION_FAILED)
    uncited = sum(1 for _, r in incidents if r.outcome is Outcome.UNCITED)
    ungrounded = sum(1 for _, r in incidents
                     if (r.diagnostics or {}).get("unverified_numbers"))
    matched = sum(1 for e, r in answered if _matches(r.answer, *_expected(e, truth)))

    # 답이 없으면 어긋날 것도 없다. 넣으면 아래 층이 죽을수록 점수가 오른다.
    checked = [
        (e, r)
        for e, r in incidents
        if e.get("mustNotClaim") and r.outcome is not Outcome.GENERATION_FAILED
    ]
    clean = sum(1 for e, r in checked if not _contradicts(r.answer, e["mustNotClaim"]))

    # **절차 적중.** 실패한 답은 분모에서 뺀다 — 답이 없으면 절차를 짚을 수도 없다.
    with_procedure = [
        (e, r) for e, r in incidents
        if e.get("procedure") and r.outcome is not Outcome.GENERATION_FAILED
    ]
    doc_hits = sum(1 for e, r in with_procedure if cites_doc(r.answer, e["procedure"]["doc"]))
    section_hits = sum(
        1 for e, r in with_procedure
        if cites_section(r.answer, e["procedure"]["doc"], e["procedure"]["section"])
    )

    # **검색이 줬나와 받고 인용했나를 가른다.** 검색 목록이 기록에 없는 판(I·J)은
    # 분모에서 빠진다 — 「검색이 안 줬다」와 「기록에 없다」는 다른 것이다.
    with_docs = [
        (e, r, (r.diagnostics or {}).get("evidenceDocs"))
        for e, r in with_procedure
        if (r.diagnostics or {}).get("evidenceDocs") is not None
    ]
    retrieved = [(e, r) for e, r, docs in with_docs if e["procedure"]["doc"] in docs]
    cited_of_retrieved = sum(
        1 for e, r in retrieved if cites_doc(r.answer, e["procedure"]["doc"])
    )

    # **탐색 줄은 따로 센다.** 절 수준으로만 본다 — 문서만 맞히고 조건 절을 못 짚으면
    # 운영자가 찾는 자리를 못 준 것이고, `cites_section` 은 문서가 틀리면 어차피 거짓이다.
    with_search_procedure = [
        (e, r) for e, r in searches
        if e.get("procedure") and r.outcome is not Outcome.GENERATION_FAILED
    ]
    search_hits = sum(
        1 for e, r in with_search_procedure
        if cites_section(r.answer, e["procedure"]["doc"], e["procedure"]["section"])
    )

    cards = sum(1 for _, r in incidents if len(parse_card(r.answer)) == len(LABELS))

    # **인용만 갈래를 합쳐 센다.** 검증 안 된 인용은 어디서 나왔든 검증 안 된 것이고,
    # 갈래마다 따로 세면 한쪽의 실패가 평가표에서 사라진다.
    citations = [c for _, r in incidents + queries + searches for c in r.citations]
    verified = sum(1 for c in citations if c.get("verified"))

    admitted = sum(
        1 for e, r in queries if e.get("expectNoEvidence") and r.outcome is Outcome.NO_EVIDENCE
    )
    expecting = [e for e, _ in queries if e.get("expectNoEvidence")]

    return Score(
        primary_cause_match=_ratio(matched, len(answered)),
        contradiction_free=_ratio(clean, len(checked)),
        citation_pass=_ratio(verified, len(citations)),
        admits_no_evidence=_ratio(admitted, len(expecting)),
        counted_incidents=len(answered),
        failed_incidents=failed,
        uncited_incidents=uncited,
        journal_cited_incidents=len(journal),
        ungrounded_number_incidents=ungrounded,
        procedure_doc_cited=_ratio(doc_hits, len(with_procedure)),
        procedure_section_cited=_ratio(section_hits, len(with_procedure)),
        counted_procedures=len(with_procedure),
        procedure_doc_retrieved=_ratio(len(retrieved), len(with_docs)),
        procedure_cited_when_retrieved=_ratio(cited_of_retrieved, len(retrieved)),
        counted_retrieved=len(retrieved),
        search_procedure_cited=_ratio(search_hits, len(with_search_procedure)),
        counted_searches=len(with_search_procedure),
        counted_citations=len(citations),
        counted_queries=len(expecting),
        counted_checked=len(checked),
        cards_complete=cards,
    )


def _spoiled(entry, record):
    """이 답이 설계 일지에서 정답을 얻었을 수 있나.

    **인용했다는 것과 거기서 얻었다는 것은 다르다.** 일지는 크고 거의 모든 검색에
    딸려 오므로, 인용만으로 걸면 **일지가 흘리지 않는 사건까지 빠진다** — 실측에서
    넷 중 셋이 빠져 표본이 1 이 됐고 그중 하나는 일지에 그 말이 한 번도 없었다.

    둘 다 참일 때만 뺀다 — **일지가 그 사건의 정답을 흘리고**(골든셋의
    `journalLeaks`), **답이 일지를 인용했을 때.**
    """
    if not entry.get("journalLeaks"):
        return False
    return any((c.get("title") or "") == DESIGN_JOURNAL for c in record.citations)


def _expected(entry, truth):
    """이 항목의 정답과 **읽는 법**. `(말 목록, 선택적인가)`.

    정답표에서 온 것은 선택적(**하나만 맞으면 된다**)이고, 골든셋에 직접 적힌 것은
    접속적이다. 없으면 `(None, False)`.
    """
    row = truth.get((entry.get("bundle") or {}).get("incidentId"))
    if row and row.get("cause"):
        return row["cause"], True
    return entry.get("expectedCause"), False


def _matches(answer, expected, any_of):
    if not expected:
        return False
    if any_of:
        return any(term in (answer or "") for term in expected)
    return _says_all(answer, expected)


def _says_all(answer, expected):
    """**부분 일치를 맞다고 세지 않는다.** 기종만 좁히고 사건을 못 좁힌 답은 틀린 답이다.

    거친 셈법이다 — 낱말이 있는지만 본다. 답의 뜻을 재는 것이 아니므로 위로도
    아래로도 틀릴 수 있고, 그 사실을 평가표에 적는다.
    """
    return all(term in (answer or "") for term in expected)


def _contradicts(answer, forbidden):
    """번들과 반대로 간 말이 하나라도 있으면 어긋난 것이다."""
    return any(term in (answer or "") for term in forbidden)


def _ratio(hit, total):
    return None if total == 0 else hit / total


#: 본문의 인용 하나. `[출처: 제목, 절]` 또는 `[출처: 제목]`. 괄호 안 전체를 잡는다.
CITATION = re.compile(r"\[출처:\s*([^\]\n]+?)\s*\]")
#: 절 표기의 앞 번호. `§4.3` · `4. 절차` · `5.1 파지 실패` 가 전부 걸린다.
SECTION_NUMBER = re.compile(r"^§?\s*(\d+(?:\.\d+)*)")


def cited_refs(answer):
    """본문의 `[출처: …]` 안쪽 전부. **본문에서 읽는다.**

    운영자가 보는 것이 본문이고, 저쪽 인용 객체의 절 표기는 판마다 다르다(`§4.3` ·
    `1. 목적`). 검증 여부는 지표 3 이 따로 잰다 — 여기서 세는 것은 「어느 문서의 어느
    절을 짚었나」뿐이다.

    ⛔ **제목과 절을 여기서 가르지 않는다.** 절에도 쉼표가 온다(I 판 실측 — 「4. 시나리오
    ② — 부품 시퀀싱 (휴머노이드, `pick_place`)」·「15. 알려진 한계, §94」). 마지막
    쉼표로 가르면 제목이 절을 삼키고, 첫 쉼표로 가르면 쉼표 든 제목이 깨진다. 그래서
    **찾는 쪽이 제목을 먼저 맞추고** 절은 그 뒤에서 읽는다([_section_after]).
    """
    return [match.group(1).strip() for match in CITATION.finditer(answer or "")]


def _section_after(body, doc):
    """`body` 가 `doc` 을 인용한 것이면 그 뒤의 절 표기. 절 없이 제목만이면 `""`, 딴 문서면 `None`."""
    if body == doc:
        return ""
    if body.startswith(doc + ","):
        return body[len(doc) + 1:].strip()
    return None


def cites_doc(answer, doc):
    """그 문서를 한 번이라도 인용했나. 제목은 그대로 맞춰야 한다."""
    return any(_section_after(body, doc) is not None for body in cited_refs(answer))


def section_match(answer, doc, number):
    """그 절을 **어떻게** 짚었나 — `"정확"` · `"하위"` · `"상위"`, 아니면 `None`.

    `3.1` 을 기대하는데 `3. 코드별 상세` 를 인용했으면 상위로 맞은 것이다(조치가 그 안에
    있다). `5` 를 기대하는데 `5.1` 을 인용했으면 하위다. `3.2` 는 아니다.

    ⛔ **상위 절 인용 하나가 사건 여럿을 동시에 만족시킨다 (2026-09-20 실측).** I 판의
    절 적중 4/8 은 정확 하나와 상위 셋인데, 그 상위 셋(G7~G9)은 전부 같은 인용
    「3. 코드별 상세」 하나로 맞은 것이다. 그 셋에서 절 지표는 문서 지표보다 더 말해 주는
    것이 없다. **비율만 보면 안 보이므로 갈래를 따로 낸다** — 물음을 고친 뒤 4/8 이 8/8 이
    되어도 그것이 정확 여덟인지 상위 여덟인지는 이 값이라야 갈린다.

    `number` 를 문자열로 맞춰 둔다. 골든셋이 손으로 고쳐져 절이 수로 오면 `+` 가 터지는데,
    그 자리가 하필 한 판(20~40분)을 다 돌린 뒤의 채점이다.
    """
    number = str(number)
    best = None
    for body in cited_refs(answer):
        section = _section_after(body, doc)
        found = SECTION_NUMBER.match(section or "")
        if not found:
            continue
        cited = found.group(1)
        if cited == number:
            return "정확"
        if best is None and cited.startswith(number + "."):
            best = "하위"
        elif best is None and number.startswith(cited + "."):
            best = "상위"
    return best


def cites_section(answer, doc, number):
    """그 문서의 그 절(또는 그 절의 상위·하위)을 인용했나. 갈래는 [section_match] 가 낸다."""
    return section_match(answer, doc, number) is not None
