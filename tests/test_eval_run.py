"""골든셋 항목을 질의로 — `AGENT-04` §4."""

from composer.query import ASK
from eval.run import query_for, load_truth, run_env
from explainer.transport import TIMEOUT


def test_사건은_번들에서_질의를_만든다():
    """**파이프라인과 같은 길을 탄다.** 평가용으로 다른 질의를 만들면 재는 것이
    실제로 도는 것과 달라진다."""
    entry = {"kind": "incident", "bundle": {"failureClass": "PAYLOAD_LOST"}}

    text = query_for(entry)

    assert text.startswith(ASK)
    assert "PAYLOAD_LOST" in text


def test_도메인_밖_질의는_그대로_간다():
    """**물음을 붙이지 않는다.** 지표 3 은 운영자 질의 경로를 재는 것이고,
    거기에 사건용 물음을 씌우면 재는 대상이 달라진다."""
    entry = {"kind": "query", "query": "오늘 부산 날씨 알려줘"}

    assert query_for(entry) == "오늘 부산 날씨 알려줘"


def test_평가는_실제로_도는_길을_탄다():
    """**하네스가 자기 경로를 따로 가지면 재는 것이 도는 것과 달라진다.**

    골든셋이 재시도를 안 하고 사유를 안 남기면, 평가표의 「설명 안 섬」이 실제
    운영의 실패율과 다른 수가 된다. 원천이 둘이면 갈릴 때 어느 쪽이 참인지 모른다.
    """
    from eval.run import collect

    calls = []

    def flaky(query):
        calls.append(1)
        return 200, {
            "success": True,
            "data": {"llm_failed": True, "llm_failure_reason": "timeout", "citations": []},
        }

    records = collect([{"kind": "query", "id": "Q1", "query": "x"}], flaky, limit=3)

    assert len(calls) == 3, "일시적 실패를 다시 해봐야 한다"
    assert records[0].reason == "timeout"
    assert (records[0].attempts, records[0].limit) == (3, 3)


def test_정답은_골든셋이_아니라_별도_파일에서_읽는다(tmp_path):
    """**정답이 질의 만드는 파일 옆에 살면 언젠가 섞인다.**

    picasso 가 정답을 `ground-truth.jsonl` 로 따로 낸다. 그 파일은 인계 자리에서
    「질의를 만드는 경로에 넣지 말 것」이라고 표시돼 있고, 여기서만 읽는다.

    `incidentId` 로 물린다 — 골든셋 항목의 id(`G7`)가 아니라 **번들의 사건 id** 다.
    """
    p = tmp_path / "ground-truth.jsonl"
    p.write_text(
        '{"incidentId":"incident-7","vendorCode":"X_FIXTURE_E4412",'
        '"narrowable":true,"cause":["관절 토크"],"why":"…","distractors":["배터리"]}\n',
        encoding="utf-8",
    )

    truth = load_truth(p)

    assert truth["incident-7"]["cause"] == ["관절 토크"]
    assert truth["incident-7"]["vendorCode"] == "X_FIXTURE_E4412"


def test_실행_기록에_환경이_찍힌다():
    """**「기록만 있으면 스택 없이 다시 센다」는 그 기록이 어느 스택 것인지 알 때만 참이다.**

    ⛔ 안 찍고 있었다(2026-09-19). 같은 골든셋을 여덟 판 돌렸는데 `top_k` 가 8 인 판과
    20 인 판이 **줄만 보고는 안 갈린다.** 그 둘은 지표 1 이 1/4 과 3/4 으로 갈린 차이다.
    모델도 두 종을 돌렸고, 벽도 120·180·300 을 오갔다.

    **결과를 좌우한 값이 결과 옆에 없으면 그 결과는 다시 못 읽는다.**

    ⚠ **내가 아는 것만 찍는다.** 브리지 벽은 저쪽 것이고 응답에 안 온다 — 모르는 것을
    찍으면 그때부터 기록이 거짓말을 한다. `model` 은 저쪽이 응답에 실어 보내는 값이라
    **관측이지 내 선언이 아니다.** 코퍼스 판은 2026-09-22 에 신고 규약이 생겨 들어왔다
    (아래 시험).
    """
    env = run_env(top_k=20, model="claude-sonnet-5", goldenset="eval/goldenset.json")

    assert env["top_k"] == 20
    assert env["model"] == "claude-sonnet-5"
    assert env["clientTimeout"] == TIMEOUT       # 내 벽. 저쪽 벽과 다르다
    assert env["at"]                              # 언제 돌았나


