"""생성 실행 — 진단 경로 한 바퀴. 설계서 `docs/superpowers/specs/2026-10-02-생성-판-진단-경로.md`.

**실행.** 권고 사례 스물하나(반복 R02 뺌)를 사례마다 두 실험군(D0 오늘 그대로 · D3 검색 텍스트는 Q3, 답변 컨텍스트는 Q0 와 후보 자료)으로
잇달아 진단한다::

    KHALA_ROOT=<khala 저장소> python -m eval.gen_diag_trial run d-1 --out eval/gen/d-1.json
    KHALA_ROOT=<khala 저장소> python -m eval.gen_diag_trial run d-1r --out eval/gen/d-1r.json --only R03:D3,R07   # 고장 줄 다시

**평가 도구.** 기록만 읽는 순수 함수다 — 실험군마다 줄을 권고 측정의 채점(`eval/recommend_score.py`)에 넘긴다. 기록 여럿은 시각 차례로
합치고 같은 (사례, 실험군)은 뒤의 줄이 이긴다::

    python -m eval.gen_diag_trial tally eval/gen/d-1.json [eval/gen/d-1r.json]

진단은 운영 경로와 같은 함수(`diagnose.core.run_diagnosis`)를 권고 측정기의 시도 규칙(`eval.recommend.run_case`)으로 부른다. 그
함수는 질의를 인자로 안 받으므로 실행기가 클라이언트 자리(`answer_context -> search`)에서 함수가 지은 질의와 답변 컨텍스트를 적고 실험군의
글로 바꿔 보낸다. `eval/recommend.py` 와 앞 실행들의 실행기는 고치지 않는다.
"""

import collections
import json
import os
import pathlib
import sys

from diagnose.context import LIMIT as CONTEXT_LIMIT
from eval import ask_trial as at
from eval import fusion_trial as ft
from eval import gen_trial as gt
from eval import query_trial as qt
from eval import recommend as rec
from eval import recommend_score as rs
from explainer.client import ANSWER_TOP_K, nexus_client
from explainer.transport import http_transport

SPEC = "docs/superpowers/specs/2026-10-02-생성-판-진단-경로.md"
COMMITTED = (SPEC, "eval/gen_diag_trial.py", "tests/test_eval_gen_diag_trial.py", "eval/gen_trial.py", "eval/ask_trial.py",
             "eval/query_trial.py")
ARMS = ("D0", "D3")
#: 앞 실행과의 견줌(설계서 §3) — 설명 경로 실행의 `_reference` 가 질문 제거 첫 실행을 G0 ↔ Q0 · G3 ↔ Q3 로 읽는다.
REFERENCE_ARMS = {"D0": "G0", "D3": "G3"}
sha = gt.sha


def plan(doc=None):
    """사례마다 두 실험군의 (질의, 답변 컨텍스트)와 부르는 차례(설계서 §1). 반복(R02)은 뺀다.

    D0 는 권고 측정기가 지을 글 그대로(Q0 · `render`), D3 은 질문 제거의 Q3 에 답변 컨텍스트 = Q0 + 빈 줄 + `render`. 홀수째 사례는 D0 먼저,
    짝수째는 D3 먼저."""
    doc = doc or rs.load_cases()
    built = qt.queries(doc)
    out = []
    for i, prep in enumerate(p for p in rec.prepare(doc) if not p["case"]["repeatOf"]):
        cid = prep["case"]["id"]
        three = at.texts(built[cid])
        if three["Q0"] != prep["query"]:
            raise ValueError(f"{cid}: 물음 떼기의 Q0 가 진단의 질의와 다르다")
        context = prep["query"] + "\n\n" + prep["context"]
        if len(context) > CONTEXT_LIMIT:
            raise ValueError(f"{cid}: D3 의 자료 칸이 {len(context)}자로 상한 {CONTEXT_LIMIT}자를 넘는다")
        out.append({"prep": prep, "order": ARMS if i % 2 == 0 else ARMS[::-1],
                    "D0": {"query": prep["query"], "context": prep["context"]},
                    "D3": {"query": three["Q3"], "context": context}})
    return out


