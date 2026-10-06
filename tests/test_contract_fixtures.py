"""진단 계약의 고정 예제 — 요청은 koshei 가 투영으로 짓고, 응답은 이 계층이 진단 함수로 짓는다(계약 §8).

요청은 koshei 정본의 바이트 사본이다(`tests/fixtures/contract/diagnosis/README.md`). 응답은 손으로 쓰지 않는다 — 사본을
`run_diagnosis` 에 넣고 시나리오마다 고정한 가짜 khala 답(`khala/`)을 물려 짓는다. 코드가 바뀌어 응답이 달라지면 첫 테스트가
빨개진다. 의도한 변화면 `NARRATOR_UPDATE_FIXTURES=1` 로 다시 짓고(그 판은 일부러 빨갛다) 환경 변수 없이 다시 돌린 뒤 koshei 에
알린다 — 그쪽이 응답을 복사해 대조한다.
"""

import json
import os
import pathlib
import types

import pytest

import receiver.pipeline as pipeline
from diagnose.contract import RESPONSE_KEYS, parse_request
from diagnose.core import run_diagnosis
from explainer.client import INCIDENT_EXCLUDED, nexus_client

HERE = pathlib.Path(__file__).parent / "fixtures" / "contract" / "diagnosis"
RUN_1 = pathlib.Path(__file__).parent / "fixtures" / "picasso" / "run-1"

#: 예제마다 (결과, 고른 후보, picked) — 계약 §4 의 판정을 글자로 박는다. 응답을 다시 지어도 이것은 안 바뀐다
EXPECTED = {
    "01-recommended": ("RECOMMENDED", "APPROVE_REMEDY:hum-02:PATROL-1:pick_place", None),
    "02-no-grounds": ("NO_GROUNDS", None, None),
    "03-out-of-candidates": ("OUT_OF_CANDIDATES", None, "SEQ-IN-05.BIN-A 로 옮겨 집는다"),
    "04-unknown": ("RECOMMENDED", "OPERATOR_DECISION:exec-8:RACK-204.S06:CONFIRM_DONE", None),
}

#: 응답 예제의 시간(초). 가짜 전송은 곧바로 답하므로 실제 서비스 실행에서 흔한 값을 박는다 — 테스트가 시계를 고정한다
ELAPSED = 212.4

#: 응답 예제의 narrator 버전. 계약 §4 의 예와 같은 대역이다
COMMIT = "0000000"


def _load(folder, name):
    return json.loads((HERE / folder / f"{name}.json").read_text(encoding="utf-8"))


def _lines(name):
    return [json.loads(line) for line in (RUN_1 / name).read_text(encoding="utf-8").splitlines() if line.strip()]


def _built(name, monkeypatch):
    """사본 요청 하나를 진단 함수에 넣어 지은 응답의 바이트. 클라이언트 설정은 워커와 같다."""
    data, sent = _load("khala", name), []

    def transport(method, url, headers, body):
        sent.append(body)
        return 200, {"success": True, "data": data}

    def client(answer_context):
        return nexus_client("http://x", token="t", tenant="picasso", transport=transport,
                            exclude_doc_types=INCIDENT_EXCLUDED, identifier_channel=True,
                            answer_context=answer_context)

    ticks = [1000.0, 1000.0 + ELAPSED]  # 처음 부르면 시작, 그 뒤로는 늘 끝 — 몇 번을 불러도 떨어지지 않는다
    monkeypatch.setattr(pipeline, "time",
                        types.SimpleNamespace(monotonic=lambda: ticks.pop(0) if len(ticks) > 1 else ticks[0]))
    response = run_diagnosis(parse_request(_load("requests", name)), client, COMMIT).response
    assert "모름" not in sent[0]["answer_context"], "후보와 확인 불가를 다 읽었다 — ref 의 칸 이름이 바뀌면 「모름」이 된다"
    return (json.dumps(response, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


@pytest.mark.parametrize("name", EXPECTED)
def test_응답_예제는_지금_코드가_짓는_그대로다(name, monkeypatch):
    built = _built(name, monkeypatch)
    path = HERE / "responses" / f"{name}.json"
    if os.environ.get("NARRATOR_UPDATE_FIXTURES") == "1":
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(built)
        pytest.fail("응답 예제를 다시 지었다 — 환경 변수 없이 다시 돌리고 koshei 에 알린다", pytrace=False)
    assert path.read_bytes() == built, (
        "진단 코드가 바뀌어 응답이 달라졌다 — 의도했으면 NARRATOR_UPDATE_FIXTURES=1 로 다시 짓고 koshei 에 알린다")


@pytest.mark.parametrize("name", EXPECTED)
def test_응답_예제는_요청을_되돌려주고_시나리오를_지킨다(name):
    request, response, khala = _load("requests", name), _load("responses", name), _load("khala", name)

    assert list(response) == list(RESPONSE_KEYS)
    assert (response["episodeId"], response["attempt"], response["sawCandidatesVersion"]) == (
        request["episodeId"], request["attempt"], request["candidatesVersion"]), "요청의 세 값을 그대로 돌려준다"
    assert (response["outcome"], response["candidateId"], response["picked"]) == EXPECTED[name]
    assert response["elapsedSeconds"] == ELAPSED, "시계를 고정했다 — 다르면 고정이 안 먹었다"
    assert response["citations"] == khala["citations"], "인용은 khala 가 준 그대로 싣는다"
    assert response["versions"] == {"modelId": khala["usage"]["model"], "promptVersion": khala["prompt_version"],
                                    "corpusVersion": khala["corpus_version"],
                                    "searchFingerprint": khala["search_fingerprint"], "narratorCommit": COMMIT}
    snapshot = request["snapshot"]
    assert snapshot["manifest"] == json.loads((RUN_1 / "manifest.json").read_text(encoding="utf-8"))
    assert all(row in _lines("incidents.jsonl") for row in snapshot["incidents"])
    assert all(row in _lines("remedy-searches.jsonl") for row in snapshot["searches"]), "인계본 줄을 가공 없이 싣는다"
    if name == "01-recommended":
        assert response["rationale"] and response["uncitedSentences"] == [] and response["unverifiedClaims"] == [], (
            "자동 승인 조건(requireClean)을 통과하는 모양")
    if name == "03-out-of-candidates":
        assert [claim["kind"] for claim in response["unverifiedClaims"]] == ["CITATION"], "검증 못 한 인용 하나"
    if name == "04-unknown":
        assert request["unknowns"], "확인 불가 예제다"
        assert all(c["kind"] == "ESCALATE" or (c["kind"] == "OPERATOR_DECISION" and c["ref"]["decision"] == "CONFIRM_DONE")
                   for c in request["candidates"]), "확인 불가면 실행 계열 후보가 없다(계약 §3.3)"
