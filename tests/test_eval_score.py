"""세 지표 산출 — `AGENT-04` §4.

**채점은 순수 함수다.** 호출과 섞으면 수치를 다시 내려면 매번 스택이 살아 있어야 하고,
그러면 평가가 인프라에 묶인다.
"""

from eval.score import score, DESIGN_JOURNAL
from recorder.outcome import Outcome
from recorder.record import Record

GIVEN = Outcome.GIVEN
NONE = Outcome.NO_EVIDENCE


def _rec(outcome, answer="", citations=()):
    return Record(key=("run", "x"), outcome=outcome, answer=answer, citations=list(citations))


def test_원인_일치는_기대한_말이_답에_다_있을_때다():
    """**부분 일치를 맞다고 세지 않는다.** 「Spot」만 맞히고 「전도」를 놓친 답은
    기종은 좁혔으나 사건을 못 좁힌 것이다."""
    entries = [
        {"id": "G1", "kind": "incident", "expectedCause": ["Spot", "전도"]},
        {"id": "G2", "kind": "incident", "expectedCause": ["Spot", "전도"]},
    ]
    records = [
        _rec(GIVEN, answer="기종은 Spot 으로 좁혀지고 순수 전도 이벤트다"),
        _rec(GIVEN, answer="기종은 Spot 으로 좁혀진다"),
    ]

    assert score(entries, records).primary_cause_match == 0.5


def test_인용_검증_통과율은_인용_단위다():
    entries = [{"id": "G1", "kind": "incident", "expectedCause": []}]
    records = [_rec(GIVEN, citations=[{"verified": True}, {"verified": False}, {"verified": True}])]

    assert score(entries, records).citation_pass == 2 / 3


def test_근거_없을_때_모른다고_답한_비율은_도메인_밖_질의로_잰다():
    """**사건으로는 못 잰다**(§8). 이 코퍼스가 이 시스템을 문서화하므로 사건에는
    언제나 근거가 있다. 재는 것은 도메인 밖 질의다."""
    entries = [
        {"id": "Q1", "kind": "query", "expectNoEvidence": True},
        {"id": "Q2", "kind": "query", "expectNoEvidence": True},
        {"id": "G1", "kind": "incident", "expectedCause": []},
    ]
    records = [_rec(NONE), _rec(GIVEN), _rec(GIVEN)]

    result = score(entries, records)

    assert result.admits_no_evidence == 0.5
    assert result.counted_queries == 2


def test_잴_것이_없으면_0_이_아니라_없음이다():
    """0 은 「해봤는데 못 했다」이고 없음은 「잴 것이 없었다」다. 접으면 평가표가
    아무도 안 읽었을 때와 완벽했을 때를 같게 보인다."""
    result = score([{"id": "G1", "kind": "incident", "expectedCause": []}], [_rec(GIVEN)])

    assert result.admits_no_evidence is None
    assert result.counted_queries == 0


def test_생성이_실패한_건은_원인_일치로_세지_않는다():
    """합성이 실패하면 Nexus 가 **근거 목록을 본문에 담은** 강등 응답을 준다.
    그 목록에 기대한 낱말이 들어 있으면 낱말 포함만 보는 채점이 **실패를 정답으로
    센다.** 답이 없는 것은 틀린 원인이 아니라 **원인이 없는 것**이다."""
    entries = [
        {"id": "G1", "kind": "incident", "expectedCause": ["PAYLOAD_LOST"]},
        {"id": "G2", "kind": "incident", "expectedCause": ["PAYLOAD_LOST"]},
    ]
    records = [
        _rec(Outcome.GENERATION_FAILED, answer="답변을 생성할 수 없습니다 … PAYLOAD_LOST …"),
        _rec(GIVEN, answer="분류가 PAYLOAD_LOST 다"),
    ]

    result = score(entries, records)

    assert result.primary_cause_match == 1.0
    assert result.counted_incidents == 1
    assert result.failed_incidents == 1