def targets(only):
    """`--only` 의 항목 → (사례 → 다시 부를 실험군). `R07:D3` 은 그 줄만, `R07` 은 두 실험군 다(검토 M1 — 고장 난 줄만 다시 부른다)."""
    out = {}
    for token in only:
        cid, _, arm = token.partition(":")
        if arm and arm not in ARMS:
            raise SystemExit(f"모르는 실험군: {token}")
        out.setdefault(cid, set()).update({arm} if arm else set(ARMS))
    return out


def client_for(intended, base, token, transport, received):
    """`run_diagnosis` 가 받는 `client(answer_context) -> search`. 함수가 지은 답변 컨텍스트와 질의를 [received] 에 적고, 보내는 것은
    실험군의 글이다. 다른 인자는 권고 측정기(`eval.recommend.client_for`)와 같다."""

    def client(context):
        seen = {"context": context, "query": None}
        received.append(seen)
        search = nexus_client(base, token=token, tenant=rec.TENANT, transport=transport, exclude_doc_types=rec.EXCLUDE,
                              identifier_channel=True, answer_context=intended["context"])

        def send(query):
            seen["query"] = query
            return search(intended["query"])

        return send

    return client


def environment(name, base, doc):
    git = ft.git
    return {
        "at": ft._now(), "pass": name, "arms": list(ARMS), "maxAttempts": rec.MAX_ATTEMPTS,
        "narratorCommit": git("rev-parse", "HEAD"),
        "cases": {"blob": git("rev-parse", "HEAD:eval/goldenset-recommend.json"), "scoringHash": rs.scoring_hash(doc)},
        "requests": git("rev-parse", "HEAD:eval/recommend-requests"),
        "measurers": {path: git("rev-parse", f"HEAD:{path}") for path in
                      ("eval/gen_diag_trial.py", "eval/gen_trial.py", "eval/ask_trial.py", "eval/query_trial.py",
                       "eval/recommend.py", "eval/recommend_score.py", "diagnose/core.py", "diagnose/context.py",
                       "diagnose/judge.py", "explainer/client.py", "composer/query.py", "receiver/pipeline.py")},
        "nexus": base, "token": "NEXUS_TOKEN", "tenant": rec.TENANT, "topK": ANSWER_TOP_K, "identifierChannel": True,
        "excludeDocTypes": list(rec.EXCLUDE), "khalaBefore": ft.khala_identity(),
    }


def row_of(row, arm, intended, sent, received, at=None, echo=None):
    """기록의 줄 하나 — 권고 측정기의 줄에 실험군 · 계획한 글과 보낸 글 · 함수가 지은 글 · 되울림을 더한다(설계서 §1)."""
    last = sent[-1] if sent else {}
    return dict(
        row, arm=arm, at=at,
        planQuerySha256=sha(intended["query"]), planContextSha256=sha(intended["context"]),
        sentQuerySha256=sha(last.get("query")), sentContextSha256=sha(last.get("answer_context")),
        sentQuery=last.get("query"), sentContext=last.get("answer_context"),
        sentQueryLen=len(last.get("query") or ""), sentContextLen=len(last.get("answer_context") or ""),
        sentKeys=sorted(last), sends=len(sent),
        receivedQuerySha256=sorted({sha(r["query"]) for r in received}, key=str),
        receivedContextSha256=sorted({sha(r["context"]) for r in received}, key=str),
        echo=echo,
    )


