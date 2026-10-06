"""융합 실험 두 실행 — 설계서 `docs/superpowers/specs/2026-10-01-융합-처치-두-판.md`.

**실행.** 측정기가 이 커밋에서 지을 요청에 두 칸만 더해 근거만 받는다(생성 없음). `KHALA_ROOT` 는 khala 저장소다 — 실행 앞뒤로 그
`HEAD` 와 `nexus/` 의 고친 파일 목록을 읽어 기록에 적는다(설계서 §3 코드 신원, 쓰지 않는다)::

    KHALA_ROOT=<khala 저장소> python -m eval.fusion_trial run t0-1 T0 --out eval/fusion/t0-1.json

**평가 도구.** 기록 여럿을 읽는 순수 함수다(무늬는 이 프로그램이 펼친다)::

    python -m eval.fusion_trial tally "eval/fusion/*.json"

⚠ `eval/measure.py` 는 가져오지 않는다 — 가져오는 순간 실제 서비스 실행을 돌거나(토큰이 있으면) 멈춘다(없으면). 골든셋의 요청은 그 파일의
`CLIENTS` 와 같은 인자로 `nexus_client` 를 지어 보내고, 그 줄은 테스트가 글자로 박는다.
"""

import collections
import datetime
import glob
import hashlib
import io
import json
import math
import os
import pathlib
import statistics
import subprocess
import sys

from eval.recommend import EXCLUDE, client_for, frozen_problems, prepare
from eval.recommend_score import ROOT, load_cases, names_doc, scoring_hash
from eval.recommend_variance import PROCEDURE_TITLES, exact_interval
from eval.run import fixture_history, load, query_for
from eval.score import INCIDENT, SEARCH
from explainer.client import ANSWER_TOP_K, INCIDENT_EXCLUDED, nexus_client
from explainer.transport import http_transport

GOLDEN = ROOT / "eval" / "goldenset.json"
SPEC = "docs/superpowers/specs/2026-10-01-융합-처치-두-판.md"
#: 첫 실행 전에 커밋되어 있어야 하는 것(설계서 §5).
COMMITTED = (SPEC, "eval/fusion_trial.py", "tests/test_eval_fusion_trial.py")
#: 모든 실행에 더하는 칸과 실험군마다 더하는 칸. T0 는 F1 키를 안 보낸다(khala 요청 문서 36, 이 계층의 「안 물었으면 안 보낸다」).
FLAGS = {"evidence_only": True}
ARMS = {"T0": {}, "F1": {"fusion_doc_agreement": True}}
#: 다시 해도 같은 상태 — 실행 전체를 곧바로 멈춘다(설계서 §3).
STOP = (401, 403, 422)
#: 실행마다 앞의 웜업. 기록하지 않는다.
WARM = {"query": "예열", "tenant": "picasso", "top_k": 1}
VERSION_KEYS = ("prompt_version", "corpus_version", "search_fingerprint")
#: F1 이 안 건드리는 칸 — 모든 실행에서 검색마다 같아야 한다(설계서 §3).
INVARIANT_KEYS = ("identifier_channel", "top_distance", "top_bm25", "weak_evidence", "excluded_doc_types")
#: khala 의 문서당 상한(`diversity_per_doc_cap`). 다양화가 모자라면 상한을 넘겨 채우므로 단단한 천장은 아니다.
CAP = 5


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


def items(doc=None, golden=GOLDEN):
    """잴 항목 — 권고 사례(반복 뺌)와 설명 골든셋, 각 파일의 차례로(설계서 §1)."""
    doc = doc or load_cases()
    out = []
    for prep in prepare(doc):
        case = prep["case"]
        if case.get("repeatOf"):
            continue
        out.append({"id": case["id"], "set": "recommend", "kind": "recommend", "query": prep["query"],
                    "context": prep["context"], "expected": list(case["procedureDocs"])})
    history = fixture_history()
    for entry in load(str(golden)):
        out.append({"id": entry["id"], "set": "golden", "kind": entry["kind"], "query": query_for(entry, prior=history),
                    "context": None, "expected": [entry["procedure"]["doc"]] if entry.get("procedure") else []})
    return out


def sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def search_key(body):
    """같은 검색인가(설계서 §2) — 근거만 받는 요청은 답변 컨텍스트를 안 쓰고, picasso 에는 `case` 종류가 없다. 두 칸을 뺀 본문의 해시."""
    plain = {key: value for key, value in body.items() if key != "answer_context"}
    if "exclude_doc_types" in plain:
        plain["exclude_doc_types"] = sorted(t for t in plain["exclude_doc_types"] if t != "case")
    return sha(plain)[:16]


def call(item, transport, base, token):
    """측정기의 길로 본문을 지어 한 번 보낸다. `(측정기 본문, 상태, 응답)` — 측정기 본문은 `transport` 가 칸을 더하기 전의 것이다.
    응답이 JSON 이 아니면 상태 `broken` 으로 돌려준다(실행의 실패로 적는다)."""
    seen = {}

    def capture(method, url, headers, body):
        seen["body"] = body
        try:
            return transport(method, url, headers, body)
        except ValueError as broken:
            return "broken", {"detail": f"{type(broken).__name__}: {broken}"[:300]}

    if item["set"] == "recommend":
        status, response = client_for(base, token, transport=capture)(item["context"])(item["query"])
    else:
        # `eval/measure.py` 의 `CLIENTS` 와 같은 인자 — 사건 · 조치 탐색 기록은 설계 문서를 빼고 질의 줄은 안 뺀다, 식별자 채널은 T2(켬)
        exclude = INCIDENT_EXCLUDED if item["kind"] in (INCIDENT, SEARCH) else ()
        status, response = nexus_client(base, token=token, tenant="picasso", transport=capture, exclude_doc_types=exclude,
                                        identifier_channel=True)(item["query"])
    return seen["body"], status, response


def row_of(item, body, status, response, at=None):
    """기록의 줄 하나(설계서 §5). `at` 은 보낸 시각이다 — khala 기록과 줄을 맞출 때 쓴다."""
    row = {"id": item["id"], "set": item["set"], "expected": item["expected"], "key": search_key(body),
           "bodySha256": sha(body), "sentExclude": list(body.get("exclude_doc_types") or []), "at": at, "status": status,
           "data": None}
    data = response.get("data") if isinstance(response, dict) and response.get("success") else None
    if status == 200 and isinstance(data, dict):
        snippets = data.get("evidence_snippets") or []
        row["data"] = {
            **{key: data.get(key) for key in ("evidence_only", "fusion_doc_agreement", "identifier_channel_asked",
                                              "answer_context_len", "searched_tenants", "degraded", "enrichment_failed")},
            **{key: data.get(key) for key in VERSION_KEYS + INVARIANT_KEYS},
            "timing": dict(data.get("timing_ms") or {}),
            "rankKey": all("rank" in s for s in snippets),
            "snippets": [{"chunk_rid": s.get("chunk_rid"), "doc_title": s.get("doc_title"),
                          "section_path": s.get("section_path"), "rank": s.get("rank"), "score": s.get("score"),
                          "chars": len(s.get("text") or "")} for s in snippets],
        }
    elif isinstance(response, dict):
        row["error"] = response.get("detail") or response.get("error")
    else:
        row["error"] = str(response)[:300]
    return row


def stop_reason(item_id, status, response):
    """곧바로 멈출 까닭(설계서 §3) — 401 · 403 · 422 는 다시 해도 같다. 없으면 `None`."""
    if status in STOP:
        detail = response.get("detail") if isinstance(response, dict) else response
        return f"멈춘다 — {item_id} 에 {status}: {str(detail)[:300]}"
    return None


def git(*args, cwd=ROOT):
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else None


def khala_identity():
    """khala 의 `HEAD` 와 `nexus/` 의 고친 파일 목록(설계서 §3). ⚠ 읽기만 한다 — `--no-optional-locks` 로 그쪽 색인을 안 쓴다(쓰기
    경계). 경로는 적지 않는다(개인 경로)."""
    root = os.environ.get("KHALA_ROOT")
    if not root:
        return None
    return {"head": git("rev-parse", "HEAD", cwd=root),
            "dirty": git("--no-optional-locks", "status", "--porcelain", "--", "nexus/", cwd=root)}