def test_설명이_하나도_안_선_경우는_비율이_없음이다():
    """전부 실패했으면 0% 가 아니라 **잴 것이 없었다**. 0 으로 적으면 「전부
    틀렸다」로 읽히고, 고칠 곳을 엉뚱한 데서 찾게 된다."""
    entries = [{"id": "G1", "kind": "incident", "expectedCause": ["X"]}]

    result = score(entries, [_rec(Outcome.GENERATION_FAILED, answer="X")])

    assert result.primary_cause_match is None
    assert result.failed_incidents == 1


def test_어긋난_주장을_했는지_센다():
    """**「맞혔나」보다 이쪽이 잴 수 있다.** 금칙어는 답이 번들과 반대로 갔을 때만
    쓰는 말이라 질의에 없고, 그래서 메아리로 통과할 수 없다."""
    entries = [
        {"id": "G1", "kind": "incident", "mustNotClaim": ["떨어뜨"]},
        {"id": "G2", "kind": "incident", "mustNotClaim": ["떨어뜨"]},
    ]
    records = [
        _rec(GIVEN, answer="쥐고 있는 상태가 유지됐다"),
        _rec(GIVEN, answer="대상을 떨어뜨린 것으로 보인다"),
    ]

    result = score(entries, records)

    assert result.contradiction_free == 0.5
    assert result.counted_checked == 2


def test_설명이_안_선_건은_어긋남_검사에서도_뺀다():
    """답이 없으면 어긋날 것도 없다. 넣으면 아래 층이 죽을수록 점수가 오른다."""
    entries = [{"id": "G1", "kind": "incident", "mustNotClaim": ["떨어뜨"]}]

    result = score(entries, [_rec(Outcome.GENERATION_FAILED, answer="")])

    assert result.contradiction_free is None
    assert result.counted_checked == 0


def test_설명이_안_선_수는_정답표와_무관하게_센다():
    """**정답이 없는 항목의 실패도 실패다.** 옛 지표에 묶어 두면 정답을 빼는 순간
    실패 수가 0 이 되고, 평가표가 「전부 설명됐다」로 읽힌다."""
    entries = [
        {"id": "G1", "kind": "incident", "mustNotClaim": ["x"]},
        {"id": "G2", "kind": "incident", "mustNotClaim": ["x"]},
        {"id": "G3", "kind": "incident", "mustNotClaim": ["x"]},
    ]
    records = [_rec(Outcome.GENERATION_FAILED), _rec(GIVEN, answer="ok"), _rec(Outcome.GENERATION_FAILED)]

    result = score(entries, records)

    assert result.failed_incidents == 2
    assert result.counted_checked == 1


def test_인용_없는_답도_수를_드러낸다():
    """**조용히 빼면 비율이 부푼다** — `failed_incidents` 를 세는 것과 같은 이유다.

    「인용 없는 답」은 실패가 아니라 분모에 남고 어긋남 검사도 받는다. 다만 인용이
    0 이라 인용 검증에는 아무것도 기여하지 않는다. 그래서 수를 따로 안 적으면
    평가표에서 **사라진다** — 설명이 선 것도 아니고 안 선 것도 아닌 채로.

    2026-09-19 실측에서 사건 하나가 2,510자짜리 답을 내고 인용이 0 이었다. 그 사실이
    어디에도 안 남으면 평가표는 「사건 셋이 설명됐다」로 읽히는데, **그중 하나는
    검증할 인용이 없는 답이다.**
    """
    entries = [
        {"id": "G1", "kind": "incident", "mustNotClaim": ["전도"]},
        {"id": "G2", "kind": "incident", "mustNotClaim": ["전도"]},
    ]
    records = [
        _rec(GIVEN, answer="근거가 붙은 설명", citations=[{"verified": True}]),
        _rec(Outcome.UNCITED, answer="근거 2 §15.89 가 이 경우를 적고 있다 …"),
    ]

    s = score(entries, records)

    assert s.uncited_incidents == 1
    # 실패가 아니다 — 답이 있으므로 어긋남 검사의 분모에 남는다.
    assert s.failed_incidents == 0
    assert s.counted_checked == 2