def run_round(name, out, token, base, transport=http_transport, clock=ft._now, only=None, doc=None, commit=None):
    """한 바퀴 — 웜업 한 번 뒤 사례마다 두 실험군을 잇달아 진단하고 줄마다 기록을 다시 쓴다(`complete` 는 실행 끝에서만 참).
    401 · 403 · 422 나 `quota` · `auth`, 잇단 실패 둘이면 곧바로 멈춘다.

    `only` 는 실행 끝에 다시 부를 줄이다(`targets`, 차례 규칙은 그대로). 다시 부르기는 권고 측정기의 실행 끝 다시 돌기처럼 줄마다 한 번
    (`rerun` 표시, 시도 예산 1)이고, 잇단 실패로는 멈추지 않는다 — 다시 불러도 실패면 그대로 센다(검토 M2)."""
    doc = doc or rs.load_cases()
    wanted = targets(only) if only is not None else None
    work = [item for item in plan(doc) if wanted is None or item["prep"]["case"]["id"] in wanted]
    if wanted is not None and {item["prep"]["case"]["id"] for item in work} != set(wanted):
        raise SystemExit(f"모르는 사례가 있다: {sorted(set(wanted) - {item['prep']['case']['id'] for item in work})}")
    env = environment(name, base, doc)
    env["only"] = sorted(only) if only is not None else None
    commit = commit or ft.git("rev-parse", "--short", "HEAD")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    try:
        status, response = transport("POST", base.rstrip("/") + "/search", headers, dict(ft.WARM))
    except ValueError:
        status, response = "broken", {}
    why = ft.stop_reason("예열", status, response) or (None if status == 200 else f"멈춘다 — 예열이 {status}")
    if why:
        raise SystemExit(why)
    rows, straight = [], 0
    for item in work:
        prep = item["prep"]
        cid = prep["case"]["id"]
        for arm in (a for a in item["order"] if wanted is None or a in wanted[cid]):
            sent, statuses, echoes, received = [], [], [], []

            def capture(method, url, headers, body):
                sent.append(body)
                try:
                    answer = transport(method, url, headers, body)
                except ValueError as broken:  # JSON 아닌 응답(프록시 502 같은 것) — 전송 실패로 받는다
                    answer = ("broken", {"detail": f"{type(broken).__name__}: {broken}"[:300]})
                statuses.append(answer[0])
                echoes.append(gt.echo_of(answer[1]))
                return answer

            at_ = clock()
            row = rec.run_case(prep, client_for(item[arm], base, token, capture, received), commit,
                               rerun=only is not None, budget=1 if only is not None else rec.MAX_ATTEMPTS)
            stopped = [s for s in statuses if s in gt.STOP]
            if stopped:
                raise SystemExit(f"{cid} {arm}: 상태 {stopped[0]} — 곧바로 멈춘다. 기록은 complete=false 로 남았다")
            rows.append(row_of(row, arm, item[arm], sent, received, at=at_, echo=echoes[-1] if echoes else None))
            rec.write(out, env, rows, complete=False)
            print(f'{name} {cid} {arm} {(row["response"] or {}).get("outcome") or "실패:" + str(row["failed"])} '
                  f'표지={row["rawPick"]!r} 시도={len(row["attempts"])}', flush=True)
            straight = straight + 1 if row["failed"] else 0
            why = rec.stop(row, straight if only is None else 0)
            if why:
                raise SystemExit(f"{cid} {arm}: {why}")
    env.update(endedAt=clock(), khalaAfter=ft.khala_identity())
    rec.write(out, env, rows, complete=True)


# ── 평가 도구 — 기록만 읽는다(설계서 §2 · §3) ──

def guards(d0, d3):
    """가드레일 지표 열(설계서 §2) — 이름 → 충족됐나. 꼴(후보 외 선택)과 안전(금지) · 실패 · 이유 없는 권고는 봐 주지 않는다."""
    return {
        "M1": d3["M1"][0] >= d0["M1"][0] - 1,
        "M2": d3["M2"][0] <= d0["M2"][0],
        "M4": d3["M4"][0] >= d0["M4"][0] - 1,
        "forbidden": d3["forbidden"][0] <= d0["forbidden"][0],
        "cards": d3["cards"][0] >= d0["cards"][0] - 1,
        "clean": d3["clean"][0] >= d0["clean"][0] - 1,
        "failed": d3["failed"] <= d0["failed"],
        "nullRationale": d3["nullRationale"][0] <= d0["nullRationale"][0],
        "citationPass": (d3["citationPass"] is not None and d0["citationPass"] is not None
                         and d3["citationPass"] >= d0["citationPass"] - 0.05),
        # 둘 다 받은 사례에서의 인용 — 검색이 더 준 몫을 빼고 모델이 답변 컨텍스트의 질문을 따랐나를 본다
        "citedWhenBoth": d3["citedWhenBoth"][0] >= d0["citedWhenBoth"][0] - 1,
    }


