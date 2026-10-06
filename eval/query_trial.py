"""질의 축소 — 설계서 `docs/superpowers/specs/2026-10-01-질의-줄이기.md`.

**실행.** 측정기가 이 커밋에서 지을 요청의 질의만 실험군의 글로 바꿔 근거만 받는다(생성 없음, F1 칸 안 보냄)::

    KHALA_ROOT=<khala 저장소> python -m eval.query_trial run q1-1 Q1 --out eval/query/q1-1.json

**평가 도구.** 기록 여럿을 읽는 순수 함수다::

    python -m eval.query_trial tally "eval/query/*.json"

융합 실험 실행의 실행기(`eval/fusion_trial.py`)의 본문 짓기 · 줄 · 유효성 · 2차 결과 변수 함수를 가져다 쓰고 그 파일은 고치지 않는다.
"""

import collections
import glob
import json
import os
import pathlib
import re
import statistics
import sys

from composer.query import ASK, _flat, compose, compose_search
from eval import fusion_trial as ft
from eval.recommend import EXCLUDE, frozen_problems, prepare
from eval.recommend_score import load_cases, scoring_hash
from eval.recommend_variance import exact_interval
from eval.run import fixture_history, load
from eval.score import INCIDENT, SEARCH
from explainer.client import ANSWER_TOP_K, INCIDENT_EXCLUDED
from explainer.transport import http_transport
from receiver.history import count_recurrence

SPEC = "docs/superpowers/specs/2026-10-01-질의-줄이기.md"
COMMITTED = (SPEC, "eval/query_trial.py", "tests/test_eval_query_trial.py", "eval/fusion_trial.py")
ARMS = ("Q0", "Q1", "Q2")
FLAGS = {"evidence_only": True}
#: khala 식별자 채널의 정규식과 상한(`nexus/search/identifiers.py`)을 옮긴 것 — 응답의 `identifier_channel` 과 실행마다 견준다.
IDENTIFIER = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
MAX_IDENTIFIERS = 12


def tokens(text):
    """글에서 식별자 토큰 — 처음 나온 차례, 겹침 없음, 열둘까지(khala 와 같은 규칙)."""
    seen = {}
    for match in IDENTIFIER.finditer(text or ""):
        seen.setdefault(match.group(0), None)
    return list(seen)[:MAX_IDENTIFIERS]


def texts(query):
    """한 `Query` 의 세 글(설계서 §1). 질의 줄(글자 그대로의 질문)은 세 글이 같다.

    Q2 는 Q0 의 식별자 토큰 전부를 Q0 의 차례로 질문 바로 뒤에 두고 그 뒤에 스칼라 사실을 둔다 — 식별자 채널이 받는 글(토큰을
    이은 것)이 Q0 와 차례까지 같아진다. khala 의 식별자 채널은 그 글로 BM25 와 벡터를 다 돌고, 벡터는 차례를 본다(독립 검토)."""
    if isinstance(query, str):
        return {arm: query for arm in ARMS}
    q0 = query.text
    scalars = " ".join(f"{k}={_flat(v)}" for k, v in query.facts.items() if not isinstance(v, (dict, list)))
    q1 = query.lookup + ASK + scalars
    t0 = tokens(q0)
    q2 = q1 if tokens(q1) == t0 else query.lookup + ASK + " ".join(part for part in (" ".join(t0), scalars) if part)
    return {"Q0": q0, "Q1": q1, "Q2": q2}


def queries(doc=None, golden=ft.GOLDEN):
    """항목마다의 `Query`(질의 줄은 글자) — 운영 경로(`diagnose.core.query_text` · `eval.run.query_for`)와 같은 재료로 짓는다."""
    doc = doc or load_cases()
    out = {}
    for prep in prepare(doc):
        if prep["case"].get("repeatOf"):
            continue
        snapshot = prep["request"].snapshot
        incidents, searches = snapshot["incidents"], snapshot["searches"]
        out[prep["case"]["id"]] = (compose(incidents[0], searches[0] if searches else None) if incidents
                                   else compose_search(searches[0]))
    history = fixture_history()
    for entry in load(str(golden)):
        if entry["kind"] == INCIDENT:
            out[entry["id"]] = compose(entry["bundle"], entry.get("search"),
                                       recurrence=count_recurrence(entry["bundle"], history))
        elif entry["kind"] == SEARCH:
            out[entry["id"]] = compose_search(entry["search"])
        else:
            out[entry["id"]] = entry["query"]
    return out


