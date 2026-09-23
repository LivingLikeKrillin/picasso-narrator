"""골든셋 자체의 규율 — `AGENT-04` §4."""

import collections
import json
import pathlib

from eval.run import fixture_history, load, load_truth, query_for

GOLDEN = pathlib.Path(__file__).parent.parent / "eval" / "goldenset.json"
#: **정답은 골든셋이 아니라 여기 있다.** picasso 인계분에서 가져온 것이고, 인계 기록이
#: 「질의를 만드는 경로에 넣지 말 것」이라고 표시해 뒀다.
TRUTH = pathlib.Path(__file__).parent / "fixtures" / "picasso" / "ground-truth.jsonl"


def _causes(entry, truth):
    """이 항목의 정답 낱말들. 정답표에 없으면 빈 목록."""
    row = truth.get((entry.get("bundle") or {}).get("incidentId"))
    return (row or {}).get("cause") or []


def test_정답은_질의에_없는_말이어야_한다():
    """**메아리를 재지 않는다.** 기대하는 낱말이 질의에 이미 있으면, 답이 입력을
    되풀이하기만 해도 맞는다. 그러면 지표 1 이 진단이 아니라 복창을 센다.

    남는 정답은 **코퍼스에서 유도해야 하는 것**뿐이다.
    """
    history = fixture_history()
    truth = load_truth(TRUTH)
    offenders = []
    for entry in load(GOLDEN):
        text = query_for(entry, prior=history)
        for term in _causes(entry, truth):
            if term in text:
                offenders.append(f"{entry['id']}: {term!r} 가 질의에 이미 있다")

    assert offenders == []
    assert any(_causes(e, truth) for e in load(GOLDEN)), "정답이 하나도 안 물렸다"


def test_정답이_없는_항목은_이유가_적혀_있다():
    """지표 1 에서 뺀 이유를 안 적으면 다음 사람이 「빠뜨렸다」로 읽고 채워 넣는다."""
    truth = load_truth(TRUTH)
    for entry in load(GOLDEN):
        if entry["kind"] == "incident" and not _causes(entry, truth):
            assert entry.get("noLabelBecause"), f"{entry['id']} 에 이유가 없다"


def test_정답표의_벤더코드가_번들과_맞는다():
    """**번호가 밀리면 정답이 조용히 딴 사건에 붙는다.**

    정답표는 `incident-7` 처럼 저쪽 번호로 물린다. 시나리오가 늘어 그 번호가 다른
    사건을 가리키게 되면 정답은 여전히 붙고 **아무것도 안 깨진다** — 채점만 틀린다.
    picasso 가 그래서 `vendorCode` 를 같이 넣었다(인계 기록). 그 값을 번들의
    `fault.vendorDetail` 과 맞대 본다.
    """
    truth = load_truth(TRUTH)
    for entry in load(GOLDEN):
        row = truth.get((entry.get("bundle") or {}).get("incidentId"))
        if not row:
            continue
        assert (entry["bundle"]["fault"] or {}).get("vendorDetail") == row["vendorCode"], (
            f"{entry['id']}: 정답표의 코드와 번들의 코드가 다르다 — 번호가 밀렸다"
        )


def test_불투명한_정지_코드는_뜻을_말하지_않는다():
    """**코드가 뜻을 말하면 되읽기만 해도 맞는다.**

    `X_FIXTURE_SIMULATED_HARDWARE_FAULT` 가 그랬다 — 분류는 `UNCLASSIFIED` 인데
    원인이 옆 칸에 적혀 있었다. 지금은 `X_FIXTURE_E4412` 처럼 **문서를 봐야
    풀리는 코드**다. 그 성질이 시나리오 쪽에서 되돌아가면 여기서 걸린다.

    ⚠ **완전하지 않다.** 뜻을 말하는 새 낱말은 이 목록에 없으면 안 걸리고, picasso 도
    「재산출 시점의 코드 대조에서 잡히지 스냅샷에서는 안 잡힌다」고 적었다.
    여기서 거르는 것은 **이미 한 번 당한 모양**뿐이다.
    """
    말하는_낱말 = ("HARDWARE", "FAULT", "SLIP", "LOST", "FAILED", "BATTERY",
                   "TORQUE", "VACUUM", "INTERLOCK", "SIMULATED")
    truth = load_truth(TRUTH)
    offenders = [
        f"{code}: {w!r}"
        for row in truth.values()
        for code in [row["vendorCode"]]
        for w in 말하는_낱말
        if w in code.upper()
    ]

    assert offenders == []


def test_도메인_밖_질의가_있다():
    """지표 3 은 이것으로만 잰다(§8)."""
    queries = [e for e in load(GOLDEN) if e["kind"] == "query" and e.get("expectNoEvidence")]

    assert len(queries) >= 3


