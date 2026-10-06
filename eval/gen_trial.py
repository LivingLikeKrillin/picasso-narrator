"""생성 실행 — 설명 경로 한 바퀴. 설계서 `docs/superpowers/specs/2026-10-01-생성-판-설명-경로.md`.

**실행.** 골든셋 열다섯을 항목마다 두 실험군(G0 오늘 그대로 · G3 검색 텍스트는 Q3, 답변 컨텍스트는 Q0)으로 잇달아 묻는다::

    KHALA_ROOT=<khala 저장소> python -m eval.gen_trial run g-1 --out eval/gen/g-1.json
    KHALA_ROOT=<khala 저장소> python -m eval.gen_trial run g-1r --out eval/gen/g-1r.json --only G3,G7   # 고장 항목 다시

**평가 도구.** 기록만 읽는 순수 함수다 — 줄을 `Record` 로 되지어 골든셋 채점(`eval/score.py`)에 넘긴다. 기록 여럿은 시각 차례로 합치고 같은
(항목, 실험군)은 뒤의 줄이 이긴다::

    python -m eval.gen_trial tally eval/gen/g-1.json [eval/gen/g-1r.json]

요청은 운영 경로와 같은 `nexus_client` · `ask_and_record` 로 짓고 보낸다. `eval/measure.py` 와 앞 실행들의 실행기는 고치지 않는다.
"""

import collections
import hashlib
import json
import os
import pathlib
import sys

from eval import ask_trial as at
from eval import fusion_trial as ft
from eval import query_trial as qt
from eval.recommend import frozen_problems
from eval.run import ABORT_AFTER, fixture_history, load, load_truth, query_for, straight_failures
from eval.score import INCIDENT, QUERY, SEARCH, cites_doc, score
from explainer.client import ANSWER_TOP_K, INCIDENT_EXCLUDED, nexus_client
from explainer.transport import http_transport
from receiver.pipeline import ask_and_record
from recorder.card import parse_card
from recorder.outcome import TRANSIENT, Outcome
from recorder.record import Record

SPEC = "docs/superpowers/specs/2026-10-01-생성-판-설명-경로.md"
COMMITTED = (SPEC, "eval/gen_trial.py", "tests/test_eval_gen_trial.py", "eval/ask_trial.py", "eval/query_trial.py",
             "eval/score.py", "eval/run.py")
ARMS = ("G0", "G3")
#: `ask_and_record` 의 시도 한도 — `eval/measure.py` 와 같다.
LIMIT = 2
GOLDEN = "eval/goldenset.json"
TRUTH = "tests/fixtures/picasso/ground-truth.jsonl"
#: 곧바로 멈추는 상태 — 내가 잘못 보냈거나(422) 식별 정보가 안 맞는다(401 · 403). 재시도로 덮이면 실행이 실패로 채워진다.
STOP = (401, 403, 422)
#: 실행 끝에 그 항목의 두 실험군을 한 번 더 부를 생성 실패의 사유(설계서 §3) — 다시 할 만한 것과 전송이 끊긴 것.
RERUN_REASONS = frozenset(TRANSIENT | {"unreachable"})


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text is not None else None


def plan(golden=GOLDEN):
    """항목마다 두 실험군의 (질의, 답변 컨텍스트)와 부르는 차례(설계서 §1).

    G0 는 측정기의 질의(`query_for`)에 답변 컨텍스트 없음, G3 은 질문 제거의 Q3 에 답변 컨텍스트 = 그 항목의 Q0 글. 질의 줄은 질문도 사실도 없어
    G3 도 G0 와 같은 요청이다. 홀수째 항목은 G0 먼저, 짝수째는 G3 먼저."""
    entries = load(golden)
    built = qt.queries(golden=pathlib.Path(golden))
    history = fixture_history()
    out = []
    for i, entry in enumerate(entries):
        q0 = query_for(entry, prior=history)
        query = built[entry["id"]]
        three = at.texts(query)
        if three["Q0"] != q0:
            raise ValueError(f"{entry['id']}: 물음 떼기의 Q0 가 측정기의 질의와 다르다")
        out.append({"entry": entry, "order": ARMS if i % 2 == 0 else ARMS[::-1],
                    "G0": {"query": q0, "context": None},
                    "G3": {"query": three["Q3"], "context": None if isinstance(query, str) else q0}})
    return out


