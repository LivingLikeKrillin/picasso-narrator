"""골든셋을 돌려 세 지표를 낸다 — `AGENT-04` §4, 절차는 `AGENT-06` §7.

**사건은 파이프라인과 같은 길을 탄다.** 평가용으로 다른 질의를 만들면 재는 것이
실제로 도는 것과 달라진다.

**도메인 밖 질의는 물음을 안 씌운다.** 지표 3 이 재는 것은 운영자 질의 경로이고,
거기에 사건용 물음을 붙이면 재는 대상이 바뀐다.
"""

import datetime
import json
import pathlib

from composer.query import compose, compose_search
from explainer.transport import TIMEOUT
from receiver.export import read_export
from receiver.history import count_recurrence, subject
from receiver.pipeline import ask_and_record

INCIDENT = "incident"
#: 짝이 되는 사건이 없는 탐색 대장의 줄. 채점기의 것과 같은 값이어야 한다.
SEARCH = "search"


def query_for(entry, prior=None):
    """골든셋 항목 하나의 질의. **파이프라인과 같은 길을 탄다.**

    :param prior: 재발을 셀 이력. `None` 이면 안 싣는다 — 픽스처 이력은
        [fixture_history] 다. 탐색 짝(`search`)이 있으면 같이 싣는다.

    ⛔ **탐색 짝 하나는 평가에만 있고 실행 경로에는 없다 (2026-09-20).** `receiver/pipeline.py`
    의 `explain` 은 사건과 탐색을 각각 설명 대상으로 다루고 짝을 짓지 않는다 —
    `BOUNDARY.md` §4.1 이 그렇게 정했다. 이유는 **없는 짝을 지어내는 것**을 막기 위해서다
    (못 찾은 것을 「대안 없음」으로 적으면 돌지도 않은 탐색을 「찾아봤지만 없다」로 만든다).

    골든셋 G1 의 짝은 지어낸 것이 아니라 실물이다(run-1 의 search-1 이 회복을 찾아냈고
    그 실행이 1초 뒤 incident-1 로 다시 실패했다. 한 벌에 이런 짝은 하나뿐이다). 그래서
    **이 자리는 재는 것과 도는 것이 갈리는 유일한 자리이고, 짝이 쓸모 있는지를 재는
    실험이다.** K 판이 쓸모를 보이면 §4.1 을 다시 볼 근거가 되고, 그 판단은 사람의 것이다.
    """
    if entry["kind"] == INCIDENT:
        recurrence = None if prior is None else count_recurrence(entry["bundle"], prior)
        return compose(entry["bundle"], entry.get("search"), recurrence=recurrence).text
    # **탐색 줄은 사건이 아니다.** 짝이 되는 사건이 없는 줄 하나를 그 자체로 설명한다
    # (`BOUNDARY.md` §4.1). 재발도 안 싣는다 — 세는 것은 사건의 주체이지 탐색이 아니다.
    if entry["kind"] == SEARCH:
        return compose_search(entry["search"]).text
    return entry["query"]


FIXTURE_EXPORTS = pathlib.Path(__file__).parent.parent / "tests" / "fixtures" / "picasso"


def fixture_history():
    """평가가 쓸 이력 — 픽스처 네 벌의 사건 주체 전부.

    ⛔ **재발은 0 이 아니다 (2026-09-22 실측).** run-1·2 두 벌만 있던 2026-09-20 에는 전부 0 이었다 —
    두 벌은 digest 까지 같은 재실행이고 한 벌 안에 같은 기체·같은 분류가 없었다. run-3(재발 한 벌)이
    G3 를 1/1 로, run-4(사건 뒤 탐색)가 G11 을 3/1 로 실었고 **G2 는 3/0 에서 4/1 로 옮겼다** —
    run-4 의 hum-04 사건이 G2 보다 앞서고 자리 이름 `RACK-204.S03` 이 run-1 과 겹친다. 픽스처가
    한 벌 늘 때 골든셋의 재발 수가 바뀌므로 그 축에서는 판을 가로질러 비교하지 않는다.

    ⚠ `sorted(glob)` 은 글자 순서다 — `run-10` 이 `run-2` 앞에 온다. 세는 데는 순서가 안 쓰인다.
    """
    prior = []
    for run in sorted(FIXTURE_EXPORTS.glob("run-*")):
        export = read_export(run)
        if export is not None:
            prior.extend(subject(b) for b in export.incidents)
    return prior