def items(arm, doc=None):
    """잴 항목 — 융합 실험 실행의 항목에 실험군의 글을 넣는다. 권고 사례의 답변 컨텍스트는 그대로다(설계서 §1)."""
    base = ft.items(doc)
    built = queries(doc)
    return [dict(item, query=texts(built[item["id"]])[arm]) for item in base]


def environment(name, arm, base):
    git = ft.git
    return {
        "at": ft._now(), "pass": name, "arm": arm, "flags": dict(FLAGS),
        "narratorCommit": git("rev-parse", "HEAD"),
        "cases": {"blob": git("rev-parse", "HEAD:eval/goldenset-recommend.json"), "scoringHash": scoring_hash(load_cases())},
        "golden": git("rev-parse", "HEAD:eval/goldenset.json"),
        "fixtures": git("rev-parse", "HEAD:tests/fixtures/picasso"),
        "measurers": {path: git("rev-parse", f"HEAD:{path}") for path in
                      ("eval/recommend.py", "eval/measure.py", "eval/run.py", "explainer/client.py", "composer/query.py",
                       "eval/fusion_trial.py", "eval/query_trial.py")},
        "nexus": base, "token": "NEXUS_TOKEN", "topK": ANSWER_TOP_K, "identifierChannel": True,
        "exclude": {"recommend": list(EXCLUDE), "incidentAndSearch": list(INCIDENT_EXCLUDED), "query": []},
        "khalaBefore": ft.khala_identity(),
    }


def run_pass(name, arm, out, token, base, transport=http_transport, clock=ft._now):
    """실행 하나 — 웜업 한 번 뒤 항목을 차례로 부르고 기록을 쓴다. 401 · 403 · 422 면 곧바로 멈추고 기록을 안 쓴다."""
    work = items(arm)
    env = environment(name, arm, base)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    try:
        status, response = transport("POST", base.rstrip("/") + "/search", headers, dict(ft.WARM))
    except ValueError:
        status, response = "broken", {}
    why = ft.stop_reason("예열", status, response)
    if why:
        raise SystemExit(why)

    def flagged(method, url, headers, body):
        return transport(method, url, headers, {**body, **FLAGS})

    rows = []
    for item in work:
        at = clock()
        body, status, response = ft.call(item, flagged, base, token)
        why = ft.stop_reason(item["id"], status, response)
        if why:
            raise SystemExit(why)
        row = ft.row_of(item, body, status, response, at=at)
        row.update(queryChars=len(item["query"]), sentTokens=tokens(item["query"]))
        rows.append(row)
        print(f"{name} {item['id']} {status}", flush=True)
    env.update(endedAt=clock(), khalaAfter=ft.khala_identity())
    ft.write(out, env, rows)


# ── 평가 도구 — 기록만 읽는다(설계서 §2 · §3) ──

def _layout(record):
    return [(row["id"], row["key"], row["bodySha256"]) for row in record["rows"]]


def _by_id(record):
    return {row["id"]: row for row in record["rows"]}