def environment(name, base):
    git = ft.git
    return {
        "at": ft._now(), "pass": name, "arms": list(ARMS), "limit": LIMIT,
        "narratorCommit": git("rev-parse", "HEAD"),
        "golden": git("rev-parse", f"HEAD:{GOLDEN}"),
        "fixtures": git("rev-parse", "HEAD:tests/fixtures/picasso"),
        "measurers": {path: git("rev-parse", f"HEAD:{path}") for path in
                      ("eval/gen_trial.py", "eval/ask_trial.py", "eval/query_trial.py", "eval/score.py", "eval/run.py",
                       "explainer/client.py", "composer/query.py", "receiver/pipeline.py", "recorder/record.py")},
        "nexus": base, "token": "NEXUS_TOKEN", "topK": ANSWER_TOP_K, "identifierChannel": True,
        "exclude": {"incidentAndSearch": list(INCIDENT_EXCLUDED), "query": []},
        "khalaBefore": ft.khala_identity(),
    }


def row_of(entry, arm, intended, sent, record, at=None, echo=None):
    """기록의 줄 하나 — 채점이 기록만으로 다시 돌게 결과 · 답 · 인용 · 계측을 다 담는다. `sent` 는 시도마다 보낸 본문이고 `echo` 는
    마지막 응답이 되울린 칸(답변 컨텍스트 길이 · 빼는 종류 · 테넌트 · 경로 · 상위 20 의 (순위, 청크))이다."""
    last = sent[-1] if sent else {}
    return {
        "id": entry["id"], "kind": entry["kind"], "arm": arm, "at": at,
        "planQuerySha256": sha(intended["query"]), "planContextSha256": sha(intended["context"]),
        "sentQuerySha256": sha(last.get("query")), "sentContextSha256": sha(last.get("answer_context")),
        "sentQueryLen": len(last.get("query") or ""), "sentContextLen": len(last.get("answer_context") or ""),
        "sentKeys": sorted(last), "sends": len(sent),
        "outcome": record.outcome.value, "reason": record.reason, "attempts": record.attempts, "limit": record.limit,
        "elapsed": record.elapsed, "answer": record.answer, "citations": list(record.citations),
        "diagnostics": dict(record.diagnostics or {}), "card": parse_card(record.answer or ""), "echo": echo,
    }


def echo_of(body):
    """응답이 되울린 칸 — 받은 쪽에서 처치를 보는 재료(검토 S1). 성공 봉투가 아니면 `None`."""
    data = body.get("data") if isinstance(body, dict) and body.get("success") else None
    if not isinstance(data, dict):
        return None
    return {"answer_context_len": data.get("answer_context_len"), "excluded_doc_types": data.get("excluded_doc_types"),
            "searched_tenants": data.get("searched_tenants"), "route_used": data.get("route_used"),
            "top": [[s.get("rank"), s.get("chunk_rid")] for s in data.get("evidence_snippets") or []
                    if isinstance(s, dict) and s.get("rank") is not None]}