def load(path):
    return json.loads(open(path, encoding="utf-8").read())["entries"]


def load_truth(path):
    """정답표를 읽는다. `incidentId` 로 물린 사전.

    **골든셋과 다른 파일이다.** picasso 가 인계 자리에 따로 내고 「질의를 만드는
    경로에 넣지 말 것」이라고 표시해 뒀다. 질의는 `query_for` 가 **번들에서만**
    만들므로, 정답이 질의로 새려면 누가 번들에 넣어야 한다 —
    `tests/test_goldenset.py` 가 그것을 막는다.

    **사건 id 로 문다.** 골든셋의 `G7` 같은 내 번호가 아니라 저쪽의 `incident-7` 이다.
    내 번호는 내가 고치면 밀리고, 그때 정답이 조용히 딴 사건에 붙는다.
    """
    rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    return {row["incidentId"]: row for row in rows}


def collect(entries, search, limit=2):
    """항목마다 기록 한 건. **실패도 기록이다** — 빠뜨리면 분모가 조용히 줄어든다.

    **배선과 같은 길을 탄다.** 여기서 따로 물으면 평가가 실제로 도는 것과 다른
    것을 재게 된다(2026-09-19 — 재시도도 사유도 없는 경로가 여기 따로 있었다).
    """
    history = fixture_history()
    return [
        ask_and_record(("golden", entry["id"]), query_for(entry, prior=history), search, limit)
        for entry in entries
    ]


#: 연속 몇 번이면 판을 접나. **둘 연속이면 우연이 아니다** — 성공한 판의 벽시계
#: 중앙값이 200초 근처다.
ABORT_AFTER = 2


def straight_failures(previous, outcome):
    """연속 실패 수. **성공 하나가 0 으로 되돌린다.**

    ⛔ **사유를 `timeout` 하나로 좁혀 놨다가 열셋을 다 태웠다**(2026-09-22 실측).
    그날 생성이 `unavailable` 로 죽었는데 검사가 그 사유를 안 보고 지나쳤다. 접어야 할
    이유는 「벽에 잘렸다」가 아니라 **「생성이 연속으로 안 선다」**다.

    ⛔ **그리고 넓히면서 반대쪽을 안 걸어 뒀다**(2026-09-22, khala 가 짚었다).
    **넓힌 검사는 넓힌 만큼 반대쪽 대조군이 필요하다** — 저쪽은 규칙을 늘 붙이는 것도
    고장이라며 「잘 맞은 검색에는 안 붙는다」를 같이 뒀다. 여기서 안 접어야 하는 자리는
    둘이다.

    - **`NO_EVIDENCE` 는 실패가 아니다.** 근거가 없다는 정상 출력이라 코퍼스가 빈
      질의만 몇 개 연달아도 판이 접히면 안 된다
    - **성공이 하나라도 사이에 들면 연속이 아니다.** 한 번 튄 것과 계속 죽어 있는
      것은 다른 일이고, 그 구별이 이 함수의 전부다
    """
    from recorder.outcome import Outcome

    return previous + 1 if outcome is Outcome.GENERATION_FAILED else 0


