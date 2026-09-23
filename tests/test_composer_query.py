"""번들에서 질의를 만든다 — `BOUNDARY.md` §1, `AGENT-01` §3 원칙 3.

**새 사실을 만들지 않는다.** 번들은 각자의 자리가 이미 답한 것을 모은 파생값이고,
이 층은 그것을 문장으로 옮길 뿐이다.
"""

import json

from composer.query import ASK, compose, compose_search, LOOKUP


def _bundle(export_dir, run, incident_id):
    lines = (export_dir(run) / "incidents.jsonl").read_text(encoding="utf-8").splitlines()
    return next(json.loads(x) for x in lines if json.loads(x)["incidentId"] == incident_id)


def test_판정하지_못한_것은_사실이_되지_않는다(export_dir):
    """incident-3 은 `expectedHold` 도 `effectMismatch` 도 널이다 — 기대를 세울
    근거가 없어 어긋남을 **판정하지 않은** 것이다. 그것을 「어긋남 없음」으로
    옮기면 모르는 것이 성공으로 접힌다."""
    bundle = _bundle(export_dir, "run-1", "incident-3")

    facts = compose(bundle).facts

    assert "effectMismatch" not in facts
    assert "expectedHold" not in facts


def _search(export_dir, run, search_id):
    lines = (export_dir(run) / "remedy-searches.jsonl").read_text(encoding="utf-8").splitlines()
    return next(json.loads(x) for x in lines if json.loads(x)["searchId"] == search_id)


def test_탐색이_없으면_대안을_말하지_않는다(export_dir):
    """사건 대부분은 짝이 되는 탐색이 없다 — 접수 관문에서 거절된 것만 탐색이 돌고,
    그것은 실행을 안 만들어 사건이 되지 않는다. 짝을 못 찾은 것을 「대안 없음」으로
    적으면 **돌지도 않은 탐색을 「찾아봤지만 없다」로 지어내게 된다.**"""
    bundle = _bundle(export_dir, "run-1", "incident-2")

    facts = compose(bundle, search=None).facts

    assert "remedyOutcome" not in facts


def test_탐색이_있으면_그_갈래를_싣는다(export_dir):
    bundle = _bundle(export_dir, "run-1", "incident-1")
    search = _search(export_dir, "run-1", "search-1")

    facts = compose(bundle, search=search).facts

    assert facts["remedyOutcome"] == "FOUND"


def test_가려진_제안의_조치_열을_지어내지_않는다(export_dir):
    """`WITHHELD` 줄에는 `steps` 키가 아예 없다. 없다고 다른 자리에서 찾아오면
    조회 한 번으로 가림이 풀리고, 사람이 먼저 진단하게 하려던 장치가 무너진다."""
    bundle = _bundle(export_dir, "run-1", "incident-1")
    search = _search(export_dir, "run-1", "search-3")

    facts = compose(bundle, search=search).facts

    assert facts["remedyOutcome"] == "WITHHELD"
    assert "remedySteps" not in facts
    assert "remedyCause" not in facts


def test_탐색_줄만으로도_질의가_선다(export_dir):
    """**질의 종류가 둘이다**(`BOUNDARY.md` §4.1). 탐색 줄에는 근거 창도 효과
    어긋남도 없고 `outcome` 과 (있으면) `cause`·`unmet` 뿐이다. 사건을 억지로
    찾아 붙이려 하면 대부분 없고, 없는 것을 지어내게 된다."""
    search = _search(export_dir, "run-1", "search-2")

    facts = compose_search(search).facts

    assert facts["remedyOutcome"] == "NONE"
    assert facts["remedyCause"] == "NO_CAPABILITY"
    assert facts["robotId"] == "hum-03"
    assert "failureClass" not in facts


def test_가려진_탐색_줄도_질의가_선다(export_dir):
    """「가려졌다」도 설명할 값이다 — 「대안 없음」이 아니라 「사람이 먼저
    진단하라」라고 말해야 한다."""
    facts = compose_search(_search(export_dir, "run-1", "search-3")).facts

    assert facts["remedyOutcome"] == "WITHHELD"
    assert "remedySteps" not in facts


def test_물음은_이_층의_것이고_사건마다_지어내지_않는다(export_dir):
    """`BOUNDARY.md` §1 이 「후보 원인의 정렬」을 이 층의 일로 두고 *제안이지
    판정이 아니다* 라고 적는다 — **묻는 것은 헌장 안이다.** 금지된 것은 사실을
    보태는 쪽이다.

    다만 물음은 **고정이다.** 사건마다 다르게 지으면 그 문장을 고르는 것이
    곧 사건의 성격을 단정하는 것이 되고, 그 판단에는 근거가 없다.
    """
    bundle = _bundle(export_dir, "run-1", "incident-1")

    text = compose(bundle).text

    assert ASK.strip(), "물음이 비어 있으면 모델은 사실 나열을 용어 해설로 받는다"
    assert text.startswith(ASK)
    assert "PAYLOAD_LOST" in text
    assert len(text) > len(ASK), "사실이 함께 실려야 한다"