def run_round(name, out, token, base, transport=http_transport, clock=ft._now, golden=GOLDEN, only=None):
    """한 바퀴 — 웜업 한 번 뒤 항목마다 두 실험군을 잇달아 묻고 기록을 쓴다. 401 · 403 · 422 나 생성 실패 연속 둘이면 곧바로
    멈추고 기록을 안 쓴다. `only` 는 다시 부를 항목들이다(차례는 골든셋 차례의 규칙 그대로)."""
    work = [item for item in plan(golden) if only is None or item["entry"]["id"] in only]
    if only is not None and {item["entry"]["id"] for item in work} != set(only):
        raise SystemExit(f"모르는 항목이 있다: {sorted(set(only) - {item['entry']['id'] for item in work})}")
    env = environment(name, base)
    env["only"] = sorted(only) if only is not None else None
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    try:
        status, response = transport("POST", base.rstrip("/") + "/search", headers, dict(ft.WARM))
    except ValueError:
        status, response = "broken", {}
    why = ft.stop_reason("예열", status, response)
    if why:
        raise SystemExit(why)
    rows, straight = [], 0
    for item in work:
        entry = item["entry"]
        exclude = INCIDENT_EXCLUDED if entry["kind"] in (INCIDENT, SEARCH) else ()
        for arm in item["order"]:
            sent, statuses, echoes = [], [], []

            def capture(method, url, headers, body):
                sent.append(body)
                try:
                    answer = transport(method, url, headers, body)
                except ValueError as broken:  # JSON 아닌 응답(프록시 502 같은 것) — 전송 실패로 받는다
                    answer = ("broken", {"detail": f"{type(broken).__name__}: {broken}"[:300]})
                statuses.append(answer[0])
                echoes.append(echo_of(answer[1]))
                return answer

            search = nexus_client(base, token, "picasso", capture, exclude_doc_types=exclude, identifier_channel=True,
                                  answer_context=item[arm]["context"])
            at_ = clock()
            record = ask_and_record(("golden", entry["id"], arm), item[arm]["query"], search, LIMIT)
            stopped = [s for s in statuses if s in STOP]
            if stopped:
                raise SystemExit(f"{entry['id']} {arm}: 상태 {stopped[0]} — 곧바로 멈춘다(기록 안 씀)")
            rows.append(row_of(entry, arm, item[arm], sent, record, at=at_, echo=echoes[-1] if echoes else None))
            print(f"{name} {entry['id']} {arm} {record.outcome.value} {record.elapsed}s", flush=True)
            straight = straight_failures(straight, record.outcome)
            if straight >= ABORT_AFTER:
                raise SystemExit(f"생성 실패가 {ABORT_AFTER} 건 연속이다(마지막 {entry['id']} {arm}) — 판을 접는다(기록 안 씀). "
                                 f"사유 {record.reason!r}")
    env.update(endedAt=clock(), khalaAfter=ft.khala_identity())
    ft.write(out, env, rows)


# ── 평가 도구 — 기록만 읽는다(설계서 §2 · §3) ──

def to_record(row):
    """기록의 줄 → 채점이 받는 `Record`. 채점이 읽는 칸(결과 · 답 · 인용 · 계측)을 그대로 옮긴다."""
    return Record(key=("golden", row["id"], row["arm"]), outcome=Outcome(row["outcome"]), answer=row["answer"] or "",
                  citations=list(row["citations"] or []), attempts=row["attempts"], limit=row["limit"],
                  reason=row["reason"] or "", elapsed=row["elapsed"], diagnostics=dict(row["diagnostics"] or {}))


def _versions(row):
    d = row["diagnostics"] or {}
    return ((d.get("usage") or {}).get("model"), d.get("prompt_version"), d.get("corpus_version"), d.get("search_fingerprint"))


def _k(ratio, n):
    return round(ratio * n) if ratio is not None else 0