def run_env(top_k, model, goldenset, exclude_doc_types=(), goldenset_version=None, arm=None,
            corpus_version=None, auth=None):
    """이 판이 무엇 위에서 돌았나. **결과 옆에 붙여 둔다.**

    ⛔ **안 찍고 있었다**(2026-09-19). 같은 골든셋을 여덟 판 돌렸는데 `top_k` 가 8 인
    판과 20 인 판이 **기록만 보고는 안 갈린다.** 그 둘은 지표 1 이 1/4 과 3/4 으로
    갈린 차이다. 모델도 두 종을 돌렸고 벽도 120·180·300 을 오갔다.

    「기록만 있으면 스택 없이 다시 센다」는 **그 기록이 어느 스택 것인지 알 때만** 참이다.

    ⚠ **아는 것만 찍는다.** 브리지 벽은 저쪽 것이고 응답에 안 온다 — 모르는 것을
    찍으면 그때부터 기록이 거짓말을 한다. `model` 은 **저쪽이 응답에 실어 보내는 값**
    이라 관측이지 내 선언이 아니다.

    ⛔ **코퍼스 판은 2026-09-22 부터 찍는다.** 전에는 「저쪽 것이고 응답에 안 온다」는
    이유로 안 찍었다. 그날 저쪽이 코퍼스를 고치면서 시각을 알려 줬고, **적재 명령 옆에
    「고치면 시각을 같이 알려라」를 적어 두겠다**고 했다. 그래서 값이 생겼다.

    ⚠ **이건 관측이 아니라 저쪽 신고값이다.** 저쪽이 말 없이 다시 적재하면 이 칸은
    조용히 낡는다. `None` 이면 그 규약 이전 판이라는 뜻이지 「안 바뀌었다」가 아니다.
    """
    return {
        "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "top_k": top_k,
        "model": model,
        #: 내 벽. **저쪽 벽과 다르고, 작은 쪽이 이긴다**(khala `#517`).
        "clientTimeout": TIMEOUT,
        "goldenset": goldenset,
        #: 사건 질의에서 뺀 문서 종류. **안 찍으면 이 판이 필터를 쓴 판인지 기록만으로
        #: 못 가린다** — 위 `top_k` 가 그래서 여기 있는 것과 같은 이유다.
        "excludeDocTypes": list(exclude_doc_types),
        #: 골든셋의 판. ⛔ **항목이 늘면 옛 기록은 다시 셀 수 없다**(2026-09-20 실측 —
        #: v6 이 탐색 줄 하나를 더하자 12줄짜리 L 판 기록이 안 맞았다). 그때 「왜 안
        #: 맞는지」를 기록이 말해야 사람이 판을 대조한다.
        "goldensetVersion": goldenset_version,
        #: 실험군. khala 사전 등록의 T0(대조군)·T2(식별자 채널). **안 찍으면 두 판을
        #: 나란히 놓을 수 없다** — 위 `excludeDocTypes` 와 같은 이유다.
        "arm": arm,
        #: 코퍼스 적재 시각(저쪽 신고값). ⛔ **이 경계를 가로질러 처치 효과를 비교하지
        #: 않는다** — 코퍼스가 바뀐 것과 처치가 한 일이 같은 칸에서 섞인다.
        "corpusVersion": corpus_version,
        #: 생성이 어느 인증 경로로 돌았나(저쪽 신고값). ⛔ **2026-09-22 에 생겼다.**
        #: 그전 판들은 `nexus/.env` 의 API 키로 돌았고, khala 가 `#535` 로 그 키를 빼면서
        #: **구독 로그인으로 바뀌었다.** 모델도 프롬프트도 작업 디렉터리도 같지만 인증과
        #: 과금 경로가 다르다.
        #:
        #: ⚠ **이 축이 답의 질을 미는지는 아무도 모른다.** 모델이 같으므로 민다고 할
        #: 근거가 없지만, 근거 없이 「안 민다」고 적지도 않는다. 적어 두고 가로지르지
        #: 않는 것이 이 칸의 몫이다. `None` 은 그 규약 이전 판이라는 뜻이다.
        "auth": auth,
    }