def environment(name, arm, base):
    return {
        "at": _now(), "pass": name, "arm": arm, "flags": {**FLAGS, **ARMS[arm]},
        "narratorCommit": git("rev-parse", "HEAD"),
        "cases": {"blob": git("rev-parse", "HEAD:eval/goldenset-recommend.json"), "scoringHash": scoring_hash(load_cases())},
        "golden": git("rev-parse", "HEAD:eval/goldenset.json"),
        "fixtures": git("rev-parse", "HEAD:tests/fixtures/picasso"),
        "measurers": {path: git("rev-parse", f"HEAD:{path}") for path in
                      ("eval/recommend.py", "eval/measure.py", "eval/run.py", "explainer/client.py", "eval/fusion_trial.py")},
        "nexus": base, "token": "NEXUS_TOKEN", "topK": ANSWER_TOP_K, "identifierChannel": True,
        "exclude": {"recommend": list(EXCLUDE), "incidentAndSearch": list(INCIDENT_EXCLUDED), "query": []},
        "khalaBefore": khala_identity(),
    }


def write(path, env, rows):
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump({"env": env, "rows": rows}, handle, ensure_ascii=False, indent=1)


def run_pass(name, arm, out, token, base, transport=http_transport, clock=_now):
    """실행 하나(설계서 §1) — 웜업 한 번 뒤 항목을 차례로 부르고 기록을 쓴다. 401 · 403 · 422 면 곧바로 멈추고 기록을 안 쓴다."""
    work = items()  # 사례 파일이 깨졌으면 부르기 전에 멈춘다
    env = environment(name, arm, base)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    try:
        status, response = transport("POST", base.rstrip("/") + "/search", headers, dict(WARM))
    except ValueError:
        status, response = "broken", {}
    why = stop_reason("예열", status, response)
    if why:
        raise SystemExit(why)

    def flagged(method, url, headers, body):
        return transport(method, url, headers, {**body, **FLAGS, **ARMS[arm]})

    rows = []
    for item in work:
        at = clock()
        body, status, response = call(item, flagged, base, token)
        why = stop_reason(item["id"], status, response)
        if why:
            raise SystemExit(why)
        rows.append(row_of(item, body, status, response, at=at))
        print(f"{name} {item['id']} {status}", flush=True)
    env.update(endedAt=clock(), khalaAfter=khala_identity())
    write(out, env, rows)


# ── 평가 도구 — 기록만 읽는다(설계서 §2 · §3) ──

def _contiguous(snippets):
    ranks = sorted(s["rank"] for s in snippets if s["rank"] is not None)
    return ranks == list(range(1, len(ranks) + 1))


def versions_of(data):
    return tuple(data[key] for key in VERSION_KEYS)


def validity(record, reference):
    """실행 하나의 유효성(설계서 §3) — 걸린 것의 목록. 비면 유효하다. `reference` 는 버전 필드의 기준 한 벌이다."""
    want_f1 = record["env"]["arm"] == "F1"
    problems = []
    for row in record["rows"]:
        data = row.get("data")
        if row["status"] != 200 or data is None:
            problems.append(f"{row['id']}: 상태 {row['status']}")
            continue
        checks = {
            "evidence_only": data["evidence_only"] is True,
            "fusion_doc_agreement": data["fusion_doc_agreement"] is want_f1,
            "identifier_channel_asked": data["identifier_channel_asked"] is True,
            "excluded_doc_types": data["excluded_doc_types"] == row["sentExclude"],
            "answer_context_len": data["answer_context_len"] == 0,
            "searched_tenants": data["searched_tenants"] == ["picasso"],
            "degraded": data["degraded"] == [],
            "enrichment_failed": data["enrichment_failed"] == [],
            "rank": data["rankKey"] and _contiguous(data["snippets"]),
            "versions": versions_of(data) == reference and all(reference),
        }
        problems += [f"{row['id']}: {name}" for name, ok in checks.items() if not ok]
    return problems