ROBOT_KINDS = ("Spot", "Digit", "G1", "Unitree", "Agility", "Boston")


def test_기종을_정답으로_쓰지_않는다():
    """**`FailureClass` 는 기종을 지우려고 있는 추상이다**(`AGENT-01` §3 원칙 8).
    그 값에서 기종을 역추론하는 것을 정답으로 박으면 셋이 한꺼번에 잘못된다.

    - 추상의 목적을 거꾸로 돌린다. 지우려고 만든 정보를 복원하는 것이 잘한 일이 된다
    - **구현 공백을 사실로 읽는다.** 「Digit 은 `ROBOT_FELL` 을 안 낸다」는 그
      어댑터가 안 매핑했다는 뜻이지 Digit 이 안 넘어진다는 뜻이 아니다.
      Spot 10종 · Digit 5종 · G1 3종은 벤더 API 노출량이지 고장 분포가 아니다
    - **조용히 썩는다.** 매핑 한 줄이 늘면 정답이 틀린 답이 되는데 아무것도 안 깨진다
    """
    truth = load_truth(TRUTH)
    offenders = [
        f"{e['id']}: {term!r}"
        for e in load(GOLDEN)
        for term in _causes(e, truth)
        if any(kind.lower() in term.lower() for kind in ROBOT_KINDS)
    ]

    assert offenders == []


def test_금칙어는_질의에_없는_말이어야_한다():
    """정답과 **반대 방향의 같은 함정**이다. 질의에 이미 있는 말을 금칙어로 두면
    답이 입력을 복창하기만 해도 위반이 되고, 어긋나지 않은 답을 어긋났다고 센다."""
    history = fixture_history()
    offenders = []
    for entry in load(GOLDEN):
        text = query_for(entry, prior=history)
        for term in entry.get("mustNotClaim") or []:
            if term in text:
                offenders.append(f"{entry['id']}: {term!r} 가 질의에 이미 있다")

    assert offenders == []


def test_사건마다_어긋남_검사가_있다():
    """자동으로 잴 수 있는 축이 이것뿐이다. 빠진 항목은 조용히 안 재진다."""
    for entry in load(GOLDEN):
        if entry["kind"] == "incident":
            assert entry.get("mustNotClaim"), f"{entry['id']} 에 금칙어가 없다"
            assert entry.get("why"), f"{entry['id']} 에 이유가 없다"


def test_사건마다_적용_절차가_있거나_없는_이유가_있다():
    """**절차 적중의 정답은 답이 아니라 코퍼스에서 온다.** SOP 마다 §2 에 「이 절차가
    다루는 실패 분류」 표가 있고, 정지 코드 문서에는 코드마다 조치 절이 있다. 그 출처를
    `why` 에 적는다 — 안 적으면 다음 사람이 답을 보고 채운다(함정 1)."""
    for entry in load(GOLDEN):
        if entry["kind"] != "incident":
            continue
        procedure = entry.get("procedure")
        if procedure:
            assert procedure.get("doc") and procedure.get("section") and procedure.get("why"), (
                f"{entry['id']}: 절차 칸이 비었다"
            )
        else:
            assert entry.get("noProcedureBecause"), f"{entry['id']}: 절차가 없는 이유가 없다"


def test_절차_문서_제목은_질의에_없다():
    """제목을 질의에 실으면 검색이 그 문서에 맞춰지고 지표가 그것을 센다.
    `composer` 가 제목을 안 쓰는 이유와 같다(`LOOKUP` 의 주석)."""
    for entry in load(GOLDEN):
        procedure = entry.get("procedure")
        if not procedure:
            continue
        text = query_for(entry)
        assert procedure["doc"] not in text, f"{entry['id']}: 절차 문서 제목이 질의에 있다"
        assert "SOP-0" not in text, f"{entry['id']}: SOP 번호가 질의에 있다"