def test_지어낸_수가_있는_답은_수를_드러낸다():
    """**근거에 없는 숫자를 말한 답은 이 층이 막으려는 바로 그것이다.**

    지표 2(번들과 어긋나지 않은 비율)는 **손으로 적은 금칙어**만 본다. 금칙어에 없는
    거짓은 안 걸린다. Nexus 의 `unverified_numbers` 는 답의 유의미한 숫자가 LLM 에게
    보여준 것에 실재하는지를 **값-일치로** 보므로, 내가 미리 못 적은 거짓도 잡는다.

    비율로 만들지 않는다 — 오탐이 있을 수 있는 검사다(항목 셋을 요약한 「3건」처럼
    근거에 문자로 없는 수가 정당할 때가 있다). **수를 드러내 사람이 보게 한다.**
    """
    entries = [
        {"id": "G1", "kind": "incident", "mustNotClaim": []},
        {"id": "G2", "kind": "incident", "mustNotClaim": []},
        {"id": "G3", "kind": "incident", "mustNotClaim": []},
    ]
    records = [
        _rec(GIVEN, answer="근거대로"),
        _rec(GIVEN, answer="가동률이 47% 였다"),
        _rec(GIVEN, answer="근거대로"),
    ]
    object.__setattr__(records[1], "diagnostics", {"unverified_numbers": 1})
    object.__setattr__(records[0], "diagnostics", {"unverified_numbers": 0})
    object.__setattr__(records[2], "diagnostics", {"unverified_numbers": 0})

    assert score(entries, records).ungrounded_number_incidents == 1


def test_정답표의_여러_표현은_하나만_맞으면_된다():
    """**정답표가 주는 목록은 «다 있어야 할 말» 이 아니라 «같은 원인의 다른 표현» 이다.**

    picasso 의 `ground-truth.jsonl` 이 그렇게 준다 — `["관절 토크", "토크 한계", "과부하"]`
    는 한 원인의 세 표면형이고, 「관절 토크 한계 초과」라고 답하면 맞은 것이다.
    `["하나로 안 좁혀진다", "안 좁혀진다", …]` 는 둘째가 첫째의 부분문자열이기까지 하다.

    ⚠ 기존 `expectedCause`(골든셋에 직접 적던 것)는 **접속적**이었다 —
    `["Spot", "전도"]` 는 기종만 좁히고 사건을 못 좁힌 답을 틀렸다고 세려던 것이다.
    둘은 다른 종류의 목록이고, **정답표에서 온 것은 선택적으로 읽는다.**
    """
    entries = [
        {"id": "G7", "kind": "incident", "bundle": {"incidentId": "incident-7"}, "mustNotClaim": []},
        {"id": "G8", "kind": "incident", "bundle": {"incidentId": "incident-8"}, "mustNotClaim": []},
    ]
    records = [
        _rec(GIVEN, answer="관절 토크 한계를 넘어선 보호 정지로 보인다"),
        _rec(GIVEN, answer="원인을 특정할 수 없다"),
    ]
    truth = {
        "incident-7": {"cause": ["관절 토크", "토크 한계", "과부하"]},
        "incident-8": {"cause": ["진공 압력", "흡착", "진공"]},
    }

    assert score(entries, records, truth=truth).primary_cause_match == 0.5