def metrics(entries, records, truth=None):
    """실험군 하나의 골든셋 지표(`eval/score.py`) — 비율과 개수를 함께."""
    s = score(entries, records, truth=truth)
    return {
        "procedureDoc": (_k(s.procedure_doc_cited, s.counted_procedures), s.counted_procedures),
        "procedureSection": (_k(s.procedure_section_cited, s.counted_procedures), s.counted_procedures),
        # 검색이 줬나 — 근거 문서 칸이 있는 사건 가운데 기대 절차가 근거에 든 수와 그 몫(분모는 채점이 안 내보낸다)
        "retrieved": (s.counted_retrieved, s.procedure_doc_retrieved),
        "citedWhenRetrieved": (_k(s.procedure_cited_when_retrieved, s.counted_retrieved), s.counted_retrieved),
        "cards": s.cards_complete, "failed": s.failed_incidents, "uncited": s.uncited_incidents,
        "ungroundedNumbers": s.ungrounded_number_incidents, "citationPass": s.citation_pass,
        "citations": s.counted_citations,
        "contradictionFree": (_k(s.contradiction_free, s.counted_checked), s.counted_checked),
        "admitsNoEvidence": (_k(s.admits_no_evidence, s.counted_queries), s.counted_queries),
        "primaryCause": (_k(s.primary_cause_match, s.counted_incidents), s.counted_incidents),
        "searchProcedure": (_k(s.search_procedure_cited, s.counted_searches), s.counted_searches),
    }


def guards(g0, g3):
    """가드레일 지표 여덟(설계서 §2) — 이름 → 충족됐나. G3 이 G0 보다 이만큼 나빠지면 충족된 것이 아니다."""
    return {
        "cards": g3["cards"] >= g0["cards"] - 1,
        "failed": g3["failed"] <= g0["failed"],
        "uncited": g3["uncited"] <= g0["uncited"] + 1,
        "ungroundedNumbers": g3["ungroundedNumbers"] <= g0["ungroundedNumbers"] + 1,
        "citationPass": (g3["citationPass"] is not None and g0["citationPass"] is not None
                         and g3["citationPass"] >= g0["citationPass"] - 0.05),
        "contradictionFree": g3["contradictionFree"][0] >= g0["contradictionFree"][0] - 1,
        # 질의 줄은 두 실험군이 같은 요청이다 — 처치를 안 재고, 갈리면 생성의 흔들림이다(검토)
        "admitsNoEvidence": g3["admitsNoEvidence"] == g0["admitsNoEvidence"],
        # 둘 다 받은 사건에서의 인용 — 검색이 준 몫을 빼고 모델이 답변 컨텍스트의 질문을 따랐나를 본다(검토 M1)
        "citedWhenBoth": g3["citedWhenBoth"][0] >= g0["citedWhenBoth"][0] - 1,
    }


def _broken(row):
    d = row["diagnostics"] or {}
    return bool(d.get("degraded") or d.get("enrichment_failed"))


def _pending(row):
    """실행 끝에 한 번 다시 부를 줄인가(설계서 §3) — 검색 부분 실패이거나 다시 할 만한 생성 실패."""
    return _broken(row) or (row["outcome"] == Outcome.GENERATION_FAILED.value and row["reason"] in RERUN_REASONS)


def _echo_problems(e, row):
    """서버가 되울린 것으로 처치를 본다 — 답변 컨텍스트 길이가 보낸 것과 같은가(생성 실패 줄은 되울림이 없을 수 있다)."""
    echo = row.get("echo")
    if echo is None:
        return [] if row["outcome"] == Outcome.GENERATION_FAILED.value else [f"{e['id']} {row['arm']}: 되울림이 없다"]
    if echo.get("answer_context_len") != row["sentContextLen"]:
        return [f"{e['id']} {row['arm']}: 자료 칸 길이 되울림 {echo.get('answer_context_len')} ≠ 보낸 {row['sentContextLen']}"]
    return []