def test_물음이_원인을_먼저_말하지_않는다():
    """물음 자체가 답을 담으면 그게 판정이다."""
    lowered = ASK.lower()

    assert ASK.strip()
    assert "payload" not in lowered
    assert "grasp" not in lowered
    assert "때문" not in ASK


def test_기체를_싣는다_역추론할_이유를_없앤다(export_dir):
    """**이 층이 기종을 되짚던 이유가 읽을 것이 없어서였다.** 이제 있다."""
    facts = compose(_bundle(export_dir, "run-1", "incident-2")).facts

    assert facts["robotId"] == "hum-04"


def test_판정이_얼마나_센가를_싣는다(export_dir):
    """등급은 **순서가 곧 세기다**(`AGENT-01` §2). 요구 등급과 도달 등급의 비교가
    「이 결론을 얼마나 믿어야 하나」이고, 없으면 그 문장을 못 쓴다."""
    facts = compose(_bundle(export_dir, "run-1", "incident-1")).facts

    assert facts["requiredEvidence"] == "E0"
    assert facts["reachedEvidence"] == "E0"
    assert facts["verification"] == "NOT_REQUESTED"


def test_결함_원문을_싣는다(export_dir):
    """**「왜 그 분류가 됐나」를 설명할 유일한 재료다.** 벤더 이름공간(`X_`)이면
    매핑표를 인용할 수 있고, 없으면 분류를 되풀이하는 것 말고 할 것이 없다."""
    facts = compose(_bundle(export_dir, "run-1", "incident-2")).facts

    assert facts["fault"]["vendorDetail"] == "X_FIXTURE_GRIPPER_SLIP"


def test_걸음_위치와_책임_소재를_싣는다(export_dir):
    """`step` 이 「몇 걸음 중 어디서」이고 `route` 가 **다음에 누구에게 묻는가**다 —
    `ROBOT` 은 기체와 어댑터의 일, `FLEET` 은 플릿의 일이다."""
    facts = compose(_bundle(export_dir, "run-1", "incident-5")).facts

    assert facts["route"] == "FLEET"
    assert facts["step"]["at"] == 1


def test_못_물어본_것을_아니오로_접지_않는다(export_dir):
    """`progressObservable` 은 **3값**이고 널이 「아직 갱신을 못 봤다」다.
    거짓으로 접으면 «못 물어봤다» 가 «못 잰다» 가 되고, 그게 이 층이 막으려는
    바로 그 접힘이다(`AGENT-01` §3 원칙 2)."""
    facts = compose(_bundle(export_dir, "run-1", "incident-5")).facts
    text = compose(_bundle(export_dir, "run-1", "incident-5")).text

    assert facts["observation"]["progressObservable"] is None
    assert "progressObservable" in text
    assert "progressObservable=false" not in text.replace(" ", "")
    assert "progressObservable:false" not in text.replace(" ", "")


def test_겹친_구조를_뭉개지_않는다(export_dir):
    """**충실함이 보기 좋음보다 앞선다.**

    `intent` 의 설비가 셋인데 쉼표로 이어 붙이면 경계가 사라지고, 어느 것이 출발이고
    어느 것이 도착인지 읽을 수 없다. 그 값이 자재 계열 진단의 핵심인데 읽는 쪽이
    잘못 가르면 **그럴듯하고 틀린 설명**이 나온다.

    그래서 겹친 값은 되읽을 수 있는 모양으로 적는다.
    """
    import json as _json

    text = compose(_bundle(export_dir, "run-1", "incident-4")).text
    rendered = dict(_pairs(text))

    intent = _json.loads(rendered["intent"])

    assert len(intent["equipment"]) == 3
    assert {e["equipmentUse"] for e in intent["equipment"]} == {"source", "destination"}


def _pairs(text):
    """`키=값` 을 되읽는다. 값에 공백이 없다는 가정이다."""
    for token in text.split()[1:]:
        if "=" in token:
            key, _, value = token.partition("=")
            yield key, value


def test_물음이_이미_보이는_것을_되풀이하지_말라고_한다():
    """**운영자 화면에는 번들이 이미 있다**(`BOUNDARY.md` §3.3 — `t0+δ` 에 사건이
    화면에 나타나고 설명은 나중에 채워지는 칸이다). 답이 사실을 다시 나열하면
    화면에 같은 것이 두 번 실리고, 출력 생성이 비용이므로 **그 중복이 곧 지연**이다.
    """
    from composer.query import SCREEN_NOTE

    assert SCREEN_NOTE.strip()
    assert SCREEN_NOTE in ASK


