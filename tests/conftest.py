"""실물 응답 픽스처 — 2026-09-18 라이브 Nexus 에서 뜬 전문(`AGENT-05` 인계).

추측한 모양이 아니라 실제로 받은 것이라, 이 파일들이 소비 표면의 계약이다.
"""

import json
import pathlib

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "nexus"


@pytest.fixture
def nexus():
    """`nexus("06-answer-no-evidence")` -> `(status, response)`."""

    def load(name):
        raw = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
        return raw["status"], raw["response"]

    return load


EXPORTS = pathlib.Path(__file__).parent / "fixtures" / "picasso"


@pytest.fixture
def export_dir():
    """`export_dir("run-1")` -> picasso 가 실물로 낸 한 벌의 경로."""
    return lambda name: EXPORTS / name


APPROVALS = pathlib.Path(__file__).parent / "fixtures" / "approvals"


@pytest.fixture
def approval():
    """`approval("01-approved")` -> `(status, response)`. 2026-09-18 실물."""

    def load(name):
        raw = json.loads((APPROVALS / f"{name}.json").read_text(encoding="utf-8"))
        return raw["status"], raw["response"]

    return load


#: run-1 의 search-1 그대로(picasso 인계본, 읽기만). 진단 요청의 기본 스냅샷이 든다.
SEARCH_1 = {
    "searchId": "search-1", "robotId": "hum-02", "jobOrderId": "PATROL-1",
    "at": "2026-09-06T00:00:01Z", "wallClockAt": "2026-09-22T16:47:30.473263200Z",
    "outcome": "FOUND",
    "steps": [{"skillType": "pick_place", "requires": [], "expectedHold": "HOLD_KIND_EMPTY",
               "onFailureHold": "HOLD_KIND_HOLDING"}],
}

#: 권고 예제의 후보 둘. 식별자는 계약 §3.1 의 재료 순서(기체 · 주문 · 조치 열).
APPROVE = {
    "candidateId": "APPROVE_REMEDY:hum-02:PATROL-1:pick_place", "kind": "APPROVE_REMEDY",
    "ref": {"robotId": "hum-02", "jobOrderId": "PATROL-1", "searchId": "search-1"},
    "sawSkillTypes": ["pick_place"],
}
ESCALATE_CANDIDATE = {"candidateId": "ESCALATE", "kind": "ESCALATE", "ref": None}


@pytest.fixture
def diagnose_request():
    """`diagnose_request(**칸)` -> 진단 계약 0.6 요청 하나(권고 예제 모양). 칸을 넘기면 덮는다.

    후보 판(`candidatesVersion`)은 koshei 만 계산한다 — 여기 값은 모양만 맞춘 가짜다.
    """

    def build(**over):
        payload = {
            "contractVersion": "0.6",
            "episodeId": "ep-1",
            "attempt": 1,
            "snapshot": {"manifest": {"schemaVersion": "5", "runId": "run-x"},
                         "incidents": [], "searches": [dict(SEARCH_1)]},
            "candidates": [dict(APPROVE), dict(ESCALATE_CANDIDATE)],
            "candidatesVersion": "sha256:" + "0" * 64,
            "unknowns": [],
            "history": [],
        }
        payload.update(over)
        return payload

    return build


#: 권고 A 를 고른 답. 머리 두 줄 · 다섯 표지 · 구분선 · 본문.
ANSWER_A = (
    "권고: A\n"
    "이유: 탐색이 찾은 조치의 전제가 관측과 맞는다 [출처: SOP-02 안착 실패와 품번 불일치, §3].\n"
    "절차: 파지 상태를 먼저 확인한다 [출처: SOP-02 안착 실패와 품번 불일치, §5].\n"
    "먼저: 근거 없음.\n"
    "금지: 근거 없음.\n"
    "갈림: 근거 없음.\n"
    "근거 세기: 로봇 자체 보고 하나다.\n"
    "\n"
    "---\n"
    "\n"
    "## 원인 후보\n"
    "후보 ① — 파지물 낙하."
)


@pytest.fixture
def khala_data():
    """`khala_data(**칸)` -> khala 답변의 `data` 하나(권고 A 를 고른 답, 검증된 인용 하나). 칸을 넘기면 덮는다."""

    def build(**over):
        data = {
            "answer": ANSWER_A,
            "citations": [{"title": "SOP-02 안착 실패와 품번 불일치", "section": "§3",
                           "verified": True, "provenance_tier": "authored"}],
            "abstained": False, "weak_evidence": False,
            "llm_failed": False, "llm_failure_reason": None,
            "unverified_citations": 0, "unverified_numbers": 0, "numbers": [],
            "usage": {"model": "claude-sonnet-5"},
            "timing_ms": {}, "evidence_snippets": [],
        }
        data.update(over)
        return data

    return build
