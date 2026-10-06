"""질문 제거 — 설계서 `docs/superpowers/specs/2026-10-01-물음-떼기.md`.

**실행.** 측정기가 이 커밋에서 지을 요청의 질의만 실험군의 글로 바꿔 근거만 받는다(생성 없음, F1 칸 안 보냄)::

    KHALA_ROOT=<khala 저장소> python -m eval.ask_trial run q3-1 Q3 --out eval/ask/q3-1.json

**평가 도구.** 기록 여럿을 읽는 순수 함수다::

    python -m eval.ask_trial tally "eval/ask/*.json"

질의 축소(`eval/query_trial.py`)의 글 짓기 · 2차 결과 변수와 융합 실험 실행(`eval/fusion_trial.py`)의 본문 짓기 · 줄 · 유효성을 가져다
쓰고 두 파일은 고치지 않는다.
"""

import collections
import glob
import json
import os
import pathlib
import statistics
import sys

from composer.query import ASK
from eval import fusion_trial as ft
from eval import query_trial as qt
from eval.recommend import EXCLUDE, frozen_problems
from eval.recommend_score import load_cases, scoring_hash
from eval.recommend_variance import PROCEDURE_TITLES, exact_interval
from explainer.client import ANSWER_TOP_K, INCIDENT_EXCLUDED
from explainer.transport import http_transport

SPEC = "docs/superpowers/specs/2026-10-01-물음-떼기.md"
COMMITTED = (SPEC, "eval/ask_trial.py", "tests/test_eval_ask_trial.py", "eval/query_trial.py", "eval/fusion_trial.py")
ARMS = ("Q0", "Q2", "Q3")
#: 승격 후보(설계서 §2). Q2 는 앞 실행의 실행 전 규칙이 이미 「안 넘긴다」로 정한 비교군이다.
CANDIDATES = ("Q3",)
FLAGS = {"evidence_only": True}


def texts(query):
    """한 `Query` 의 세 글(설계서 §1). Q0 · Q2 는 질의 축소의 글 그대로이고 Q3 은 Q2 에서 고정 질문(`ASK`)만 뺀 글이다 —
    조회 지시는 맨 앞에 남고, 식별자 토큰과 스칼라 사실은 Q2 의 차례 그대로다. 질의 줄(글자 그대로의 질문)은 세 글이 같다."""
    base = qt.texts(query)
    if isinstance(query, str):
        return {arm: base["Q0"] for arm in ARMS}
    head = query.lookup + ASK
    if not base["Q2"].startswith(head):
        raise ValueError(f"Q2 가 조회 지시와 물음으로 시작하지 않는다: {base['Q2'][:80]!r}")
    q3 = query.lookup + base["Q2"][len(head):]
    if not q3.strip():
        # 빈 질의는 khala 가 400 으로 받는데 400 은 곧바로 멈추는 상태가 아니라 실행이 무효인 채 끝까지 돈다 — 짓는 자리에서 막는다
        raise ValueError("물음을 떼니 빈 글이다 — 사실도 조회 지시도 없는 Query")
    return {"Q0": base["Q0"], "Q2": base["Q2"], "Q3": q3}


def items(arm, doc=None):
    """잴 항목 — 융합 실험 실행의 항목에 실험군의 글을 넣는다. 권고 사례의 답변 컨텍스트는 그대로다(설계서 §1)."""
    base = ft.items(doc)
    built = qt.queries(doc)
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
                       "eval/fusion_trial.py", "eval/query_trial.py", "eval/ask_trial.py")},
        "nexus": base, "token": "NEXUS_TOKEN", "topK": ANSWER_TOP_K, "identifierChannel": True,
        "exclude": {"recommend": list(EXCLUDE), "incidentAndSearch": list(INCIDENT_EXCLUDED), "query": []},
        "khalaBefore": ft.khala_identity(),
    }


def run_pass(name, arm, out, token, base, transport=http_transport, clock=ft._now):
    """실행 하나 — 웜업 한 번 뒤 항목을 차례로 부르고 기록을 쓴다. 401 · 403 · 422 면 곧바로 멈추고 기록을 안 쓴다.
    줄마다 질의 길이 · 보낸 토큰 · 응답의 검색 경로(`route_used`)를 더 적는다."""
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
        data = response.get("data") if isinstance(response, dict) else None
        row.update(queryChars=len(item["query"]), sentTokens=qt.tokens(item["query"]),
                   route=data.get("route_used") if isinstance(data, dict) else None)
        rows.append(row)
        print(f"{name} {item['id']} {status}", flush=True)
    env.update(endedAt=clock(), khalaAfter=ft.khala_identity())
    ft.write(out, env, rows)