def test_정답이_없는_사건은_분모에_안_든다():
    """**못 맞힌 것과 잴 것이 없는 것은 다르다.**

    ⛔ `_expected` 가 `(말, 선택적인가)` 튜플을 돌려주는데 그것을 `if` 로 걸렀다.
    **빈 튜플이 아니므로 언제나 참**이고, 정답 없는 사건이 전부 분모에 들어가
    지표 1 이 조용히 낮아졌다. 2026-09-19 실측에서 1/4 가 1/9 로 찍혔다.

    널이 아니라 **0 에 가까운 수로 틀리는 고장**이라 눈으로는 안 잡힌다 —
    수치가 그럴듯하게 나오기 때문이다.
    """
    entries = [
        {"id": "G7", "kind": "incident", "bundle": {"incidentId": "incident-7"}, "mustNotClaim": []},
        {"id": "G1", "kind": "incident", "bundle": {"incidentId": "incident-1"}, "mustNotClaim": []},
        {"id": "G2", "kind": "incident", "bundle": {"incidentId": "incident-2"}, "mustNotClaim": []},
    ]
    records = [_rec(GIVEN, answer="관절 토크 한계"), _rec(GIVEN, answer="뭐라고"), _rec(GIVEN, answer="뭐라고")]
    truth = {"incident-7": {"cause": ["관절 토크"]}}

    s = score(entries, records, truth=truth)

    assert s.counted_incidents == 1
    assert s.primary_cause_match == 1.0


def test_설계_일지를_근거로_든_답은_지표_1_에서_뺀다():
    """**골든셋 설계가 그 문서 안에 있다. 읽으면 답이 나온다.**

    picasso 가 `limits.md` §15.181 로 넘긴 조각이다 — 「설계 일지를 근거로 든 답의
    제외는 받는 측 채점기의 몫」. 그 일지(`superpowers/specs/2026-09-05-picasso-design.md`)
    는 삭제하지 않는 기록이라 코퍼스에 남고, 검색이 집어 온다. 실제로 내 답 하나가
    벤더 문서 대신 그 일지를 인용해 `E9001` 의 성질을 설명했다.

    **틀렸다고 세지 않고 분모에서 뺀다.** 그 답이 추론한 것인지 정답 설계를 되읽은
    것인지 **밖에서 못 가른다.** 틀렸다고 세면 없는 사실을 주장하는 것이고, 그냥
    두면 거짓 통과가 섞인다. **못 재는 것은 못 재는 것이다.**

    ⚠ **과잉 배제다.** 일지를 **다른 주장의 근거로** 들고 원인은 벤더 문서에서 가져온
    답도 같이 빠진다. 낮게 나오는 쪽(표본이 주는 쪽)으로 틀리므로 그쪽을 택한다.

    그리고 **수를 드러낸다** — 조용히 빼면 비율이 부푼다.
    """
    entries = [
        {"id": "G7", "kind": "incident", "bundle": {"incidentId": "incident-7"}, "mustNotClaim": []},
        {"id": "G4", "kind": "incident", "bundle": {"incidentId": "incident-4"},
         "mustNotClaim": [], "journalLeaks": True},
    ]
    records = [
        _rec(GIVEN, answer="관절 토크 한계",
             citations=[{"title": "합성 기체(fixture)의 정지 코드 표면", "verified": True}]),
        _rec(GIVEN, answer="안 좁혀진다",
             citations=[{"title": DESIGN_JOURNAL, "verified": True}]),
    ]
    truth = {"incident-7": {"cause": ["관절 토크"]}, "incident-4": {"cause": ["안 좁혀"]}}

    s = score(entries, records, truth=truth)

    # 둘 다 정답 낱말을 담았지만 센 것은 하나다.
    assert s.counted_incidents == 1
    assert s.primary_cause_match == 1.0
    assert s.journal_cited_incidents == 1