def test_물음이_확실성_구별을_요구한다():
    """**이것은 줄이지 않는다.** 「설계와 직접 일치」와 「인과는 미확정」을 가르는
    것이 이 층의 산출물이고, 그것까지 잘라내면 빨라진 대신 쓸모가 없어진다."""
    from composer.query import CERTAINTY_NOTE

    assert CERTAINTY_NOTE.strip()
    assert CERTAINTY_NOTE in ASK


def test_물음이_절차와_갈림과_금지를_묻는다():
    """**「무엇이 일어났나」에서 끝나던 답을 「무엇을 하나」까지 가게 한다.**

    2026-09-20 실측 — 위치 상실 사건의 답이 SOP-05 를 안 인용하고 다른 SOP 넷을
    「해당 없음」으로 인용하는 데 2,923자를 썼다. 물음이 원인 후보만 물었기 때문이다.
    절차·갈라 줄 관측·하지 말 것은 전부 **근거가 말하는 것을 옮기라**는 요구이고
    판정이 아니다.
    """
    from composer.query import PROCEDURE_NOTE

    assert PROCEDURE_NOTE in ASK
    assert "절차" in PROCEDURE_NOTE
    assert "관측" in PROCEDURE_NOTE
    assert "하지 말라" in PROCEDURE_NOTE


def test_물음이_문서_이름을_부르지_않는다():
    """제목을 넣으면 그 픽스처에 맞추는 것이고, 절차 적중 지표가 그것을 센다.
    `LOOKUP` 이 문서 제목을 안 쓰는 이유와 같다."""
    assert "SOP" not in ASK
    assert "정지 코드 표면" not in ASK


def test_불투명한_정지_코드는_찾으라고_세운다():
    """**번들이 코드를 들고 뜻을 안 들면, 뜻은 문서에 있다.**

    2026-09-19 실측 — `failureClass=UNCLASSIFIED` 에 `vendorDetail=X_FIXTURE_E4412`
    인 건에서 그 코드를 설명하는 문서가 **상위 20 에도 안 들었다.** 코드만 단독으로
    치면 bm25 1위인데, 번들 1,600자에 섞으면 묻힌다. 검색이 「이 코드를 설명하는
    문서」 대신 「picasso 에 관한 문서」를 집어 온다.

    코드를 한 번 더 반복하는 것으로는 안 살아났다. 살린 것은 **문서의 산문과 맞는
    의도어**였다(「벤더」·「정지 코드」·「뜻」) — 4위로 올라왔다.

    ⚠ **문장은 고정이다.** 사건마다 물음을 지어내면 그 문장을 고르는 것이 곧
    판정이 된다([Query.text] 의 계약). 여기서 번들이 정하는 것은 **걸리는지 여부와
    코드 값**뿐이고, 무엇을 찾으라는 말은 안 바뀐다. **원인을 말하지 않는다 —
    필요한 조회의 종류를 말한다.**
    """
    bundle = {
        "failureClass": "UNCLASSIFIED",
        "fault": {"failureClass": "UNCLASSIFIED", "vendorDetail": "X_FIXTURE_E4412"},
    }

    text = compose(bundle).text

    assert text.startswith(LOOKUP.format(code="X_FIXTURE_E4412"))
    assert "X_FIXTURE_E4412" in text


def test_분류가_붙었으면_찾으라고_안_한다():
    """**매핑된 코드는 이름이 뜻을 말한다.** 찾으라고 세우면 이미 있는 답을
    문서에서 다시 찾게 만들고, 검색 예산을 엉뚱한 데 쓴다."""
    bundle = {
        "failureClass": "GRASP_FAILED",
        "fault": {"failureClass": "GRASP_FAILED", "vendorDetail": "X_FIXTURE_GRIPPER_SLIP"},
    }

    assert not compose(bundle).text.startswith("벤더")


def test_코드가_없으면_찾으라고_안_한다():
    """`UNCLASSIFIED` 인데 벤더가 코드를 안 준 건도 있다. 없는 것을 찾으라고 하면
    **없는 문서를 뒤지게 하고**, 그 결과를 「근거 없음」으로 읽게 된다."""
    bundle = {"failureClass": "UNCLASSIFIED", "fault": {"vendorDetail": ""}}

    assert not compose(bundle).text.startswith("벤더")


def test_재발_횟수는_주어질_때만_싣는다(export_dir):
    """**이 층이 보태는 유일한 사실이다.** 안 주어지면 키가 없다 — 0 으로 지어내지
    않는다. 주어지면 0 도 싣는다: 0 은 「이 층이 본 것 중 없다」이고 그것도 사실이다."""
    bundle = _bundle(export_dir, "run-1", "incident-1")

    assert "recurrenceSeen" not in compose(bundle).facts
    text = compose(bundle, recurrence={"sameRobotSameClass": 0, "sameUnitSameClass": 0}).text
    assert 'recurrenceSeen={"sameRobotSameClass":0,"sameUnitSameClass":0}' in text