def test_평가_질의에도_재발_횟수가_실린다():
    """**평가는 실제로 도는 길을 탄다.** 배선은 재발을 싣는데 평가가 안 실으면 재는 것이
    도는 것과 달라진다. 이력을 안 주면 안 싣는다 — 옛 시험이 그대로 서는 이유다."""
    from eval.run import fixture_history

    entry = {"kind": "incident", "bundle": {"robotId": "hum-02", "failureClass": "PAYLOAD_LOST",
                                           "digest": "z", "at": "2026-09-07T00:00:00Z"}}

    assert "recurrenceSeen" not in query_for(entry)
    assert 'recurrenceSeen={"sameRobotSameClass":1,"sameUnitSameClass":0}' in query_for(
        entry, prior=fixture_history()
    )
    assert len(fixture_history()) == 25, "run-1·2 에 아홉씩, run-3 에 넷, run-4 에 셋. 새 벌이 오면 이 수를 고친다"


def test_짝이_있으면_탐색_줄을_같이_싣는다():
    entry = {"kind": "incident", "bundle": {"failureClass": "PAYLOAD_LOST"},
             "search": {"outcome": "FOUND", "steps": [{"skillType": "pick_place"}]}}

    text = query_for(entry)

    assert "remedyOutcome=FOUND" in text
    assert "pick_place" in text


def test_코퍼스_판이_환경에_실린다():
    """⛔ **전에는 「저쪽 것이라 모른다」고 안 찍었다** (2026-09-22 에 바뀜).

    khala 가 코퍼스를 고치면서 적재 시각을 알려 줬고, 적재 명령 옆에 「고치면 시각을
    같이 알려라」를 적어 두겠다고 했다. **값이 생겼으니 찍는다** — 이 경계를 가로질러
    처치 효과를 비교하면 코퍼스가 바뀐 것과 처치가 한 일이 같은 칸에서 섞인다.

    ⚠ **관측이 아니라 신고값이다.** `None` 은 「안 바뀌었다」가 아니라 **그 규약 이전
    판**이라는 뜻이다. 안 싣고 넘어가면 그 구별이 사라지므로 칸은 늘 있어야 한다.
    """
    declared = run_env(top_k=20, model="m", goldenset="eval/goldenset.json",
                       corpus_version="2026-09-22T04:39:29Z")
    before = run_env(top_k=20, model="m", goldenset="eval/goldenset.json")

    assert declared["corpusVersion"] == "2026-09-22T04:39:29Z"
    assert "corpusVersion" in before and before["corpusVersion"] is None


def test_인증_경로가_환경에_실린다():
    """⛔ **축이 하나 더 있었다** (2026-09-22 에 알았다).

    khala 가 배포 설정에서 API 키를 빼면서 생성이 **구독 로그인**으로 바뀌었다. 그전
    판들은 전부 그 키로 돌았다. 모델도 프롬프트도 작업 디렉터리도 같고 **인증과 과금
    경로만 다르다.**

    ⚠ **이 축이 답의 질을 미는지는 아무도 모른다.** 모델이 같으니 민다고 할 근거가
    없지만, **근거 없이 「안 민다」고도 안 적는다.** 적어 두고 가로지르지 않는 것이 이
    칸의 몫이고, `None` 은 「안 바뀌었다」가 아니라 그 규약 이전 판이라는 뜻이다.
    """
    now = run_env(top_k=20, model="m", goldenset="eval/goldenset.json", auth="subscription")
    before = run_env(top_k=20, model="m", goldenset="eval/goldenset.json")

    assert now["auth"] == "subscription"
    assert "auth" in before and before["auth"] is None


def test_판을_접는_셈은_사유를_안_가리고_성공에_되돌아간다():
    """⛔ **넓힌 검사는 넓힌 만큼 반대쪽 대조군이 필요하다** (2026-09-22).

    사유를 `timeout` 하나로 좁혀 놨다가 열셋을 다 태운 뒤 사유를 안 가리게 넓혔는데,
    **「접으면 안 되는 판에서 안 접는다」를 안 걸어 뒀다.** khala 가 같은 날 규칙
    대조군에서 그 자리를 짚었다 — 늘 붙이는 것도 고장이라 「잘 맞은 검색에는 규칙이
    안 붙는다」를 같이 뒀다고.

    안 접어야 하는 자리가 둘이다. **`NO_EVIDENCE` 는 실패가 아니고**(근거가 없다는
    정상 출력이다), **성공이 사이에 들면 연속이 아니다.**
    """
    from eval.run import ABORT_AFTER, straight_failures
    from recorder.outcome import Outcome

    # 접는다 — 사유를 안 가린다
    assert straight_failures(1, Outcome.GENERATION_FAILED) >= ABORT_AFTER

    # 안 접는다 — 근거 없음은 정상 출력이다
    assert straight_failures(1, Outcome.NO_EVIDENCE) == 0
    assert straight_failures(1, Outcome.UNCITED) == 0

    # 안 접는다 — 성공 하나가 연속을 끊는다
    assert straight_failures(straight_failures(1, Outcome.GIVEN), Outcome.GENERATION_FAILED) == 1