def _secondary(arm, valid, rep, q0groups, keys, labeled):
    rows = [rep[arm][q0groups[key][0]["id"]] for key in keys]
    lat = {key: [_by_id(p["record"])[q0groups[key][0]["id"]]["data"]["timing"].get("total_ms") for p in valid[arm]]
           for key in keys}
    flat = [v for values in lat.values() for v in values if v is not None]
    spread = [max(v) - min(v) for v in lat.values() if len(v) > 1 and None not in v]
    conc = [ft.concentration(row) for row in rows]
    first = {key: rep[arm][q0groups[key][0]["id"]] for key in keys}
    return {
        "queryChars": {"mean": ft._mean([row["queryChars"] for row in rows]), "max": max(row["queryChars"] for row in rows),
                       "over2000": sum(row["queryChars"] > 2000 for row in rows)},
        "evidenceChars": ft._mean([sum(s["chars"] for s in row["data"]["snippets"]) for row in rows]),
        "ranked": ft._mean([sum(s["rank"] is not None for s in row["data"]["snippets"]) for row in rows]),
        "fills": ft._mean([sum(s["rank"] is None for s in row["data"]["snippets"]) for row in rows]),
        "tokens": ft._mean([len(row["data"]["identifier_channel"] or []) for row in rows]),
        "latency": {"median": statistics.median(flat) if flat else None, "range": [min(flat), max(flat)] if flat else None,
                    "spread": statistics.median(spread) if spread else None, "passes": len(valid[arm]), "byKey": lat},
        "wrong": {"labeled": sum(ft.wrong(first[key], ft.expected(q0groups[key])) for key in labeled),
                  "unlabeled": sum(ft.wrong(first[key], []) for key in keys if key not in labeled)},
        "concentration": {name: ft._mean([c[name] for c in conc]) for name in ("top20", "top10", "capped", "bundle")},
    }