def test_사람의_걸음은_있을_때만_싣고_실_시계는_안_싣는다(export_dir):
    """판 5(2026-09-23)의 `resolution` — 사람이 그 단위에 낸 판단이다. 있으면 결정과 가상 시각을
    싣는다. 실 시계는 사건의 `wallClockAt` 과 같은 이유로 안 싣는다 — 구동마다 다르고 모델이
    오늘과 섞는다. null 은 「사람이 안 왔다」이고 키 부재는 「이 판이 그 칸을 안 낸다」인데 둘 다
    말할 수 있는 사실이 아니라 안 싣는다 — 「사람 없음」을 지어내지 않는다."""
    rework = _bundle(export_dir, "run-4", "incident-1")

    query = compose(rework)

    assert query.facts["resolution"] == {"decision": "REWORK", "at": "2026-09-06T00:00:04Z"}
    assert 'resolution={"decision":"REWORK","at":"2026-09-06T00:00:04Z"}' in query.text
    assert "resolution" not in compose(_bundle(export_dir, "run-4", "incident-3")).facts
    without = dict(rework)
    del without["resolution"]
    assert "resolution" not in compose(without).facts
    hollow = dict(rework, resolution={"wallClockAt": "2026-09-22T16:47:45.606355100Z"})
    assert "resolution" not in compose(hollow).facts


def test_물음이_카드_다섯_줄을_먼저_요구한다():
    """답이 길고 청중이 개발자였다(2026-09-20 실측 — 아홉 답 중앙값 2,637자, 본문 인용
    72건 중 21건이 picasso 설계 일지). 운영자가 먼저 볼 다섯 줄을 표지로 세운다. 표지마다
    인용 하나를 요구하므로 근거 없는 줄은 「근거 없음」이 된다 — 판정이 아니다."""
    from composer.query import CARD_NOTE
    from recorder.card import LABELS

    assert CARD_NOTE in ASK
    assert all(label in CARD_NOTE for label in LABELS)


def test_물음이_제안된_조치의_전제를_묻는다():
    """회복은 picasso 가 계산했고 이 층은 설명한다. 「맞는가」를 묻지 않는다 — 전제를
    사실과 **나란히** 적으라고만 한다. 판정은 읽는 사람이 한다."""
    from composer.query import REMEDY_NOTE

    assert REMEDY_NOTE in ASK
    assert "전제" in REMEDY_NOTE
    assert "맞는지" not in REMEDY_NOTE


def test_출발_결품의_전제가_질의에_실린다(export_dir):
    """⛔ **회복이 인계에 닿아도 질의에 안 실리면 없는 것과 같다 (2026-09-20 실측).**
    picasso 가 점유 축으로 계산한 대안 자리를 대장에 실어 보냈는데(적재 규약 판 4),
    이 층이 `outcome` 만 옮기고 전제를 통째로 버리고 있었다.

    전제는 넷이다 — 무엇이 없고(`material`), 어디가 비었고(`source`), 무엇을 관측했고
    (`observed`), 대안이 어디인가(`alternatives`). **판정하지 않는다** — 대안이 옳은지는
    말하지 않고 사실로 실어 읽는 사람에게 넘긴다.
    """
    facts = compose_search(_search(export_dir, "run-1", "search-4")).facts

    assert facts["remedyOutcome"] == "SOURCE_MISSING"
    assert facts["remedyMaterial"] == "ENGINE-COVER-B"
    assert facts["remedySource"] == "SEQ-IN-03.BIN-A"
    assert facts["remedyAlternatives"] == ["SEQ-IN-03.BIN-B"]
    # **널은 싣지 않는다.** 관측이 널인 것은 「못 봤다」이지 「없었다」가 아니다.
    assert "remedyObserved" not in facts
    # 승인 대상이 아니라는 것은 키 부재가 말한다(picasso 가 표면에서 집행한다).
    assert "remedySteps" not in facts


def test_능력_없음의_못_채운_선행조건이_질의에_실린다(export_dir):
    """`NONE` 이 왜 없는지는 `cause` 하나로는 안 보인다. 무엇이 요구됐고 무엇이
    관측됐는지가 `unmet` 에 있고, 그것이 운영자가 손댈 자리를 가리킨다."""
    facts = compose_search(_search(export_dir, "run-1", "search-2")).facts

    assert facts["remedyCause"] == "NO_CAPABILITY"
    assert facts["remedyUnmet"][0]["required"] == "HOLD_KIND_EMPTY"
    assert facts["remedyUnmet"][0]["observed"] == "HOLD_KIND_HOLDING"