# ── 평가 도구 — 기록만 읽는다(설계서 §2 · §3) ──

def _wrong_by(arm, rep, q0groups, labeled):
    """기대 아닌 채로 상위 20 에 든 기대 있는 검색의 수 — 절차 문서마다(설계서 §2)."""
    counts = collections.Counter()
    for key in labeled:
        rows = q0groups[key]
        want = ft.expected(rows)
        row = rep[arm][rows[0]["id"]]
        counts.update(title for title in PROCEDURE_TITLES if title not in want and ft.has(row, title))
    return dict(sorted(counts.items()))


def _strength(arm, rep, q0groups, keys):
    """근거 강도 — 적기만 한다(설계서 §2). Q0 검색의 첫 구성원 줄에서 `weak_evidence` 의 수와 `top_distance` · `top_bm25` 의
    중앙값과 끝값. 질문이 빠진 짧은 글이 khala 의 약함 임계값을 넘으면 생성 실행의 서술 계약이 바뀐다."""
    rows = [rep[arm][q0groups[key][0]["id"]]["data"] for key in keys]
    distance = [d["top_distance"] for d in rows if d.get("top_distance") is not None]
    bm25 = [d["top_bm25"] for d in rows if d.get("top_bm25") is not None]
    return {"weak": sum(bool(d.get("weak_evidence")) for d in rows), "of": len(rows),
            "topDistance": {"median": statistics.median(distance), "max": max(distance)} if distance else None,
            "topBm25": {"median": statistics.median(bm25), "min": min(bm25)} if bm25 else None}