def top(row):
    """상위 20 의 모양 — 순위마다 `chunk_rid` 와 `score`(설계서 §3 결정론)."""
    ranked = sorted((s for s in row["data"]["snippets"] if s["rank"] is not None), key=lambda s: s["rank"])
    return tuple((s["rank"], s["chunk_rid"], s["score"]) for s in ranked)


def order(row):
    """상위 20 의 청크 차례만 — khala 회귀 탐침의 「출력이 갈린 질의」와 견줄 수 있다(점수는 F1 이 모든 자리에 더한다)."""
    return tuple(rid for _, rid, _ in top(row))


def searches(record):
    """실행 하나의 검색 — 요청 해시마다 구성원 줄, 첫 등장 차례."""
    out = {}
    for row in record["rows"]:
        out.setdefault(row["key"], []).append(row)
    return out


def expected(rows):
    """무리의 기대 문서 — 구성원 기대의 합집합(설계서 §2)."""
    return list(dict.fromkeys(doc for row in rows for doc in row["expected"]))


def has(row, doc, ranked=True):
    """그 문서를 대는 청크가 있나 — `ranked` 면 상위 20(순위가 있는 청크)만 본다."""
    return any(names_doc(s["doc_title"], doc) and (s["rank"] is not None or not ranked) for s in row["data"]["snippets"])


def sign_test(b, c):
    """양쪽 정확 부호 검정(이항 1/2)."""
    n = b + c
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n)


def concentration(row):
    """한 문서 쏠림(설계서 §2) — 상위 20 · 순위 10 이하 · 상한 채운 문서 수 · 묶음 전체."""
    snippets = row["data"]["snippets"]
    ranked = [s for s in snippets if s["rank"] is not None]

    def counts(group):
        out = collections.Counter(s["doc_title"] for s in group)
        return out

    def share(group):
        return max(counts(group).values()) / len(group) if group else None

    return {"top20": share(ranked), "top10": share([s for s in ranked if s["rank"] <= 10]),
            "capped": sum(n >= CAP for n in counts(ranked).values()), "bundle": share(snippets)}


def wrong(row, docs):
    """상위 20 에 든 절차 문서 가운데 기대가 아닌 서로 다른 문서의 수(설계서 §2)."""
    return sum(1 for title in PROCEDURE_TITLES if title not in docs and has(row, title))


def _mean(values):
    values = [v for v in values if v is not None]
    return round(statistics.mean(values), 3) if values else None


def _layout(record):
    return [(row["id"], row["key"], row["bodySha256"]) for row in record["rows"]]


