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