def test_짝지어진_탐색은_같은_기체를_가리키고_실물의_순서를_지킨다():
    """실물의 짝은 두 모양이다. run-1 은 탐색이 먼저 서고 그 실행이 사건이 됐다 — 같은 주문이다.
    run-4 는 사건 뒤에 사람의 재작업이 있고 그 새 주문에서 탐색이 섰다 — 주문이 다르고 탐색이
    사건보다 뒤다(picasso, 2026-09-22). 어느 쪽이든 기체는 같고 짝은 지어낸 것이 아니라 실물
    그대로다 — 지어낸 짝은 없는 회복을 설명하게 한다.

    ⛔ **계획서가 이 시험을 못 봤다** (2026-09-22). 구현자가 빨간 것을 보고 멈춰 알렸고, 넓히는
    것이 아니라 둘째 실물 모양을 드는 것으로 고쳤다. `EMPTY` 를 금칙어에서 뺀 것과 같은 규율이다 —
    답이 아니라 실물에서 온 판단이다."""
    paired = [e for e in load(GOLDEN) if e["kind"] == "incident" and e.get("search")]
    assert [e["id"] for e in paired] == ["G1", "G10", "G11"]
    for entry in paired:
        search, bundle = entry["search"], entry["bundle"]
        assert search["robotId"] == bundle["robotId"], entry["id"]
        assert search["outcome"] in ("FOUND", "WITHHELD"), entry["id"]
        same_order = search["jobOrderId"] == bundle["jobOrderId"]
        after = search["at"] > bundle["at"]
        assert same_order or after, f'{entry["id"]}: 같은 주문도 아니고 사건 뒤도 아니다 — 지어낸 짝이다'
    assert paired[0]["search"]["outcome"] == "FOUND"
    assert paired[2]["search"]["outcome"] == "WITHHELD"


def test_사람의_걸음은_사건과_탐색_사이에_선다():
    """판 5(2026-09-23)의 `resolution` — 사람이 그 단위에 낸 판단이다. run-4 꼴의 짝은 사건 →
    사람의 재작업 → 탐색이라 그 걸음이 두 시각 사이에 서야 하고, run-1 꼴(탐색이 먼저 서고 그
    실행이 사건이 된 것)에는 사람이 없어 null 이다. 지어낸 걸음은 없는 사람을 설명하게 한다."""
    paired = {e["id"]: e for e in load(GOLDEN) if e["kind"] == "incident" and e.get("search")}

    assert paired["G1"]["bundle"]["resolution"] is None
    for id_ in ("G10", "G11"):
        bundle, search = paired[id_]["bundle"], paired[id_]["search"]
        step = bundle["resolution"]
        assert step["decision"] == "REWORK", id_
        assert bundle["at"] < step["at"] < search["at"], f"{id_}: 걸음이 사건과 탐색 사이에 없다"


def test_탐색_줄_항목은_실물_대장의_줄이다():
    """**지어낸 탐색은 없는 회복을 설명하게 한다.** 골든셋의 탐색 항목은 인계된 대장의
    줄을 그대로 옮긴 것이어야 한다."""
    ledger = []
    for run in sorted((TRUTH.parent).glob("run-*")):
        for line in (run / "remedy-searches.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                ledger.append(json.loads(line))

    entries = [e for e in load(GOLDEN) if e["kind"] == "search"]
    assert entries, "탐색 줄을 재는 항목이 하나는 있어야 한다"
    for entry in entries:
        # **어느 벌의 줄이어도 된다.** 두 벌은 재실행이라 `searchId` 가 같고 `wallClockAt`
        # 만 다르다 — 그 하나로 「지어낸 줄」을 가를 수는 없으므로 줄 전체가 대장에 있으면 된다.
        assert entry["search"] in ledger, f'{entry["id"]}: 대장에 없는 줄이다'


def test_탐색_줄의_절차도_코퍼스에서_온다():
    """사건과 같은 규율이다 — 정답은 답이 아니라 코퍼스에서 오고 출처를 `why` 에 적는다."""
    for entry in load(GOLDEN):
        if entry["kind"] != "search":
            continue
        procedure = entry.get("procedure")
        if procedure:
            assert procedure.get("doc") and procedure.get("section") and procedure.get("why")
        else:
            assert entry.get("noProcedureBecause"), f'{entry["id"]}: 절차가 없는 이유가 없다'


def test_골든셋의_크기를_센다():
    """⛔ **산문이 「6~10 건」이라 적고 있었다** (2026-09-22 정정. 실제 13, 같은 날 run-4 의 짝 둘이 들어와 15).

    세 저장소 점검이 「산문의 수가 세 곳에서 다 썩는다」로 같은 종류의 낡음을 찾았고,
    그 규율이 **「세는 시험이 없는 수는 적지 않는다」**다. 그래서 이 수를 여기서 센다 —
    **골든셋이 늘면 이 시험이 빨개지고, 그때 산문을 같이 고친다.**

    갈래별로도 센다. 총수만 세면 사건 하나가 질의 하나로 바뀌어도 안 걸린다.
    """
    entries = load(GOLDEN)
    kinds = collections.Counter(e["kind"] for e in entries)

    assert len(entries) == 15, "BOUNDARY.md §8 의 「골든셋 15 건」을 같이 고친다"
    assert kinds == {"incident": 11, "search": 1, "query": 3}