def tally(records, reference=None):
    """기록 여럿 → 설계서 §2 · §3 의 수. 단위는 Q0 의 검색이고 실험군은 항목으로 짝짓는다.

    `reference` — 앞 실행(질의 축소 `q0-1`)의 항목마다 상위 20(`{id: top}`). 주면 Q0 와 견주어 두 창 사이 검색이 안 움직였나를 본다."""
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
    if not valid["Q0"] or not any(valid[arm] for arm in ARMS if arm != "Q0"):
        out["comparable"] = "Q0 와 다른 실험군 하나에 성립한 판이 있어야 한다"
        return out
    every = [p for arm in ARMS for p in valid[arm]]
    if (any(len({json.dumps(qt._layout(p["record"])) for p in valid[arm]}) > 1 for arm in ARMS)
            or len({p["record"]["env"].get("narratorCommit") for p in every}) > 1):
        out["comparable"] = "같은 실험군 판끼리 항목 · 본문이 다르거나 narrator 커밋이 다르다"
        return out
    # khala 코드 신원 — 유효한 실행 전부의 앞뒤가 한 벌이어야 한다
    out["khalaChanged"] = len({json.dumps(p["record"]["env"].get(side), sort_keys=True)
                               for p in every for side in ("khalaBefore", "khalaAfter")}) > 1
    rep = {arm: qt._by_id(valid[arm][0]["record"]) for arm in ARMS if valid[arm]}
    q0groups = ft.searches(valid["Q0"][0]["record"])
    keys = list(q0groups)
    # 결정론 — 같은 실험군 실행끼리 항목마다, 실행 안에서 같은 검색끼리, 같은 Q0 무리의 요청 해시끼리
    for arm in rep:
        for p in valid[arm]:
            mine = qt._by_id(p["record"])
            out["drift"] += [{"pass": p["name"], "ids": [cid]} for cid, row in mine.items() if ft.top(row) != ft.top(rep[arm][cid])]
            out["drift"] += [{"pass": p["name"], "ids": [row["id"] for row in rows]}
                             for rows in ft.searches(p["record"]).values() if len({ft.top(row) for row in rows}) > 1]
            out["tokens"] += [{"arm": arm, "pass": p["name"], "id": cid, "sent": row["sentTokens"],
                               "used": row["data"]["identifier_channel"]}
                              for cid, row in mine.items() if (row["data"]["identifier_channel"] or []) != row["sentTokens"]]
        out["drift"] += [{"pass": valid[arm][0]["name"], "ids": [row["id"] for row in rows], "why": "같은 Q0 무리인데 글이 다르다"}
                         for rows in q0groups.values() if len({rep[arm][row["id"]]["key"] for row in rows}) > 1]
    # 처치가 걸렸나 — 바뀐 항목, 질문만 뺐나(글자 수 차), 토큰의 차례
    out["changed"] = {arm: sorted(cid for cid in rep["Q0"] if rep[arm][cid]["bodySha256"] != rep["Q0"][cid]["bodySha256"])
                      for arm in rep if arm != "Q0"}
    subset = not {"Q2", "Q3"} <= set(rep) or set(out["changed"]["Q2"]) <= set(out["changed"]["Q3"])
    out["askCut"] = ([cid for cid in rep["Q0"] if rep["Q3"][cid]["bodySha256"] != rep["Q0"][cid]["bodySha256"]
                      and rep["Q2"][cid]["queryChars"] - rep["Q3"][cid]["queryChars"] != len(ASK)]
                     if {"Q2", "Q3"} <= set(rep) else None)
    # Q3 이 Q0 와 같은 글을 보냈으면 그 항목의 Q0 는 질문이 없는 글(질의 줄)이어야 한다 — 질문보다 짧다. 위 둘이 못 잡는 R05 의
    # 자리다(Q2 도 안 바꾸고 글자 수 검사도 건너뛴다, 독립 검토)
    out["askKept"] = ([cid for cid in rep["Q0"] if rep["Q3"][cid]["bodySha256"] == rep["Q0"][cid]["bodySha256"]
                       and rep["Q0"][cid]["queryChars"] >= len(ASK)] if "Q3" in rep else None)
    out["tokenOrder"] = {arm: [cid for cid in rep["Q0"] if rep[arm][cid]["sentTokens"] != rep["Q0"][cid]["sentTokens"]]
                         for arm in rep if arm != "Q0"}
    # 음성 대조 — 세 글이 같은 항목은 실험군 사이 상위 20 이 같다
    unchanged = [cid for cid in rep["Q0"] if all(rep[arm][cid]["bodySha256"] == rep["Q0"][cid]["bodySha256"] for arm in rep)]
    out["unchanged"] = unchanged
    out["negative"] = [cid for cid in unchanged if len({ft.top(rep[arm][cid]) for arm in rep}) > 1]
    if reference:
        out["reference"] = sorted(cid for cid, top in reference.items() if cid in rep["Q0"] and ft.top(rep["Q0"][cid]) != top)
    out["comparable"] = ("khala 코드 신원이 판마다 같지 않다" if out["khalaChanged"]
                         else "결정론이 깨졌다" if out["drift"] else "식별자 토큰이 보낸 글과 다르다" if out["tokens"]
                         else "실험군의 식별자 토큰이 Q0 와 다르다" if any(out["tokenOrder"].values())
                         else "Q3 이 Q2 에서 물음만 뺀 글이 아니다" if out["askCut"]
                         else "Q3 이 물음 있는 글을 그대로 보냈다" if out["askKept"]
                         else "Q2 가 바꾼 항목을 Q3 이 안 바꿨다" if not subset
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
                 "routes": dict(sorted(collections.Counter(str(first(arm, key).get("route")) for key in keys).items())),
                 "wrongBy": _wrong_by(arm, rep, q0groups, labeled),
                 "strength": _strength(arm, rep, q0groups, keys),
                 "secondary": qt._secondary(arm, valid, rep, q0groups, keys, labeled)}
        if arm != "Q0":
            entry.update(against("Q0", arm), p=None)
            gaps = [statistics.mean(entry["secondary"]["latency"]["byKey"][key]) - statistics.mean(lat)
                    for key, lat in out["arms"]["Q0"]["secondary"]["latency"]["byKey"].items()
                    if None not in lat + entry["secondary"]["latency"]["byKey"][key]] if "Q0" in out["arms"] else []
            entry["secondary"]["latency"]["vsQ0Mean"] = statistics.median(gaps) if gaps else None
        out["arms"][arm] = entry
    if {"Q2", "Q3"} <= set(rep):
        out["q2VsQ3"] = dict(against("Q2", "Q3"), wrong=(out["arms"]["Q2"]["secondary"]["wrong"]["labeled"],
                                                         out["arms"]["Q3"]["secondary"]["wrong"]["labeled"]))
    else:
        out["q2VsQ3"] = None
    out["advance"] = advance(out["arms"]) if out["comparable"] is None else None
    return out