def tally(records, reference=None):
    """기록 여럿 → 설계서 §2 · §3 의 수. 실행마다 유효성을 먼저 보고 무효 실행은 안 센다.

    `reference` — 권고 변동 기록의 같은 입력 `{id: {"size": 묶음 크기, "docs": 근거 문서 목록}}`(설계서 §3 「T0 와 오늘
    측정기」). 없으면 안 견준다."""
    records = sorted(records, key=lambda r: r["env"]["at"])
    tuples = collections.Counter(versions_of(row["data"]) for r in records for row in r["rows"] if row.get("data"))
    if not tuples:
        return {"passes": [], "versions": None, "comparable": "기록에 응답이 하나도 없다"}
    common = tuples.most_common(1)[0][0]
    passes = [{"name": r["env"]["pass"], "arm": r["env"]["arm"], "problems": validity(r, common), "record": r} for r in records]
    out = {"passes": [{"name": p["name"], "arm": p["arm"], "valid": not p["problems"], "problems": p["problems"][:10]}
                      for p in passes],
           "versions": list(common), "drift": [], "invariant": [], "moved": [], "movedOrder": []}
    names = [p["name"] for p in passes]
    valid = {arm: [p for p in passes if p["arm"] == arm and not p["problems"]] for arm in ARMS}
    if len(set(names)) != len(names):
        out["comparable"] = "같은 이름의 판이 둘 이상이다"
        return out
    if not valid["T0"] or not valid["F1"]:
        out["comparable"] = "실험군마다 성립한 판이 하나 이상 있어야 한다"
        return out
    every = valid["T0"] + valid["F1"]
    if len({json.dumps(_layout(p["record"])) for p in every}) > 1 or len({p["record"]["env"].get("narratorCommit")
                                                                          for p in every}) > 1:
        out["comparable"] = "성립한 판들의 항목 · 본문 · narrator 커밋이 서로 다르다"
        return out
    grouped = {p["name"]: searches(p["record"]) for p in every}
    t0, f1 = grouped[valid["T0"][0]["name"]], grouped[valid["F1"][0]["name"]]
    keys = list(t0)
    # 결정론 — 같은 실험군 실행끼리, 실행 안의 같은 무리끼리
    for arm in ARMS:
        base = grouped[valid[arm][0]["name"]]
        for p in valid[arm]:
            for key, rows in grouped[p["name"]].items():
                if len({top(row) for row in rows}) > 1 or top(rows[0]) != top(base[key][0]):
                    out["drift"].append({"pass": p["name"], "ids": [row["id"] for row in rows]})
    # 불변 칸 — 모든 실행에서 검색마다 같다
    out["invariant"] = [[row["id"] for row in t0[key]] for key in keys
                        if len({json.dumps([rows[0]["data"][k] for k in INVARIANT_KEYS], sort_keys=True)
                                for rows in (grouped[name][key] for name in grouped)}) > 1]
    out["moved"] = [[row["id"] for row in t0[key]] for key in keys if top(t0[key][0]) != top(f1[key][0])]
    out["movedOrder"] = [[row["id"] for row in t0[key]] for key in keys if order(t0[key][0]) != order(f1[key][0])]
    out["searches"] = len(keys)
    if not out["moved"]:
        out["comparable"] = "양성 대조 — F1 판의 상위 20 이 T0 와 같다(처치가 안 걸렸다)"
        return out
    out["comparable"] = ("결정론이 깨졌다" if out["drift"] else "불변 칸이 갈렸다" if out["invariant"] else None)
    labeled = [key for key in keys if expected(t0[key])]

    def ids(key):
        return [row["id"] for row in t0[key]]

    def any_in(group, key, ranked=True):
        return any(has(group[key][0], doc, ranked) for doc in expected(group[key]))

    def all_in(group, key):
        return all(has(group[key][0], doc) for doc in expected(group[key]))

    n = len(labeled)
    head = {arm: sum(any_in(g, key) for key in labeled) for arm, g in (("T0", t0), ("F1", f1))}
    only_t0 = [ids(key) for key in labeled if any_in(t0, key) and not any_in(f1, key)]
    only_f1 = [ids(key) for key in labeled if any_in(f1, key) and not any_in(t0, key)]
    pairs = [(ids(key), doc, has(t0[key][0], doc), has(f1[key][0], doc)) for key in labeled for doc in expected(t0[key])]
    out["headline"] = {
        "n": n, "T0": (head["T0"], n, exact_interval(head["T0"], n)), "F1": (head["F1"], n, exact_interval(head["F1"], n)),
        "onlyT0": only_t0, "onlyF1": only_f1,
        "p": sign_test(len(only_t0), len(only_f1)) if len(only_t0) + len(only_f1) >= 6 else None,
    }
    sets = {}
    for name in ("recommend", "golden"):
        inside = [key for key in labeled if any(row["set"] == name for row in t0[key])]
        sets[name] = {arm: (sum(any_in(g, key) for key in inside), len(inside)) for arm, g in (("T0", t0), ("F1", f1))}
    out["described"] = {
        "pairs": {"T0": (sum(p[2] for p in pairs), len(pairs)), "F1": (sum(p[3] for p in pairs), len(pairs)),
                  "split": [{"ids": p[0], "doc": p[1], "T0": p[2], "F1": p[3]} for p in pairs if p[2] != p[3]]},
        "allIn": {arm: sum(all_in(g, key) for key in labeled) for arm, g in (("T0", t0), ("F1", f1))},
        "sets": sets,
        "bundle": {arm: sum(any_in(g, key, ranked=False) for key in labeled) for arm, g in (("T0", t0), ("F1", f1))},
    }
    out["secondary"] = _secondary(valid, grouped, keys, labeled)
    if reference:
        out["reference"] = [{"id": cid, "now": {"size": len(row["data"]["snippets"]),
                                                "docs": sorted({s["doc_title"] for s in row["data"]["snippets"]})},
                             "then": ref}
                            for cid, ref in reference.items()
                            for row in [next(r for rows in t0.values() for r in rows if r["id"] == cid)]
                            if len(row["data"]["snippets"]) != ref["size"]
                            or sorted({s["doc_title"] for s in row["data"]["snippets"]}) != sorted(ref["docs"])]
    return out