def test_일지가_그_답을_안_흘리면_인용해도_센다():
    """**인용했다는 것과 거기서 답을 얻었다는 것은 다르다.**

    설계 일지는 크고 거의 모든 검색에 딸려 온다. 「인용했으면 뺀다」로 걸면
    **일지가 흘리지 않는 사건까지 빠진다** — 2026-09-19 실측에서 넷 중 셋이
    빠져 표본이 1 이 됐고, 그중 하나(`E2075`)는 일지에 「진공 압력」이 **한 번도
    안 나온다.** 거기서 얻을 수 있는 답이 아니었다.

    그래서 **그 사건의 정답 표현이 일지에 실재할 때만** 뺀다. 골든셋이
    `journalLeaks` 로 들고, 근거(낱말별 출현 수)를 `journalLeaksWhy` 에 적는다.

    ⚠ **코퍼스가 바뀌면 그 값이 낡는다.** 저쪽이 일지를 고치면 다시 세야 하고,
    이 시험은 그것을 못 잡는다 — 세는 절차는 `eval/README.md` 에 적어 둔다.
    """
    entries = [
        {"id": "G8", "kind": "incident", "bundle": {"incidentId": "incident-8"},
         "mustNotClaim": [], "journalLeaks": False},
        {"id": "G7", "kind": "incident", "bundle": {"incidentId": "incident-7"},
         "mustNotClaim": [], "journalLeaks": True},
    ]
    cite = [{"title": DESIGN_JOURNAL, "verified": True}]
    records = [_rec(GIVEN, answer="진공 압력 저하", citations=cite),
               _rec(GIVEN, answer="관절 토크 한계", citations=cite)]
    truth = {"incident-8": {"cause": ["진공 압력"]}, "incident-7": {"cause": ["관절 토크"]}}

    s = score(entries, records, truth=truth)

    assert s.counted_incidents == 1          # G8 만 센다
    assert s.journal_cited_incidents == 1    # G7 만 뺀다
    assert s.primary_cause_match == 1.0


STOP_CODES = "합성 기체(fixture)의 정지 코드 표면 — Synthetic Stop-Code Surface"


def _proc(doc, section):
    return {"doc": doc, "section": section, "why": "…"}


def test_절차_적중은_그_분류의_절차_문서를_인용했을_때다():
    """**「무엇을 하나」를 안 담은 답을 잡는다.** 위치 상실 사건의 답이 SOP-05 를 안
    인용하고 다른 SOP 넷을 「해당 없음」으로 인용했는데 네 지표가 만점이었다
    (2026-09-20 실측)."""
    entries = [
        {"id": "G3", "kind": "incident", "procedure": _proc("SOP-05 자기 위치 상실 복구", "4")},
        {"id": "G6", "kind": "incident", "procedure": _proc("SOP-01 파지 실패와 잔여 파지 처리", "5")},
    ]
    records = [
        _rec(GIVEN, answer="정지시킨다 [출처: SOP-05 자기 위치 상실 복구, 4. 절차]"),
        _rec(GIVEN, answer="결품은 아니다 [출처: SOP-03 자재 결품과 대체 슬롯 운용, 3. 선행 조건]"),
    ]

    result = score(entries, records)

    assert result.procedure_doc_cited == 0.5
    assert result.counted_procedures == 2


def test_목적_절만_인용한_답은_절_수준에서_떨어진다():
    """문서는 맞췄는데 절차 절이 아니라 목적 절이다. 운영자가 할 일은 §5 에 있다."""
    entries = [{"id": "G1", "kind": "incident",
                "procedure": _proc("SOP-01 파지 실패와 잔여 파지 처리", "5")}]
    records = [_rec(GIVEN, answer="[출처: SOP-01 파지 실패와 잔여 파지 처리, 1. 목적]")]

    result = score(entries, records)

    assert result.procedure_doc_cited == 1.0
    assert result.procedure_section_cited == 0.0


def test_상위_절이나_하위_절_인용도_절_수준_적중이다():
    """§3.1 의 조치를 §3 전체로 인용해도, §5 를 §5.1 로 인용해도 절차를 짚은 것이다.
    저쪽 인용 표기는 `§3.1` 과 `3. 코드별 상세` 가 섞여 온다."""
    entries = [
        {"id": "G7", "kind": "incident", "procedure": _proc(STOP_CODES, "3.1")},
        {"id": "G2", "kind": "incident", "procedure": _proc("SOP-01 파지 실패와 잔여 파지 처리", "5")},
        {"id": "G8", "kind": "incident", "procedure": _proc(STOP_CODES, "3.2")},
    ]
    records = [
        _rec(GIVEN, answer=f"[출처: {STOP_CODES}, 3. 코드별 상세]"),
        _rec(GIVEN, answer="[출처: SOP-01 파지 실패와 잔여 파지 처리, 5.1 파지 실패 (`GRASP_FAILED`)]"),
        _rec(GIVEN, answer=f"[출처: {STOP_CODES}, §3.1]"),
    ]

    result = score(entries, records)

    assert result.procedure_section_cited == 2 / 3


