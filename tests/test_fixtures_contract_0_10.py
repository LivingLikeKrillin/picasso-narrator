"""계약 0.10.0 인계 세트 — 운영 경로가 새 세트를 그대로 받는가.

측정 기준 세트(`fixtures/picasso/`, 계약 0.9.0 · 스키마 5)는 과거 측정 기록과 koshchei 사본이 바이트로
기대고 있어 그대로 둔다. 이 세트는 그 옆에서 **운영이 지금 picasso 가 내는 번들을 받는지**만 본다.
"""

import json
import pathlib

import pytest

from composer.query import compose
from recorder.store import RecordStore
from receiver.run import once
from receiver.scan import scan

SET = pathlib.Path(__file__).parent / "fixtures" / "picasso-0.10.0"
RUNS = ("run-1", "run-2", "run-3", "run-4")


def _ok(query, search_text=None):
    return 200, {
        "success": True,
        "data": {"llm_failed": False, "answer": "…", "citations": [{"verified": True}]},
    }


@pytest.mark.parametrize("run", RUNS)
def test_새_세트의_줄마다_설명이_한_건씩_붙는다(tmp_path, run):
    """스키마 6 · 계약 0.10.0 번들도 빠지는 줄 없이 한 건씩 적힌다. 질의에는 계약 버전이 번들 값 그대로 실린다."""
    manifest = json.loads((SET / run / "manifest.json").read_text(encoding="utf-8"))
    assert (manifest["schemaVersion"], manifest["contractSemver"]) == ("6", "0.10.0")
    store = RecordStore(tmp_path / "explanations.jsonl")

    written = once(SET / run, store, search=_ok)

    counts = manifest["counts"]
    assert written == len(store.load()) == counts["incidents"] + counts["remedySearches"]
    batch = scan(SET / run, set())
    assert all(compose(b).facts["contractSemver"] == "0.10.0" for b in batch.incidents)