def tally(records, reference=None):
    """기록 여럿 → 설계서 §2 · §3 의 수. 단위는 Q0 의 검색이고 실험군은 항목으로 짝짓는다.

    `reference` — 융합 실험 실행 T0 의 항목마다 상위 20(`{id: top}`). 주면 Q0 의 상위 20 과 견주어 그 사이 검색이 안 움직였나를 본다."""
    records = sorted(records, key=lambda r: r["env"]["at"])
    versions = collections.Counter(ft.versions_of(row["data"]) for r in records for row in r["rows"] if row.get("data"))
    if not versions:
        return {"passes": [], "comparable": "기록에 응답이 하나도 없다"}
    common = versions.most_common(1)[0][0]
    passes = [{"name": r["env"]["pass"], "arm": r["env"]["arm"], "problems": ft.validity(r, common), "record": r} for r in records]
    out = {"passes": [{"name": p["name"], "arm": p["arm"], "valid": not p["problems"], "problems": p["problems"][:10]}
                      for p in passes],
           "versions": list(common), "drift": [], "tokens": [], "negative": [], "unchanged": None, "reference": None,
           "broken": {arm: {"rows": sum(1 for p in passes if p["arm"] == arm for row in p["record"]["rows"]
                                        if row.get("data") and (row["data"]["degraded"] or row["data"]["enrichment_failed"])),
                            "of": sum(len(p["record"]["rows"]) for p in passes if p["arm"] == arm),
                            "passes": sum(1 for p in passes if p["arm"] == arm)} for arm in ARMS}}
    names = [p["name"] for p in passes]
    if len(set(names)) != len(names):
        out["comparable"] = "같은 이름의 판이 둘 이상이다"
        return out
    valid = {arm: [p for p in passes if p["arm"] == arm and not p["problems"]] for arm in ARMS}
    if not valid["Q0"] or not (valid["Q1"] or valid["Q2"]):
        out["comparable"] = "Q0 와 다른 실험군 하나에 성립한 판이 있어야 한다"
        return out
    every = [p for arm in ARMS for p in valid[arm]]
    if (any(len({json.dumps(_layout(p["record"])) for p in valid[arm]}) > 1 for arm in ARMS)
            or len({p["record"]["env"].get("narratorCommit") for p in every}) > 1):
        out["comparable"] = "같은 실험군 판끼리 항목 · 본문이 다르거나 narrator 커밋이 다르다"
        return out
    # khala 코드 신원 — 유효한 실행 전부의 앞뒤가 한 벌이어야 한다(실행 사이에 상대 저장소 코드가 안 움직였다)
    out["khalaChanged"] = len({json.dumps(p["record"]["env"].get(side), sort_keys=True)
                               for p in every for side in ("khalaBefore", "khalaAfter")}) > 1
    rep = {arm: _by_id(valid[arm][0]["record"]) for arm in ARMS if valid[arm]}
    q0groups = ft.searches(valid["Q0"][0]["record"])  # Q0 의 검색 — 요청 해시마다 구성원 줄
    keys = list(q0groups)
    # 결정론 — 같은 실험군 실행끼리 항목마다, 실행 안에서 같은 본문끼리, 같은 Q0 무리의 실험군 글끼리
    for arm in rep:
        for p in valid[arm]:
            mine = _by_id(p["record"])
            out["drift"] += [{"pass": p["name"], "ids": [cid]} for cid, row in mine.items() if ft.top(row) != ft.top(rep[arm][cid])]
            out["drift"] += [{"pass": p["name"], "ids": [row["id"] for row in rows]}
                             for rows in ft.searches(p["record"]).values() if len({ft.top(row) for row in rows}) > 1]
            # 식별자 토큰 — 응답이 쓴 것이 보낸 글에서 뽑은 것과 같은가(모든 유효한 실행)
            out["tokens"] += [{"arm": arm, "pass": p["name"], "id": cid, "sent": row["sentTokens"],
                               "used": row["data"]["identifier_channel"]}
                              for cid, row in mine.items() if (row["data"]["identifier_channel"] or []) != row["sentTokens"]]
        # 무리는 요청 해시로 본다 — 답변 컨텍스트는 사례마다 달라 본문 해시는 무리 안에서도 갈린다(⛔ 2026-10-01, 첫 평가 도구가 그것으로 잘못 걸었다)
        out["drift"] += [{"pass": valid[arm][0]["name"], "ids": [row["id"] for row in rows], "why": "같은 Q0 무리인데 글이 다르다"}
                         for rows in q0groups.values() if len({rep[arm][row["id"]]["key"] for row in rows}) > 1]
    # 처치가 걸렸나 — 글이 달라진 항목(Q1 과 Q2 가 같은 항목이어야 한다), Q2 의 토큰은 Q0 와 차례까지 같아야 한다
    out["changed"] = {arm: sorted(cid for cid in rep["Q0"] if rep[arm][cid]["bodySha256"] != rep["Q0"][cid]["bodySha256"])
                      for arm in rep if arm != "Q0"}
    changed_ok = len({tuple(ids) for ids in out["changed"].values()}) <= 1
    out["q2Tokens"] = ([cid for cid in rep["Q0"] if rep["Q2"][cid]["sentTokens"] != rep["Q0"][cid]["sentTokens"]]
                       if "Q2" in rep else None)
    out["q1SameTokens"] = (sum(rep["Q1"][q0groups[key][0]["id"]]["sentTokens"] == rep["Q0"][q0groups[key][0]["id"]]["sentTokens"]
                               for key in keys) if "Q1" in rep else None)
    # 음성 대조 — 세 글이 같은 항목은 실험군 사이 상위 20 이 같다
    unchanged = [cid for cid in rep["Q0"] if all(rep[arm][cid]["bodySha256"] == rep["Q0"][cid]["bodySha256"] for arm in rep)]
    out["unchanged"] = unchanged
    out["negative"] = [cid for cid in unchanged if len({ft.top(rep[arm][cid]) for arm in rep}) > 1]
    if reference:
        out["reference"] = sorted(cid for cid, top in reference.items() if cid in rep["Q0"] and ft.top(rep["Q0"][cid]) != top)
    out["comparable"] = ("khala 코드 신원이 판마다 같지 않다" if out["khalaChanged"]
                         else "결정론이 깨졌다" if out["drift"] else "식별자 토큰이 보낸 글과 다르다" if out["tokens"]
                         else "Q2 의 식별자 토큰이 Q0 와 다르다" if out["q2Tokens"]
                         else "Q1 과 Q2 의 글이 달라진 항목이 다르다" if not changed_ok
                         else "음성 대조가 갈렸다" if out["negative"] else None)
    labeled = [key for key in keys if ft.expected(q0groups[key])]

    def first(arm, key):
        return rep[arm][q0groups[key][0]["id"]]

    def any_in(arm, key, ranked=True):
        return any(ft.has(first(arm, key), doc, ranked) for doc in ft.expected(q0groups[key]))

    def ids(key):
        return [row["id"] for row in q0groups[key]]

    def against(left, right):
        pairs = [(ids(key), doc, ft.has(first(left, key), doc), ft.has(first(right, key), doc))
                 for key in labeled for doc in ft.expected(q0groups[key])]
        return {f"only{left}": [ids(key) for key in labeled if any_in(left, key) and not any_in(right, key)],
                f"only{right}": [ids(key) for key in labeled if any_in(right, key) and not any_in(left, key)],
                "split": [{"ids": p[0], "doc": p[1], left: p[2], right: p[3]} for p in pairs if p[2] != p[3]]}

    n = len(labeled)
    out["n"] = n
    out["arms"] = {}
    for arm in rep:
        head = sum(any_in(arm, key) for key in labeled)
        pairs = [ft.has(first(arm, key), doc) for key in labeled for doc in ft.expected(q0groups[key])]
        # 합쳐짐 — 이 실험군에서 서로 다른 Q0 검색이 같은 검색이 된 것(설계서 §2 — 단위가 독립이 아니라 p 값을 안 낸다)
        joined = collections.defaultdict(list)
        for key in keys:
            joined[first(arm, key)["key"]].append(key)
        entry = {"headline": (head, n, exact_interval(head, n)), "pairs": (sum(pairs), len(pairs)),
                 "allIn": sum(all(ft.has(first(arm, key), doc) for doc in ft.expected(q0groups[key])) for key in labeled),
                 "bundle": sum(any_in(arm, key, ranked=False) for key in labeled),
                 "sets": {name: (sum(any_in(arm, key) for key in labeled if any(r["set"] == name for r in q0groups[key])),
                                 sum(1 for key in labeled if any(r["set"] == name for r in q0groups[key])))
                          for name in ("recommend", "golden")},
                 "searches": {"all": len(joined), "labeled": len({first(arm, key)["key"] for key in labeled})},
                 "merges": [sum((ids(key) for key in group), []) for group in joined.values() if len(group) > 1],
                 "r01": {doc: ft.has(rep[arm]["R01"], doc) for doc in ft.expected([rep["Q0"]["R01"]])} if "R01" in rep[arm] else None,
                 "secondary": _secondary(arm, valid, rep, q0groups, keys, labeled)}
        if arm != "Q0":
            entry.update(against("Q0", arm), p=None)
            gaps = [statistics.mean(entry["secondary"]["latency"]["byKey"][key]) - statistics.mean(lat)
                    for key, lat in out["arms"]["Q0"]["secondary"]["latency"]["byKey"].items()
                    if None not in lat + entry["secondary"]["latency"]["byKey"][key]] if "Q0" in out["arms"] else []
            entry["secondary"]["latency"]["vsQ0Mean"] = statistics.median(gaps) if gaps else None
        out["arms"][arm] = entry
    out["q1VsQ2"] = against("Q1", "Q2") if {"Q1", "Q2"} <= set(rep) else None
    out["advance"] = advance(out["arms"]) if out["comparable"] is None else None
    return out