def _pending(row):
    """실행 끝에 한 번 다시 부를 줄인가(설계서 §3) — 검색 부분 실패이거나 다시 할 만한 생성 실패."""
    return rs.search_broken(row) or (row["response"] is None and row["failed"] in gt.RERUN_REASONS)


def _retrieved(row, case):
    docs = (row.get("diagnostics") or {}).get("evidenceDocs") or []
    return any(rs.names_doc(title, d) for title in docs for d in case["procedureDocs"])


def _treatment(cid, d0, d3):
    """처치가 걸렸나(설계서 §3) — 계획대로 보냈나, 함수가 지은 글이 운영 글인가, D3 의 글이 Q3 과 Q0 + 후보 자료인가, 되울림."""
    problems = []
    for r in (d0, d3):
        if r["sentQuerySha256"] != r["planQuerySha256"] or r["sentContextSha256"] != r["planContextSha256"]:
            problems.append(f"{cid} {r['arm']}: 보낸 글이 계획과 다르다")
        if sha(r["sentQuery"]) != r["sentQuerySha256"] or sha(r["sentContext"]) != r["sentContextSha256"]:
            problems.append(f"{cid} {r['arm']}: 적은 글이 보낸 글의 해시와 다르다")
        if r["receivedQuerySha256"] != [r["querySha256"]] or r["receivedContextSha256"] != [r["contextSha256"]]:
            problems.append(f"{cid} {r['arm']}: 진단 함수가 지은 글이 운영 글이 아니다")
        echo = r.get("echo")
        if echo is None:
            if r["response"] is not None:
                problems.append(f"{cid} {r['arm']}: 되울림이 없다")
        else:
            if echo.get("answer_context_len") != r["sentContextLen"]:
                problems.append(f"{cid} {r['arm']}: 자료 칸 길이 되울림 {echo.get('answer_context_len')} ≠ 보낸 {r['sentContextLen']}")
            # 받은 쪽에서 빼는 종류와 테넌트도 본다(검토 S4) — 차례는 안 본다
            if sorted(echo.get("excluded_doc_types") or []) != sorted(rec.EXCLUDE):
                problems.append(f"{cid} {r['arm']}: 빼는 종류 되울림 {echo.get('excluded_doc_types')}")
            if echo.get("searched_tenants") != [rec.TENANT]:
                problems.append(f"{cid} {r['arm']}: 테넌트 되울림 {echo.get('searched_tenants')}")
    if d0["sentKeys"] != d3["sentKeys"]:
        problems.append(f"{cid}: 두 실험군이 보낸 칸이 다르다 {d0['sentKeys']} · {d3['sentKeys']}")
    if d0["sentQuerySha256"] != d0["querySha256"] or d0["sentContextSha256"] != d0["contextSha256"]:
        problems.append(f"{cid}: D0 가 운영 글을 안 보냈다")
    if d3["sentQuery"] == d0["sentQuery"]:
        problems.append(f"{cid}: D3 의 질의가 안 바뀌었다")
    if d3["sentContext"] != (d0["sentQuery"] or "") + "\n\n" + (d0["sentContext"] or ""):
        problems.append(f"{cid}: D3 의 자료 칸이 Q0 와 후보 자료가 아니다")
    return problems


