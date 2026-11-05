# picasso 인계 세트 (계약 0.10.0)

2026-11-05 picasso PR #144에서 계약 SemVer를 0.10.0으로 올리고 다시 낸 인계 번들 네 세트(run-1~run-4)다. 출처는 picasso 저장소 `handoff/narrator/`(커밋 14410e1, picasso main 0a06f08 시점)다.
기계가 읽는 파일만(run-*/ 의 incidents.jsonl·remedy-searches.jsonl·manifest.json, entitlements.json, ground-truth.jsonl) 들였고, 안내문 INDEX.txt(sha256 앞자리 d6cae0db)는 들이지 않는다.
`tests/test_fixtures_contract_0_10.py`에서 운영 경로(`receiver.run.once`)가 새 세트의 줄마다 설명을 한 건씩 적고 질의에 contractSemver 0.10.0 이 번들 값 그대로 실리는지 시험한다.
측정 기준 세트는 기존 `tests/fixtures/picasso/` 에 둔 채로 유지하며, 측정 기준을 새 세트로 옮기는 일은 다음에 실측을 다시 돌릴 때 함께 한다.