def _secondary(valid, grouped, keys, labeled):
    """2차 결과 변수(설계서 §2) — 실험군마다 실행 셋의 값과 그 평균. 지연은 F1 을 T0 실행 셋의 평균과 검색마다 견준다."""
    out = {}
    latency = {}
    for arm in ARMS:
        per_pass = []
        for p in valid[arm]:
            rep = grouped[p["name"]]
            rows = [rep[key][0] for key in keys]
            conc = [concentration(row) for row in rows]
            per_pass.append({
                "pass": p["name"],
                "ranked": _mean([sum(s["rank"] is not None for s in row["data"]["snippets"]) for row in rows]),
                "fills": _mean([sum(s["rank"] is None for s in row["data"]["snippets"]) for row in rows]),
                "chars": _mean([sum(s["chars"] for s in row["data"]["snippets"]) for row in rows]),
                "wrong": {"labeled": sum(wrong(rep[key][0], expected(rep[key])) for key in labeled),
                          "unlabeled": sum(wrong(rep[key][0], []) for key in keys if key not in labeled)},
                "concentration": {name: _mean([c[name] for c in conc]) for name in ("top20", "top10", "capped", "bundle")},
            })
        latency[arm] = {key: [grouped[p["name"]][key][0]["data"]["timing"].get("total_ms") for p in valid[arm]] for key in keys}
        flat = [v for values in latency[arm].values() for v in values if v is not None]
        spread = [max(v) - min(v) for v in latency[arm].values() if len(v) > 1 and None not in v]
        out[arm] = {"passes": per_pass,
                    "latency": {"median": statistics.median(flat) if flat else None,
                                "range": [min(flat), max(flat)] if flat else None,
                                "spread": statistics.median(spread) if spread else None, "passes": len(valid[arm])}}
    gaps = [statistics.mean(latency["F1"][key]) - statistics.mean(latency["T0"][key]) for key in keys
            if None not in latency["F1"][key] + latency["T0"][key]]
    out["F1"]["latency"]["vsT0Mean"] = statistics.median(gaps) if gaps else None
    return out


def _fraction(triple):
    k, n, interval = triple
    return f"{k}/{n}" + (f" [{interval[0]:.2f}, {interval[1]:.2f}]" if interval else "")