def metrics(doc, rows, paired):
    """실험군 하나 — 권고 측정의 채점에 이 실행의 셈 넷을 더한다(설계서 §2). **두 실험군이 다 답한 사례(`paired`)로만 센다**
    (검토 S3) — 한쪽만 실패한 사례가 그쪽 분모만 줄이지 않게. 실패는 실패 가드레일 지표가 전체에서 센다."""
    failed = sum(1 for r in rows if r["response"] is None)
    rows = [r for r in rows if r["id"] in paired]
    s = rs.score(doc, rows)
    a = s["all"]
    cases = {c["id"]: c for c in doc["cases"]}
    done = [r for r in rows if r["response"] is not None and not cases[r["id"]]["repeatOf"]]
    procedural = [r for r in done if cases[r["id"]]["procedureDocs"]]
    citations = [c for r in done for c in r["response"]["citations"]]
    return {
        "procedureCited": (sum(rs._grounded(r, cases[r["id"]]) for r in procedural), len(procedural)),
        "retrieved": (sum(_retrieved(r, cases[r["id"]]) for r in procedural), len(procedural)),
        "M1": a["M1"], "M2": a["M2"], "M4": a["M4marker"], "forbidden": a["forbiddenEffect"],
        "groundedEscalation": a["groundedEscalation"], "outcomes": a["outcomes"], "picks": a["M2byOutcome"],
        "cards": s["cards"], "nullRationale": s["nullRationale"],
        "failed": failed,
        "clean": (sum(rs.clean(r["response"]) for r in done), len(done)),
        "citationPass": (sum(c.get("verified") is True for c in citations) / len(citations)) if citations else None,
        "citations": len(citations),
        "uncitedSentences": sum(len(r["response"]["uncitedSentences"]) for r in done),
        # 꾸민 라벨 줄이 하나라도 있는 답 — 꾸밈 없는 줄은 `["plain"]` 이라 그것은 안 센다(실행 뒤에 고침, 서술 칸)
        "decorated": sum(any(kinds != ["plain"] for kinds in v.values()) for v in s["decorations"].values()),
        "weakEvidence": sum(bool((r["diagnostics"] or {}).get("weak_evidence")) for r in done),
    }