def test_절차가_없는_사건과_실패한_답은_절차_분모에_안_든다():
    """0 은 「해봤는데 못 했다」이고 없음은 「잴 것이 없었다」다."""
    entries = [
        {"id": "G5", "kind": "incident", "noProcedureBecause": "플릿 거절이다"},
        {"id": "G3", "kind": "incident", "procedure": _proc("SOP-05 자기 위치 상실 복구", "4")},
    ]
    records = [_rec(GIVEN, answer="…"), _rec(Outcome.GENERATION_FAILED)]

    result = score(entries, records)

    assert result.procedure_doc_cited is None
    assert result.counted_procedures == 0


def test_본문의_인용은_제목으로_맞추고_절은_제목_뒤에서_읽는다():
    """운영자가 보는 것은 본문이다. 저쪽 인용 객체의 절 표기는 판마다 달라
    (`§4.3` · `1. 목적`) 본문의 `[출처: 제목, 절]` 을 읽는다.

    ⛔ **절에도 쉼표가 온다**(I 판 실측 — 「4. 시나리오 ② — 부품 시퀀싱 (휴머노이드,
    `pick_place`)」). 마지막 쉼표로 가르면 제목이 절을 삼킨다. 그래서 **제목을 먼저
    맞추고** 절은 그 뒤에서 읽는다. 절 없이 제목만 인용해도 문서 적중이다."""
    from eval.score import cites_doc, cites_section

    scenario = "운영 시나리오 명세서 — 3대 작업 흐름 및 인터페이스 경계 정의"
    answer = (
        f"가 [출처: {scenario}, 4. 시나리오 ② — 부품 시퀀싱 (휴머노이드, `pick_place`)] "
        "나 [출처: picasso — 이기종 로봇 표준 I/F 계약과 운영 변경 체계]"
    )

    assert cites_doc(answer, scenario)
    assert cites_section(answer, scenario, "4")
    assert not cites_section(answer, scenario, "3")
    assert cites_doc(answer, "picasso — 이기종 로봇 표준 I/F 계약과 운영 변경 체계")
    assert not cites_doc(answer, "SOP-01 파지 실패와 잔여 파지 처리")


def test_카드가_다섯_줄_다_있는_답을_센다():
    entries = [{"id": "G1", "kind": "incident"}, {"id": "G2", "kind": "incident"}]
    records = [
        _rec(GIVEN, answer="절차: a\n먼저: b\n금지: c\n갈림: d\n근거 세기: e\n본문"),
        _rec(GIVEN, answer="절차: a\n먼저: b\n본문"),
    ]

    assert score(entries, records).cards_complete == 1


def _seen(outcome, answer="", docs=None):
    """검색이 돌려준 문서 목록을 든 기록. `docs=None` 이면 옛 기록이다."""
    return Record(key=("run", "x"), outcome=outcome, answer=answer,
                  diagnostics={} if docs is None else {"evidenceDocs": list(docs)})


def test_검색이_준_것과_답이_인용한_것을_가른다():
    """⛔ **절차 적중 4/8 이 설명층의 점수로 읽혔다**(2026-09-20 K 판). 실제로는 넷이
    검색에서 그 문서를 못 받았고, 받은 넷은 넷 다 인용했다. 남의 층의 실패를 이 층의
    점수로 적지 않는다 — 두 수를 가른다."""
    proc = {"doc": "SOP-01", "section": "5", "why": "…"}
    entries = [{"id": i, "kind": "incident", "procedure": proc} for i in ("G1", "G2", "G3")]
    records = [
        _seen(GIVEN, "[출처: SOP-01, 5. 절차]", ["SOP-01", "SOP-02"]),   # 받고 인용
        _seen(GIVEN, "딴 말 [출처: SOP-02, 1. 목적]", ["SOP-01"]),        # 받고도 안 함
        _seen(GIVEN, "딴 말", ["SOP-02", "SOP-03"]),                     # 아예 못 받음
    ]

    result = score(entries, records)

    assert result.procedure_doc_cited == 1 / 3, "전체 적중은 그대로 센다"
    assert result.procedure_doc_retrieved == 2 / 3
    assert result.procedure_cited_when_retrieved == 0.5
    assert result.counted_retrieved == 2


