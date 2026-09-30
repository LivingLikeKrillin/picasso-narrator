"""권고 측정기 — 설계서 `docs/superpowers/specs/2026-09-30-권고-측정.md` §6. **실물 khala 를 부른다.**

    NEXUS_TOKEN=… python -m eval.recommend                                   # 첫 판 → eval/last-recommendations.json
    NEXUS_TOKEN=… python -m eval.recommend --only R03,R11 --out eval/last-recommendations-rerun.json
    NEXUS_TOKEN=… python -m eval.recommend --pass repeat --only R01,R03 --out eval/last-recommendations-repeat.json

진단 워커와 **같은 함수**(`diagnose.core.run_diagnosis`)를 부른다(계약 §7 「같은 길」). 저장소를 모르는 함수라 첫 결과
저장소에 걸리지 않는다. khala 클라이언트는 워커와 같은 인자이고 빼는 종류에 과거 사례(`case`)만 더한다(계약 §7).

**얼릴 것이 커밋되지 않았거나 고쳐진 트리에서는 돌지 않는다**(설계서 §0) — 기록의 `env` 에 적은 객체 해시가 곧 이 판을 잰
규칙이다. **먼저 다 본다** — khala 를 부르기 전에 사례 전부를 읽고 짓는다. 하나라도 안 되면 아무것도 안 부른다. **멈춰도
기록은 남긴다** — 사례마다 기록을 통째로 다시 쓰고 `complete` 는 판 끝에서만 참이다. **있는 기록을 덮지 않는다** — 다시
돌기는 다른 파일에 쓰고 재채점이 합친다(`--force` 로만 덮는다).
"""

import argparse
import datetime
import hashlib
import io
import json
import os
import pathlib
import subprocess
import sys
import time

from diagnose.context import aliases, render
from diagnose.contract import parse_request
from diagnose.core import query_text, run_diagnosis
from diagnose.judge import DiagnoseFailed
from eval.recommend_score import CASES, RECORD, ROOT, load_cases, scoring_hash
from explainer.client import ANSWER_TOP_K, INCIDENT_EXCLUDED, nexus_client
from explainer.transport import TIMEOUT, http_transport
from recorder.outcome import TRANSIENT

REQUESTS = ROOT / "eval" / "recommend-requests"
#: 계약 §7 — 측정은 과거 사례 종류를 뺀다. 과거 사례는 테넌트 `narrator` 에 있어 지금은 걸러지는 것이 없다.
EXCLUDE = tuple(INCIDENT_EXCLUDED) + ("case",)
TENANT = "picasso"
#: koshei 정책 예시의 `diagnosis.maxAttempts`.
MAX_ATTEMPTS = 2
#: 다음 사례도 같을 사유 — 곧바로 멈춘다.
ABORT_ON = ("quota", "auth")
#: 잇달아 이만큼 실패하면 멈춘다(설명 측정과 같다).
ABORT_AFTER = 2
FROZEN = ("eval/goldenset-recommend.json", "eval/recommend-requests", "eval/recommend_score.py", "eval/recommend.py")
#: ⚠ 윈도에서는 누가 기록을 열어 둔 동안(재채점으로 엿보기 · 백신 검사) 이름 바꾸기가 `PermissionError` 로 막힌다 — 이만큼
#: 쉬며 이만큼 다시 해 본다.
WRITE_PAUSE, WRITE_TRIES = 0.5, 20


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


def prepare(doc, only=None, requests=REQUESTS):
    """사례마다 요청을 읽고 짓는다 — khala 를 부르기 전에 전부. 하나라도 안 되면 `SystemExit`."""
    wanted = set(only or [])
    unknown = wanted - {c["id"] for c in doc["cases"]}
    if unknown:
        raise SystemExit(f"사례 파일에 없는 사례: {sorted(unknown)}")
    prepared, errors = [], []
    for case in doc["cases"]:
        if wanted and case["id"] not in wanted:
            continue
        try:
            raw = (requests / case["request"]).read_bytes()
            if sha(raw) != case["requestSha256"]:
                raise ValueError("요청 파일의 sha256 이 사례 파일과 다르다")
            request = parse_request(json.loads(raw.decode("utf-8")))
            context = render(request.candidates, request.unknowns, request.history)
            query = query_text(request.snapshot)
            prepared.append({"case": case, "request": request, "aliases": aliases(request.candidates),
                             "context": context, "query": query, "requestSha256": sha(raw)})
        except Exception as error:  # noqa: BLE001 — 사례마다 모아서 한꺼번에 알린다
            errors.append(f"{case['id']}: {type(error).__name__}: {error}")
    if errors:
        raise SystemExit("먼저 보기에서 멈춘다 — khala 를 한 번도 안 불렀다\n" + "\n".join(errors))
    return prepared


def git(*args, root=ROOT):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout.strip()