def tally(records, doc=None, reference=None):
    """기록 여럿 → 설계서 §2 · §3 의 수. 시각 차례로 합치고, 다시 부른 기록(`env.only`)의 줄은 앞에서 다시 부를 줄이던 것만 한 번
    덮는다. `reference` — 질문 제거 실행의 (G0 · G3, 사례) → 근거 문서 집합(적기만 한다)."""
    if isinstance(records, dict):
        records = [records]
    doc = doc or rs.load_cases()
    records = sorted(records, key=lambda r: r["env"].get("at") or "")
    cases = {c["id"]: c for c in doc["cases"] if not c["repeatOf"]}
    latest, reruns, bad_reruns = {}, collections.Counter(), []
    for record in records:
        is_rerun = record["env"].get("only") is not None
        for row in record["rows"]:
            key = (row["id"], row["arm"])
            if is_rerun:
                reruns[key] += 1
                if key not in latest or not _pending(latest[key]) or reruns[key] > 1:
                    bad_reruns.append(f"{row['id']} {row['arm']}")
            latest[key] = row
    out = {"pass": " + ".join(str(r["env"].get("pass")) for r in records), "rows": sum(len(r["rows"]) for r in records),
           "comparable": None, "badReruns": bad_reruns}
    # 전체 실행은 하나다 — 다시 부른 기록이 아닌 것이 둘이면 뒤 실행이 앞 실행을 조용히 덮는다(검토 S2)
    out["fullPasses"] = [str(r["env"].get("pass")) for r in records if r["env"].get("only") is None]
    out["incomplete"] = [str(r["env"].get("pass")) for r in records if r.get("complete") is not True]
    out["caseDrift"] = sorted({r["env"]["cases"]["scoringHash"] for r in records} - {rs.scoring_hash(doc)})
    out["missing"] = [f"{cid} {arm}" for cid in cases for arm in ARMS if (cid, arm) not in latest]
    answered = [row for row in latest.values() if row["response"] is not None]
    out["versions"] = sorted({json.dumps(rs.version_tuple(row)) for row in answered})
    # 모르는 버전 필드(`None`)는 같다고 못 한다 — 채점기의 대표 지표 규칙과 같다(검토 S1)
    out["unknownVersions"] = sorted({f"{row['id']} {row['arm']}" for row in answered if None in rs.version_tuple(row)})
    out["broken"] = sorted(f"{row['id']} {row['arm']}" for row in latest.values() if rs.search_broken(row))
    # 다시 부르지 않은 채 남은 생성 실패 — 다시 불렀는데도 실패면 그대로 센다(설계서 §3)
    out["pending"] = sorted(f"{key[0]} {key[1]}" for key, row in latest.items()
                            if _pending(row) and not rs.search_broken(row) and not reruns[key])
    out["failedAfterRerun"] = sorted(f"{key[0]} {key[1]}" for key, row in latest.items()
                                     if row["response"] is None and reruns[key])
    treatment = []
    for cid in cases:
        d0, d3 = latest.get((cid, "D0")), latest.get((cid, "D3"))
        if d0 and d3:
            treatment += _treatment(cid, d0, d3)
    out["treatment"] = treatment
    out["khalaChanged"] = len({json.dumps(r["env"].get(side), sort_keys=True)
                               for r in records for side in ("khalaBefore", "khalaAfter")}) > 1
    out["narratorChanged"] = len({r["env"].get("narratorCommit") for r in records}) > 1
    out["comparable"] = ("전체 판 기록이 하나가 아니다" if len(out["fullPasses"]) != 1
                         else "끝나지 않은 기록이 있다" if out["incomplete"]
                         else "사례 파일의 채점 칸이 다르다" if out["caseDrift"]
                         else "빠진 줄이 있다" if out["missing"]
                         else "판 칸이 한 벌이 아니다" if len(out["versions"]) > 1
                         else "모르는 판 칸이 있다" if out["unknownVersions"]
                         else "검색 고장이 남았다" if out["broken"] else "다시 부를 실패가 남았다" if out["pending"]
                         else "다시 부른 줄이 고장 · 실패가 아니었거나 두 번이다" if bad_reruns
                         else "처치가 계획과 다르다" if treatment
                         else "khala 코드 신원이 판 앞뒤로 다르다" if out["khalaChanged"]
                         else "narrator 커밋이 기록마다 다르다" if out["narratorChanged"] else None)
    if out["missing"]:
        return out
    paired = {cid for cid in cases if all(latest[(cid, arm)]["response"] is not None for arm in ARMS)}
    out["unpaired"] = sorted(set(cases) - paired)
    out["arms"] = {arm: metrics(doc, [latest[(cid, arm)] for cid in cases], paired) for arm in ARMS}

    def row(cid, arm):
        return latest[(cid, arm)]

    both = [cid for cid, case in cases.items() if case["procedureDocs"]
            and all(row(cid, arm)["response"] is not None and _retrieved(row(cid, arm), case) for arm in ARMS)]
    out["bothRetrieved"] = both  # 쌍인 사례만 — 둘 다 답했어야 둘 다 받았다고 본다
    for arm in ARMS:
        out["arms"][arm]["citedWhenBoth"] = (sum(rs._grounded(row(cid, arm), cases[cid]) for cid in both), len(both))
    out["items"] = [{"id": cid, **{arm: {
        "outcome": (row(cid, arm)["response"] or {}).get("outcome") or f"실패:{row(cid, arm)['failed']}",
        "pick": row(cid, arm)["rawPick"], "resolved": row(cid, arm)["resolved"],
        "clean": rs.clean(row(cid, arm)["response"]) if row(cid, arm)["response"] else None,
        "cards": len((row(cid, arm)["response"] or {}).get("card") or []),
        "procedureCited": rs._grounded(row(cid, arm), case) if case["procedureDocs"] and row(cid, arm)["response"] else None,
        "procedureRetrieved": _retrieved(row(cid, arm), case) if case["procedureDocs"] else None,
        "answerLen": len(row(cid, arm)["answer"] or ""), "attempts": len(row(cid, arm)["attempts"]),
        "elapsed": row(cid, arm)["attempts"][-1].get("elapsed")} for arm in ARMS}} for cid, case in cases.items()]
    out["reference"] = (sorted(f"{cid} {arm}" for cid in cases for arm in ARMS
                               if (REFERENCE_ARMS[arm], cid) in reference
                               and set((row(cid, arm)["diagnostics"] or {}).get("evidenceDocs") or [])
                               != reference[(REFERENCE_ARMS[arm], cid)])
                        if reference else None)
    out["guards"] = guards(out["arms"]["D0"], out["arms"]["D3"])
    out["primary"] = out["arms"]["D3"]["procedureCited"][0] >= out["arms"]["D0"]["procedureCited"][0]
    out["advance"] = out["comparable"] is None and all(out["guards"].values()) and out["primary"]
    return out