def test_검색_목록이_없는_옛_기록은_영이_아니라_없음이다():
    """0 은 「검색이 안 줬다」이고 없음은 「검색이 뭘 줬는지 기록에 없다」다. I·J 판이
    그렇다 — `evidenceDocs` 는 2026-09-20 에 생겼다. 접으면 옛 판이 검색을 한 번도
    못 받은 것처럼 읽힌다."""
    proc = {"doc": "SOP-01", "section": "5", "why": "…"}
    entries = [{"id": "G1", "kind": "incident", "procedure": proc}]
    records = [_seen(GIVEN, "[출처: SOP-01, 5. 절차]")]

    result = score(entries, records)

    assert result.procedure_doc_cited == 1.0
    assert result.procedure_doc_retrieved is None
    assert result.procedure_cited_when_retrieved is None
    assert result.counted_retrieved == 0


def test_탐색_줄은_사건과_분모를_합치지_않는다():
    """⛔ **합치면 판 사이 비교가 깨진다.** 사건 아홉으로 재 온 절차 적중에 탐색 줄을
    섞으면 앞 판들과 같은 수가 아니게 된다. 그리고 둘은 답해야 할 것이 다르다 — 사건은
    「무엇을 하나」이고 탐색 줄은 「그 조치를 쓰려면 무엇이 참이어야 하나」다.

    인용 검증만 합쳐 센다. **검증 안 된 인용은 어느 갈래에서 나왔든 검증 안 된 것**이고,
    갈래마다 따로 세면 한쪽의 실패가 평가표에서 사라진다.
    """
    proc = {"doc": "SOP-03 자재 결품과 대체 슬롯 운용", "section": "4", "why": "…"}
    entries = [
        {"id": "G1", "kind": "incident",
         "procedure": {"doc": "SOP-01 파지 실패와 잔여 파지 처리", "section": "5", "why": "…"}},
        {"id": "S1", "kind": "search", "procedure": proc},
    ]
    records = [
        Record(key=("r", "1"), outcome=GIVEN,
               answer="[출처: SOP-01 파지 실패와 잔여 파지 처리, 5. 절차]",
               citations=[{"verified": True}]),
        Record(key=("r", "2"), outcome=GIVEN,
               answer="[출처: SOP-03 자재 결품과 대체 슬롯 운용, 4. 대체 슬롯은 기본이 아니다]",
               citations=[{"verified": False}]),
    ]

    result = score(entries, records)

    assert result.procedure_doc_cited == 1.0, "사건 분모는 사건 하나 그대로다"
    assert result.counted_procedures == 1
    assert result.search_procedure_cited == 1.0
    assert result.counted_searches == 1
    assert result.citation_pass == 0.5, "인용은 갈래를 합쳐 센다"


def test_탐색_줄이_절차를_안_짚으면_떨어진다():
    """대체 슬롯을 쓸 조건은 SOP-03 §4 에만 있다. 결과만 되읽고 조건을 안 짚으면
    운영자는 그 자리를 못 찾는다."""
    entries = [{"id": "S1", "kind": "search",
                "procedure": {"doc": "SOP-03 자재 결품과 대체 슬롯 운용", "section": "4", "why": "…"}}]
    records = [_rec(GIVEN, answer="출발 자리에 자재가 없습니다. 대안은 SEQ-IN-03.BIN-B 입니다.")]

    result = score(entries, records)

    assert result.search_procedure_cited == 0.0
    assert result.counted_searches == 1