def advance(arms):
    """다음 단계로 승격할 실험군(설계서 §2). 세 실험군이 다 유효해야 정한다. 넘으려면 대표 지표와 쌍이 Q0 보다 낮지 않고 하나는 높으며,
    기대 아닌 절차 문서(`wrong.labeled`)가 Q0 보다 많지 않아야 한다. 둘 다 넘으면 쌍 · 대표 지표 · Q2 차례로 고른다. 없으면 `None`."""
    if set(arms) != set(ARMS):
        return None
    base = arms["Q0"]

    def passes(arm):
        a = arms[arm]
        return (a["headline"][0] >= base["headline"][0] and a["pairs"][0] >= base["pairs"][0]
                and (a["headline"][0] > base["headline"][0] or a["pairs"][0] > base["pairs"][0])
                and a["secondary"]["wrong"]["labeled"] <= base["secondary"]["wrong"]["labeled"])

    passed = [arm for arm in ("Q1", "Q2") if passes(arm)]
    if not passed:
        return None
    return sorted(passed, key=lambda arm: (-arms[arm]["pairs"][0], -arms[arm]["headline"][0], arm != "Q2"))[0]


def _fraction(triple):
    k, n, interval = triple
    return f"{k}/{n}" + (f" [{interval[0]:.2f}, {interval[1]:.2f}]" if interval else "")