def advance(arms):
    """다음 단계로 승격할 실험군(설계서 §2). 세 실험군이 다 유효해야 정하고 후보는 Q3 하나다. 대표 지표와 쌍이 Q0 보다 낮지 않고
    하나는 높으며, 기대 있는 검색의 틀린 절차가 Q0 보다 많지 않아야 넘는다. 못 넘으면 `None`."""
    if set(arms) != set(ARMS):
        return None
    base = arms["Q0"]

    def passes(arm):
        a = arms[arm]
        return (a["headline"][0] >= base["headline"][0] and a["pairs"][0] >= base["pairs"][0]
                and (a["headline"][0] > base["headline"][0] or a["pairs"][0] > base["pairs"][0])
                and a["secondary"]["wrong"]["labeled"] <= base["secondary"]["wrong"]["labeled"])

    passed = [arm for arm in CANDIDATES if passes(arm)]
    return passed[0] if passed else None


def _short(title):
    return title.split()[0] if title.startswith("SOP-") else "정지코드"


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
        + " · 토큰 차례가 Q0 와 다른 항목 " + json.dumps(out["tokenOrder"])
        + " · 물음만 뺀 글이 아닌 항목 " + ("Q2 판이 없어 안 봄" if out["askCut"] is None else json.dumps(out["askCut"]))
        + " · 물음 있는 글을 그대로 보낸 항목 " + ("Q3 판이 없어 안 봄" if out["askKept"] is None else json.dumps(out["askKept"]))
        + " · 글이 달라진 항목 수 " + json.dumps({arm: len(ids) for arm, ids in out["changed"].items()})
        + f" · 음성 대조({len(out['unchanged'])}) " + ("갈림 " + json.dumps(out["negative"]) if out["negative"] else "같음")
        + " · 앞 판 Q0 와 다른 항목 " + json.dumps(out["reference"]),
        ("머리 수치" if out["comparable"] is None else f"⚠ 머리 수치 아님({out['comparable']})")
        + f" — 기대 문서가 있는 Q0 검색 {out['n']} 에서 하나라도 상위 20: "
        + " · ".join(f"{arm} {qt._fraction(e['headline'])}" for arm, e in out["arms"].items())
        + " (합쳐진 검색은 Q0 단위 수만큼 센다 — p 값은 안 낸다)",
    ]
    for arm, e in out["arms"].items():
        line = (f"{arm} — 짝 {e['pairs'][0]}/{e['pairs'][1]} · 다 {e['allIn']}/{out['n']} · 묶음 {e['bundle']}/{out['n']} · 집합 "
                + json.dumps(e["sets"], ensure_ascii=False) + f" · 서로 다른 검색 {json.dumps(e['searches'])} · R01 "
                + json.dumps(e["r01"], ensure_ascii=False) + " · 경로 " + json.dumps(e["routes"], ensure_ascii=False)
                + " · 틀린 절차(문서별) " + json.dumps({_short(t): c for t, c in e["wrongBy"].items()}, ensure_ascii=False)
                + " · 근거 세기(적기만) " + json.dumps(e["strength"], ensure_ascii=False))
        if arm != "Q0":
            line += (f" · Q0 만 {e['onlyQ0']} · {arm} 만 {e[f'only{arm}']} · 갈린 짝 " + json.dumps(e["split"], ensure_ascii=False)
                     + " · 합쳐짐 " + json.dumps(e["merges"]))
        lines.append(line)
        secondary = {k: v for k, v in e["secondary"].items() if k != "latency"}
        latency = {k: v for k, v in e["secondary"]["latency"].items() if k != "byKey"}
        lines.append(f"   {arm} 부 변수 " + json.dumps(secondary, ensure_ascii=False) + " · 지연 " + json.dumps(latency))
    if out.get("q2VsQ3"):
        lines.append("Q2 대 Q3(물음의 몫) " + json.dumps(out["q2VsQ3"], ensure_ascii=False))
    decided = out["comparable"] is None and set(out["arms"]) == set(ARMS)
    lines.append("다음 단계로 넘길 실험군 — " + ((out["advance"] or "없음") if decided else "판정 안 함"))
    return lines


def _reference():
    """앞 실행(질의 축소 `q0-1`)의 항목마다 상위 20 — 기록이 없으면 `None`."""
    path = ft.ROOT / "eval" / "query" / "q0-1.json"
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
            raise SystemExit(f"판 이름은 실험군으로 시작한다(q0-1 · q3-1 …): {name} · {arm}")
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