def frozen_problems(root=ROOT):
    """얼릴 경로 넷이 추적되고 HEAD 와 같은가, 그 밖의 추적 파일이 고쳐지지 않았나(설계서 §0). 걸린 것의 목록.

    ⚠ `--untracked-files=no` 만 보면 **한 번도 커밋하지 않은 새 파일**이 안 잡힌다 — 새 사례 파일이 바로 그 모양이다.
    """
    problems = [f"{path}: 커밋되지 않았다" for path in FROZEN
                if subprocess.run(["git", "ls-files", "--error-unmatch", path], cwd=root, capture_output=True).returncode]
    problems += [f"HEAD 와 다르다: {line}" for line in git("status", "--porcelain", "--", *FROZEN, root=root).splitlines()]
    problems += [f"고친 추적 파일: {line}"
                 for line in git("status", "--porcelain", "--untracked-files=no", root=root).splitlines()]
    return problems


def environment(doc, pass_name, only, base):
    return {
        "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "pass": pass_name, "only": list(only) if only else None,
        "narratorCommit": git("rev-parse", "HEAD"), "frozen": True,
        "cases": {"path": "eval/goldenset-recommend.json", "version": doc["version"],
                  "blob": git("rev-parse", "HEAD:eval/goldenset-recommend.json"), "scoringHash": scoring_hash(doc)},
        "requests": {"path": "eval/recommend-requests", "tree": git("rev-parse", "HEAD:eval/recommend-requests")},
        "scorer": git("rev-parse", "HEAD:eval/recommend_score.py"),
        "measurer": git("rev-parse", "HEAD:eval/recommend.py"),
        "koshei": doc["source"],
        "nexus": base, "tenant": TENANT, "topK": ANSWER_TOP_K, "excludeDocTypes": list(EXCLUDE),
        "identifierChannel": True, "clientTimeout": TIMEOUT, "auth": "subscription",
        "retry": {"maxAttempts": MAX_ATTEMPTS, "retryOn": sorted(TRANSIENT), "abortOn": list(ABORT_ON),
                  "abortAfterStraight": ABORT_AFTER, "rerunAtEnd": 1},
        "concurrency": 1,
    }


def attempt(prep, client, commit, clock=time.time, timer=time.monotonic):
    """한 번. `(시도 기록, Diagnosis 또는 None, 실패 사유 또는 None)`.

    생성 실패 밖의 예외도 사유(`exception:<종류>`, 재시도 안 함)로 적고 판을 잇는다 — 몇 시간짜리 판이 사례 하나의 뜻밖의
    예외로 죽지 않게. 끊기(`KeyboardInterrupt`)는 잡지 않는다 — 그때까지의 기록은 이미 파일에 있다.
    """
    started, t0 = clock(), timer()
    try:
        diagnosis = run_diagnosis(prep["request"], client, commit)
    except DiagnoseFailed as failed:
        return {"at": started, "elapsed": round(timer() - t0, 1), "reason": failed.reason}, None, failed.reason
    except Exception as error:  # noqa: BLE001 — 판을 잇는다. 무엇이었는지는 기록에 남긴다
        reason = f"exception:{type(error).__name__}"
        return ({"at": started, "elapsed": round(timer() - t0, 1), "reason": reason, "detail": str(error)[:500]},
                None, reason)
    return {"at": started, "elapsed": round(timer() - t0, 1), "reason": None}, diagnosis, None


def row_of(prep, attempts, diagnosis, reason):
    """기록의 줄 하나(설계서 §6). 답이 있으면 계약 응답 전부와 답 글과 계측 전부를 담는다."""
    request = prep["request"]
    row = {
        "id": prep["case"]["id"], "tier": prep["case"]["tier"], "requestSha256": prep["requestSha256"],
        "candidatesVersion": request.candidates_version, "querySha256": sha(prep["query"]),
        "contextSha256": sha(prep["context"]), "aliases": prep["aliases"],
        "kinds": {c["candidateId"]: c["kind"] for c in request.candidates}, "attempts": attempts,
        "failed": reason, "response": None, "rawPick": None, "resolved": None, "recordOutcome": None,
        "answer": None, "diagnostics": None,
    }
    if diagnosis is not None:
        record = diagnosis.record
        row.update(response=diagnosis.response, rawPick=diagnosis.raw_pick, resolved=diagnosis.resolved,
                   recordOutcome=record.outcome.value, answer=record.answer, diagnostics=dict(record.diagnostics))
    return row


def run_case(prep, client, commit, attempts=None, rerun=False, budget=MAX_ATTEMPTS, **clocks):
    """사례 하나를 재시도까지. 재시도할 사유면 한 번 더([MAX_ATTEMPTS]). 시도는 다 적는다. 판 끝에서 다시 도는 시도는
    koshei 의 `maxAttempts` 밖이라 `rerun` 으로 표시하고 한 번만 한다(`budget=1`)."""
    attempts = list(attempts or [])
    while True:
        record, diagnosis, reason = attempt(prep, client, commit, **clocks)
        attempts.append(dict(record, n=len(attempts) + 1, **({"rerun": True} if rerun else {})))
        budget -= 1
        if diagnosis is not None or reason not in TRANSIENT or budget == 0:
            return row_of(prep, attempts, diagnosis, reason)