def report_lines(out):
    lines = ["판 " + " · ".join(f"{p['name']}({p['arm']}) {'성립' if p['valid'] else '무효 ' + str(p['problems'][:5])}"
                               for p in out["passes"]),
             "판 칸(가장 많은 벌) " + json.dumps(out.get("versions"), ensure_ascii=False)
             + " · 검색 고장(모든 판의 줄) " + json.dumps(out.get("broken"), ensure_ascii=False)]
    if "arms" not in out:
        return lines + [f"⚠ 비교 안 함 — {out.get('comparable')}", "다음 단계로 넘길 실험군 — 판정 안 함"]
    lines += [
        "khala 코드 신원 " + ("판마다 다름" if out["khalaChanged"] else "한 벌")
        + " · 결정론 " + (json.dumps(out["drift"], ensure_ascii=False) if out["drift"] else "어긋남 없음")
        + " · 식별자 토큰 " + (json.dumps(out["tokens"], ensure_ascii=False) if out["tokens"] else "보낸 글과 같음")
        + " · Q2 토큰이 Q0 와 다른 항목 " + json.dumps(out["q2Tokens"])
        + f" · Q1 이 Q0 와 같은 토큰인 검색 {out['q1SameTokens']}"
        + " · 글이 달라진 항목 수 " + json.dumps({arm: len(ids) for arm, ids in out["changed"].items()})
        + f" · 음성 대조({len(out['unchanged'])}) " + ("갈림 " + json.dumps(out["negative"]) if out["negative"] else "같음")
        + " · 융합 판 T0 와 다른 Q0 항목 " + json.dumps(out["reference"]),
        ("머리 수치" if out["comparable"] is None else f"⚠ 머리 수치 아님({out['comparable']})")
        + f" — 기대 문서가 있는 Q0 검색 {out['n']} 에서 하나라도 상위 20: "
        + " · ".join(f"{arm} {_fraction(e['headline'])}" for arm, e in out["arms"].items())
        + " (합쳐진 검색은 Q0 단위 수만큼 센다 — p 값은 안 낸다)",
    ]
    for arm, e in out["arms"].items():
        line = (f"{arm} — 짝 {e['pairs'][0]}/{e['pairs'][1]} · 다 {e['allIn']}/{out['n']} · 묶음 {e['bundle']}/{out['n']} · 집합 "
                + json.dumps(e["sets"], ensure_ascii=False) + f" · 서로 다른 검색 {json.dumps(e['searches'])} · R01 "
                + json.dumps(e["r01"], ensure_ascii=False))
        if arm != "Q0":
            line += (f" · Q0 만 {e['onlyQ0']} · {arm} 만 {e[f'only{arm}']} · 갈린 짝 " + json.dumps(e["split"], ensure_ascii=False)
                     + " · 합쳐짐 " + json.dumps(e["merges"]))
        lines.append(line)
        secondary = {k: v for k, v in e["secondary"].items() if k != "latency"}
        latency = {k: v for k, v in e["secondary"]["latency"].items() if k != "byKey"}
        lines.append(f"   {arm} 부 변수 " + json.dumps(secondary, ensure_ascii=False) + " · 지연 " + json.dumps(latency))
    if out.get("q1VsQ2"):
        lines.append("Q1 대 Q2 " + json.dumps(out["q1VsQ2"], ensure_ascii=False))
    decided = out["comparable"] is None and set(out["arms"]) == set(ARMS)
    lines.append("다음 단계로 넘길 실험군 — " + ((out["advance"] or "없음") if decided else "판정 안 함"))
    return lines


def _reference():
    """융합 실험 실행 T0(t0-2)의 항목마다 상위 20 — 기록이 없으면 `None`."""
    path = ft.ROOT / "eval" / "fusion" / "t0-2.json"
    if not path.exists():
        return None
    return {row["id"]: ft.top(row) for row in json.loads(path.read_text(encoding="utf-8"))["rows"] if row.get("data")}


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["run"] and len(args) >= 3 and "--out" in args[:-1]:
        name, arm = args[1], args[2].upper()
        out = pathlib.Path(args[args.index("--out") + 1])
        if arm not in ARMS:
            raise SystemExit(f"실험군은 {list(ARMS)} 가운데 하나다: {arm}")
        if not name.lower().startswith(arm.lower() + "-"):
            raise SystemExit(f"판 이름은 실험군으로 시작한다(q0-1 · q1-1 …): {name} · {arm}")
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