def report_lines(out):
    lines = ["판 " + " · ".join(f"{p['name']}({p['arm']}) {'성립' if p['valid'] else '무효 ' + str(p['problems'][:5])}"
                               for p in out["passes"]),
             "판 칸(가장 많은 벌) " + json.dumps(out["versions"], ensure_ascii=False),
             "결정론 " + (json.dumps(out["drift"], ensure_ascii=False) if out["drift"] else "어긋남 없음")
             + " · 불변 칸 " + (json.dumps(out["invariant"], ensure_ascii=False) if out["invariant"] else "어긋남 없음")]
    if "headline" not in out:
        return lines + [f"⚠ 비교 안 함 — {out.get('comparable')}"]
    head = out["headline"]
    lines += [
        ("머리 수치" if out["comparable"] is None else f"⚠ 머리 수치 아님({out['comparable']})")
        + f" — 기대 문서가 있는 검색 {head['n']} 에서 하나라도 상위 20: T0 {_fraction(head['T0'])} · F1 {_fraction(head['F1'])}",
        f"불일치 — T0 만 {head['onlyT0']} · F1 만 {head['onlyF1']} · "
        + (f"양쪽 정확 부호 검정 p={head['p']:.4f}" if head["p"] is not None else "불일치 6 미만 — p 값 안 냄"),
    ]
    d = out["described"]
    lines += [
        f"짝(서술) T0 {d['pairs']['T0'][0]}/{d['pairs']['T0'][1]} · F1 {d['pairs']['F1'][0]}/{d['pairs']['F1'][1]} · 갈린 짝 "
        + json.dumps(d["pairs"]["split"], ensure_ascii=False),
        f"다 들었나(서술) T0 {d['allIn']['T0']}/{head['n']} · F1 {d['allIn']['F1']}/{head['n']}",
        "집합마다(서술) " + json.dumps(d["sets"], ensure_ascii=False),
        f"묶음 쪽(곁에) T0 {d['bundle']['T0']}/{head['n']} · F1 {d['bundle']['F1']}/{head['n']}",
        f"양성 대조 — 상위 20(순위 · 조각 · 점수)이 갈린 검색 {len(out['moved'])}/{out['searches']} · 조각 차례만 갈린 검색 "
        f"{len(out['movedOrder'])}/{out['searches']}",
    ]
    for arm, s in out["secondary"].items():
        lines.append(f"{arm} 지연 " + json.dumps(s["latency"]) + " · 판마다 " + json.dumps(s["passes"], ensure_ascii=False))
    if "reference" in out:
        lines.append("T0 와 권고 변동 기록 " + (json.dumps(out["reference"], ensure_ascii=False) if out["reference"] else "같다"))
    return lines


def _reference():
    """권고 변동 첫 실행의 R01 · R03 · R06 — 묶음 크기와 근거 문서(설계서 §3). 기록이 없으면 `None`."""
    path = ROOT / "eval" / "variance" / "var-01.json"
    if not path.exists():
        return None
    rows = json.loads(path.read_text(encoding="utf-8"))["rows"]
    return {row["id"]: {"size": row["diagnostics"]["evidence"], "docs": row["diagnostics"]["evidenceDocs"]}
            for row in rows if row["id"] in ("R01", "R03", "R06")}


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["run"] and len(args) >= 3 and "--out" in args[:-1]:
        name, arm = args[1], args[2].upper()
        out = pathlib.Path(args[args.index("--out") + 1])
        if arm not in ARMS:
            raise SystemExit(f"실험군은 {sorted(ARMS)} 가운데 하나다: {arm}")
        if not name.lower().startswith(arm.lower() + "-"):
            raise SystemExit(f"판 이름은 실험군으로 시작한다(t0-1 · f1-1 …): {name} · {arm}")
        token = os.environ.get("NEXUS_TOKEN")
        if not token:
            raise SystemExit("Nexus 토큰이 없다. NEXUS_TOKEN 으로 준다")
        root = os.environ.get("KHALA_ROOT")
        if not root or git("rev-parse", "HEAD", cwd=root) is None:
            raise SystemExit("KHALA_ROOT 가 khala 저장소를 가리켜야 한다(설계서 §3 코드 신원)")
        problems = frozen_problems() + [f"{path}: 커밋되지 않았다" for path in COMMITTED
                                        if git("rev-parse", f"HEAD:{path}") is None]
        if problems:
            raise SystemExit("고친 트리에서는 돌지 않는다 — 커밋하고 돈다\n" + "\n".join(problems))
        if not out.parent.is_dir():
            raise SystemExit(f"기록을 둘 폴더가 없다: {out.parent}")
        if out.exists():
            raise SystemExit(f"기록이 이미 있다: {out} — 다시 돈 판은 이름 뒤에 r 을 붙인다")
        run_pass(name, arm, out, token, os.environ.get("NEXUS_URL", "http://localhost:8000"))
        return 0
    if args[:1] == ["tally"] and len(args) > 1:
        paths = sorted({path for pattern in args[1:] for path in (glob.glob(pattern) or [pattern])})
        records = [json.loads(pathlib.Path(p).read_text(encoding="utf-8")) for p in paths]
        for line in report_lines(tally(records, reference=_reference())):
            print(line)
        return 0
    raise SystemExit(__doc__)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