def write(path, env, rows, complete):
    """기록을 통째로 다시 쓴다 — 임시 파일에 쓰고 이름을 바꾼다. 멈춰도 그때까지의 답이 남는다."""
    tmp = pathlib.Path(str(path) + ".tmp")
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump({"env": env, "complete": complete, "rows": rows}, handle, ensure_ascii=False, indent=1)
    for _ in range(WRITE_TRIES - 1):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(WRITE_PAUSE)
    os.replace(tmp, path)


def stop(row, straight):
    """멈출 까닭이 있으면 그 글, 없으면 `None`. `quota` · `auth` 는 곧바로, 잇단 실패는 [ABORT_AFTER] 에서."""
    if row["failed"] in ABORT_ON:
        return f'멈춘다 — {row["failed"]} 는 다음 사례도 같다. 기록은 complete=false 로 남았다'
    if straight >= ABORT_AFTER:
        return f"멈춘다 — {ABORT_AFTER} 사례가 잇달아 실패했다. 기록은 complete=false 로 남았다"
    return None


def measure(prepared, client, commit, env, out, **clocks):
    """판 하나. 사례 차례대로, 멈춤 규칙과 끝의 다시 돌기(사례마다 한 번, 같은 멈춤 규칙)까지. `(rows, complete)`."""
    rows, straight = [], 0
    for prep in prepared:
        row = run_case(prep, client, commit, **clocks)
        rows.append(row)
        write(out, env, rows, complete=False)
        print(f'{row["id"]} {(row["response"] or {}).get("outcome") or "실패:" + str(row["failed"])} '
              f'표지={row["rawPick"]!r} 시도={len(row["attempts"])}', flush=True)
        straight = straight + 1 if row["failed"] else 0
        why = stop(row, straight)
        if why:
            print(why, flush=True)
            return rows, False
    straight = 0
    for i, row in enumerate(rows):
        if row["failed"] not in TRANSIENT:
            continue
        prep = next(p for p in prepared if p["case"]["id"] == row["id"])
        rows[i] = run_case(prep, client, commit, attempts=row["attempts"], rerun=True, budget=1, **clocks)
        write(out, env, rows, complete=False)
        print(f'{row["id"]} 다시: {(rows[i]["response"] or {}).get("outcome") or "실패:" + str(rows[i]["failed"])}',
              flush=True)
        straight = straight + 1 if rows[i]["failed"] else 0
        why = stop(rows[i], straight)
        if why:
            print(why, flush=True)
            return rows, False
    write(out, env, rows, complete=True)
    return rows, True


def client_for(base, token, transport=http_transport):
    """`client(answer_context)` — 워커와 같은 인자(테넌트 · `top_k` · 식별자 채널 · 자료 칸)에 빼는 종류만 [EXCLUDE]."""

    def client(answer_context):
        return nexus_client(base, token=token, tenant=TENANT, transport=transport, exclude_doc_types=EXCLUDE,
                            identifier_channel=True, answer_context=answer_context)

    return client


def main(argv=None):
    parser = argparse.ArgumentParser(description="권고 측정 — 실물 khala")
    parser.add_argument("--pass", dest="pass_name", default="first")
    parser.add_argument("--only", default="")
    parser.add_argument("--out", default=str(RECORD))
    parser.add_argument("--force", action="store_true", help="이미 있는 --out 을 덮는다 — 그 판의 답을 잃는다")
    args = parser.parse_args(argv)
    token = os.environ.get("NEXUS_TOKEN")
    if not token:
        raise SystemExit("Nexus 토큰이 없다. NEXUS_TOKEN 으로 준다. 값은 저장소에 두지 않는다 (.secrets/nexus-tokens.env)")
    problems = frozen_problems()
    if problems:
        raise SystemExit("얼릴 것이 커밋되지 않았거나 고쳐졌다 — 커밋하고 돈다(설계서 §0)\n" + "\n".join(problems))
    out = pathlib.Path(args.out)
    if not out.parent.is_dir():
        raise SystemExit(f"기록을 둘 폴더가 없다: {out.parent}")
    if out.exists() and not args.force:
        raise SystemExit(f"기록이 이미 있다: {out} — 다시 돌기는 다른 --out 에 쓰고 재채점이 합친다(덮으려면 --force)")
    doc = load_cases(CASES)
    only = [x for x in args.only.split(",") if x]
    prepared = prepare(doc, only)
    base = os.environ.get("NEXUS_URL", "http://localhost:8000")
    env = environment(doc, args.pass_name, only, base)
    _, complete = measure(prepared, client_for(base, token), git("rev-parse", "--short", "HEAD"), env, out)
    return 0 if complete else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