def tally(records, golden=GOLDEN, truth_path=TRUTH, reference=None):
    """기록 여럿 → 설계서 §2 · §3 의 수. 시각 차례로 합치고, 다시 부른 기록(`env.only`)의 줄은 앞에서 다시 부를 줄이던 것만 한 번
    덮는다(검토 S2). `reference` — 질문 제거 실행의 (실험군, 항목) → 근거 문서 집합(적기만 한다)."""
    if isinstance(records, dict):
        records = [records]
    records = sorted(records, key=lambda r: r["env"].get("at") or "")
    entries = load(golden)
    truth = load_truth(truth_path)
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
    out["missing"] = [f"{e['id']} {arm}" for e in entries for arm in ARMS if (e["id"], arm) not in latest]
    answered = [row for row in latest.values() if row["outcome"] != Outcome.GENERATION_FAILED.value]
    out["versions"] = sorted({json.dumps(_versions(row)) for row in answered})
    out["broken"] = sorted(f"{row['id']} {row['arm']}" for row in latest.values() if _broken(row))
    # 다시 부르지 않은 채 남은 생성 실패 — 다시 불렀는데도 실패면 그대로 센다(설계서 §3)
    out["pending"] = sorted(f"{key[0]} {key[1]}" for key, row in latest.items()
                            if _pending(row) and not _broken(row) and not reruns[key])
    out["failedAfterRerun"] = sorted(f"{key[0]} {key[1]}" for key, row in latest.items()
                                     if row["outcome"] == Outcome.GENERATION_FAILED.value and reruns[key])
    treatment = []
    for e in entries:
        g0, g3 = latest.get((e["id"], "G0")), latest.get((e["id"], "G3"))
        if not g0 or not g3:
            continue
        if any(row["sentQuerySha256"] != row["planQuerySha256"] or row["sentContextSha256"] != row["planContextSha256"]
               for row in (g0, g3)):
            treatment.append(f"{e['id']}: 보낸 글이 계획과 다르다")
        if g0["sentContextSha256"] is not None:
            treatment.append(f"{e['id']}: G0 에 자료 칸이 있다")
        if e["kind"] == QUERY:
            if g3["sentQuerySha256"] != g0["sentQuerySha256"] or g3["sentContextSha256"] is not None:
                treatment.append(f"{e['id']}: 질의 줄의 G3 이 G0 와 다른 요청이다")
        elif g3["sentContextSha256"] != g0["sentQuerySha256"] or g3["sentQuerySha256"] == g0["sentQuerySha256"]:
            treatment.append(f"{e['id']}: G3 의 자료 칸이 G0 의 질의가 아니거나 질의가 안 바뀌었다")
        treatment += _echo_problems(e, g0) + _echo_problems(e, g3)
    out["treatment"] = treatment
    out["khalaChanged"] = len({json.dumps(r["env"].get(side), sort_keys=True)
                               for r in records for side in ("khalaBefore", "khalaAfter")}) > 1
    out["narratorChanged"] = len({r["env"].get("narratorCommit") for r in records}) > 1
    out["comparable"] = ("빠진 줄이 있다" if out["missing"] else "판 칸이 한 벌이 아니다" if len(out["versions"]) > 1
                         else "검색 고장이 남았다" if out["broken"] else "다시 부를 실패가 남았다" if out["pending"]
                         else "다시 부른 줄이 고장 · 실패가 아니었거나 두 번이다" if bad_reruns
                         else "처치가 계획과 다르다" if treatment
                         else "khala 코드 신원이 판 앞뒤로 다르다" if out["khalaChanged"]
                         else "narrator 커밋이 기록마다 다르다" if out["narratorChanged"] else None)
    if out["missing"]:
        return out
    out["arms"] = {arm: metrics(entries, [to_record(latest[(e["id"], arm)]) for e in entries], truth=truth) for arm in ARMS}

    def row(e, arm):
        return latest[(e["id"], arm)]

    def retrieved(e, arm):
        return e["procedure"]["doc"] in ((row(e, arm)["diagnostics"] or {}).get("evidenceDocs") or [])

    procedural = [e for e in entries if e["kind"] == INCIDENT and e.get("procedure")]
    both = [e for e in procedural if all(retrieved(e, arm) for arm in ARMS)]
    out["bothRetrieved"] = [e["id"] for e in both]
    for arm in ARMS:
        rows = [row(e, arm) for e in entries if e["kind"] != QUERY]
        out["arms"][arm]["citedWhenBoth"] = (sum(cites_doc(row(e, arm)["answer"] or "", e["procedure"]["doc"]) for e in both),
                                             len(both))
        out["arms"][arm]["weakEvidence"] = sum(bool((r["diagnostics"] or {}).get("weak_evidence")) for r in rows)
        out["arms"][arm]["incidentNoEvidence"] = sum(r["outcome"] == Outcome.NO_EVIDENCE.value for r in rows)
    out["items"] = [{"id": e["id"], **{arm: {
        "outcome": row(e, arm)["outcome"], "cards": len(row(e, arm)["card"]),
        "procedureCited": cites_doc(row(e, arm)["answer"] or "", e["procedure"]["doc"]) if e.get("procedure") else None,
        "procedureRetrieved": retrieved(e, arm) if e.get("procedure") else None,
        "answerLen": len(row(e, arm)["answer"] or ""), "elapsed": row(e, arm)["elapsed"]} for arm in ARMS}} for e in entries]
    out["reference"] = (sorted(f"{e['id']} {arm}" for e in entries for arm in ARMS if (arm, e["id"]) in reference
                               and set((row(e, arm)["diagnostics"] or {}).get("evidenceDocs") or []) != reference[(arm, e["id"])])
                        if reference else None)
    out["guards"] = guards(out["arms"]["G0"], out["arms"]["G3"])
    out["primary"] = out["arms"]["G3"]["procedureDoc"][0] >= out["arms"]["G0"]["procedureDoc"][0]
    out["advance"] = out["comparable"] is None and all(out["guards"].values()) and out["primary"]
    return out