def report_lines(out):
    lines = [f"판 {out.get('pass')} · 줄 {out['rows']} · 판 칸 {out.get('versions')} · 검색 고장 {out.get('broken')}"
             + f" · 처치 {out.get('treatment') or '계획대로'} · khala 코드 신원 {'판 앞뒤로 다름' if out.get('khalaChanged') else '한 벌'}"]
    if "arms" not in out:
        return lines + [f"⚠ 비교 안 함 — {out['comparable']}", "다음 단계로 넘김 — 판정 안 함"]
    d0, d3 = out["arms"]["D0"], out["arms"]["D3"]
    lines.append(("성립" if out["comparable"] is None else f"⚠ 성립 안 함({out['comparable']})")
                 + f" — 주 변수 절차 문서 인용 D0 {d0['procedureCited'][0]}/{d0['procedureCited'][1]} · "
                 + f"D3 {d3['procedureCited'][0]}/{d3['procedureCited'][1]}")
    for arm in ARMS:
        lines.append(f"{arm} " + json.dumps(out["arms"][arm], ensure_ascii=False))
    lines.append("가드 " + json.dumps(out["guards"], ensure_ascii=False))
    lines.append(f"둘 다 받은 사례 {out['bothRetrieved']} · 앞 판과 근거 문서 집합이 다른 줄 {out['reference']}")
    for item in out["items"]:
        lines.append(f"  {item['id']:4} " + " · ".join(
            f"{arm} {item[arm]['outcome']} {item[arm]['pick']!r} 깨끗 {item[arm]['clean']} 카드 {item[arm]['cards']} "
            f"절차 {item[arm]['procedureCited']}/{item[arm]['procedureRetrieved']} {item[arm]['elapsed']}초" for arm in ARMS))
    lines.append("다음 단계로 넘김 — " + (("D3" if out["advance"] else "없음") if out["comparable"] is None else "판정 안 함"))
    return lines


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["run"] and len(args) >= 2 and "--out" in args[:-1]:
        name = args[1]
        out = pathlib.Path(args[args.index("--out") + 1])
        only = set(args[args.index("--only") + 1].split(",")) if "--only" in args[:-1] else None
        token = os.environ.get("NEXUS_TOKEN")
        if not token:
            raise SystemExit("Nexus 토큰이 없다. NEXUS_TOKEN 으로 준다")
        root = os.environ.get("KHALA_ROOT")
        if not root or ft.git("rev-parse", "HEAD", cwd=root) is None:
            raise SystemExit("KHALA_ROOT 가 khala 저장소를 가리켜야 한다(설계서 §3 코드 신원)")
        problems = rec.frozen_problems() + [f"{path}: 커밋되지 않았다" for path in COMMITTED
                                            if ft.git("rev-parse", f"HEAD:{path}") is None]
        if problems:
            raise SystemExit("고친 트리에서는 돌지 않는다 — 커밋하고 돈다\n" + "\n".join(problems))
        if not out.parent.is_dir():
            raise SystemExit(f"기록을 둘 폴더가 없다: {out.parent}")
        if out.exists():
            raise SystemExit(f"기록이 이미 있다: {out}")
        run_round(name, out, token, os.environ.get("NEXUS_URL", "http://localhost:8000"), only=only)
        return 0
    if args[:1] == ["tally"] and len(args) >= 2:
        records = [json.loads(pathlib.Path(path).read_text(encoding="utf-8")) for path in args[1:]]
        for line in report_lines(tally(records, reference=gt._reference())):
            print(line)
        return 0
    raise SystemExit(__doc__)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