def _reference():
    """질문 제거 실행의 첫 실행(q0-1 · q3-1)에서 항목마다 근거 묶음의 문서 집합 — G0 ↔ Q0, G3 ↔ Q3. 기록이 없으면 `None`."""
    out = {}
    for arm, name in (("G0", "q0-1"), ("G3", "q3-1")):
        path = ft.ROOT / "eval" / "ask" / f"{name}.json"
        if not path.exists():
            return None
        for r in json.loads(path.read_text(encoding="utf-8"))["rows"]:
            if r.get("data"):
                out[(arm, r["id"])] = {s["doc_title"] for s in r["data"]["snippets"] if s.get("doc_title")}
    return out


def report_lines(out):
    lines = [f"판 {out.get('pass')} · 줄 {out['rows']} · 판 칸 {out.get('versions')} · 검색 고장 {out.get('broken')}"
             + f" · 처치 {out.get('treatment') or '계획대로'} · khala 코드 신원 {'판 앞뒤로 다름' if out.get('khalaChanged') else '한 벌'}"]
    if "arms" not in out:
        return lines + [f"⚠ 비교 안 함 — {out['comparable']}", "다음 단계로 넘김 — 판정 안 함"]
    g0, g3 = out["arms"]["G0"], out["arms"]["G3"]
    lines.append(("성립" if out["comparable"] is None else f"⚠ 성립 안 함({out['comparable']})")
                 + f" — 주 변수 절차 문서 인용 G0 {g0['procedureDoc'][0]}/{g0['procedureDoc'][1]} · "
                 + f"G3 {g3['procedureDoc'][0]}/{g3['procedureDoc'][1]}")
    for arm in ARMS:
        lines.append(f"{arm} " + json.dumps(out["arms"][arm], ensure_ascii=False))
    lines.append("가드 " + json.dumps(out["guards"], ensure_ascii=False))
    for item in out["items"]:
        lines.append(f"  {item['id']:4} " + " · ".join(
            f"{arm} {item[arm]['outcome']} 카드 {item[arm]['cards']} 답 {item[arm]['answerLen']}자 {item[arm]['elapsed']}초" for arm in ARMS))
    lines.append("다음 단계로 넘김 — " + (("G3" if out["advance"] else "없음") if out["comparable"] is None else "판정 안 함"))
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
        problems = frozen_problems() + [f"{path}: 커밋되지 않았다" for path in COMMITTED
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
        for line in report_lines(tally(records, reference=_reference())):
            print(line)
        return 0
    raise SystemExit(__doc__)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
