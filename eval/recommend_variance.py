"""권고 변동의 셈 — 설계서 `docs/superpowers/specs/2026-10-01-권고-변동.md` §2.

**순수 함수다.** 측정기 기록 여럿(`{env, complete, rows}`)과 사례 파일만으로 센다. 채점기의 `merge` 는 쓰지 않는다 — 사례마다
마지막 줄만 남겨 반복을 접는다. 비율은 `(k, n)` 짝이고, 곁에 정확한 양쪽 95% 구간(Clopper-Pearson)을 보조로 낸다.

    python -m eval.recommend_variance eval/variance/var-*.json
"""

import json
import math
import pathlib
import subprocess
import sys

from diagnose.fields import _CITATION
from eval.recommend_score import ROOT, clean, load_cases, names_doc, norm, scoring_hash, version_tuple

SPEC = "docs/superpowers/specs/2026-10-01-권고-변동.md"
SELF = "eval/recommend_variance.py"
APPROVE = "APPROVE_REMEDY"

#: 코퍼스의 절차 문서 일곱 — 사례 불변식 시험(`tests/test_eval_recommend_cases.py`)의 목록과 같다.
PROCEDURE_TITLES = (
    "SOP-01 파지 실패와 잔여 파지 처리", "SOP-02 안착 실패와 품번 불일치", "SOP-03 자재 결품과 대체 슬롯 운용",
    "SOP-04 이동 경로 차단 대응", "SOP-05 자기 위치 상실 복구", "SOP-06 제어권 상실과 명령 덮어쓰기",
    "합성 기체(fixture)의 정지 코드 표면 — Synthetic Stop-Code Surface",
)


def kind_of(row):
    """풀린 표지의 후보 종류. 풀리지 않았으면 `None`."""
    return row["kinds"].get(row["resolved"]) if row["resolved"] is not None else None


def search_state(row):
    """검색 고장 칸 둘(`degraded` · `enrichment_failed`)로 `broken` · `unknown` · `intact`. 하나라도 빈 목록이 아니면 고장이고,
    고장이 아닌데 하나라도 `None` 이면 모름이다 — 칸이 없던 판의 줄은 온전하다고 못 한다."""
    diagnostics = row.get("diagnostics") or {}
    values = [diagnostics.get("degraded"), diagnostics.get("enrichment_failed")]
    if any(isinstance(v, list) and v for v in values):
        return "broken"
    if any(v is None for v in values):
        return "unknown"
    return "intact"


def cited_docs(response, docs):
    """이유 글이 검증된 인용으로 대는 문서들(설계서 §2 「A 의 절차 인용」). 닫힌 `[출처: …]` 무리마다 `출처:` 뒤를 몸으로 보고,
    `verified` 가 참인 인용의 제목 t 로 몸이 시작하고 `names_doc(t, d)` 가 참이면 그 무리가 d 를 댄다."""
    titles = [c["title"] for c in response.get("citations") or [] if c.get("verified") is True and c.get("title")]
    out = set()
    for group in _CITATION.finditer(response.get("rationale") or ""):
        body = norm(group.group(0)[len("[출처:"):-1])
        for title in titles:
            if body.startswith(norm(title)):
                out.update(d for d in docs if names_doc(title, d))
    return out


def exact_interval(k, n, level=0.95):
    """정확한 양쪽 구간(Clopper-Pearson). `n` 이 0 이면 `None`. 이분법으로 이항 꼬리를 맞춘다."""
    if n == 0:
        return None
    tail = (1 - level) / 2

    def upper_tail(p):  # P(X >= k)
        return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))

    def lower_tail(p):  # P(X <= k)
        return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(0, k + 1))

    def solve(f, rising):
        lo, hi = 0.0, 1.0
        for _ in range(80):
            mid = (lo + hi) / 2
            if (f(mid) < tail) == rising:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    low = 0.0 if k == 0 else solve(upper_tail, rising=True)
    high = 1.0 if k == n else solve(lower_tail, rising=False)
    return low, high


def _identity(env, row):
    return (row.get("requestSha256"), row.get("querySha256"), row.get("contextSha256"),
            env.get("narratorCommit"), env.get("scorer"), env.get("measurer"))


def _count(values):
    out = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: str(kv[0])))


def _measure(case, rows):
    """답한 줄들로 설계서 §2 의 수. 비율은 `(k, n)` — 분모는 답한 반복이고, **절차 인용 둘만 A 를 고른 답이 분모**다."""
    n = len(rows)
    approves = [r for r in rows if kind_of(r) == APPROVE]

    def is_clean_approve(r):
        return r["response"]["outcome"] == "RECOMMENDED" and kind_of(r) == APPROVE and clean(r["response"])

    def cites_any(r):
        return bool(cited_docs(r["response"], PROCEDURE_TITLES))

    def evidence_has(r, d):
        return any(names_doc(e, d) for e in (r.get("diagnostics") or {}).get("evidenceDocs") or [])

    docs = list(case["procedureDocs"])
    return {
        "n": n,
        "picks": _count("unresolved" if kind_of(r) is None else kind_of(r) for r in rows),
        "outcomes": _count(r["response"]["outcome"] for r in rows),
        "approve": (len(approves), n),
        "cleanApprove": (sum(is_clean_approve(r) for r in rows), n),
        "forbiddenEffect": (sum(r["response"]["outcome"] == "RECOMMENDED"
                                and r["response"]["candidateId"] in case["mustNotPick"] for r in rows), n),
        "approveCites": {d: (sum(d in cited_docs(r["response"], [d]) for r in approves), len(approves)) for d in docs},
        "approveCitesAny": (sum(cites_any(r) for r in approves), len(approves)),
        "cleanApproveCited": (sum(is_clean_approve(r) and cites_any(r) for r in rows), n),
        "evidence": {d: (sum(evidence_has(r, d) for r in rows), n) for d in docs},
    }


def tally(doc, records):
    """기록 여럿 → 입력마다의 수(설계서 §2). 사례 판이 다른 기록은 안 센다.

    한 입력의 답한 줄이 같은 입력의 칸 여섯과 판 칸 넷으로 둘 이상의 갈래면 `parts` 에 갈래마다 따로 센다 — 설계서 §2
    「갈리면 무리마다 적고 합치지 않는다」. 그때 그 입력의 `all` · `intact` 는 합친 값이라 머리 수치가 아니다."""
    now = scoring_hash(doc)
    cases = {c["id"]: c for c in doc["cases"]}
    order = list(cases)
    skipped = [r["env"].get("pass") for r in records if r["env"]["cases"]["scoringHash"] != now]
    entries = []
    for record in records:
        if record["env"]["cases"]["scoringHash"] != now:
            continue
        for position, row in enumerate(record["rows"]):
            entries.append((record["env"], position, row))
    inputs = {}
    for cid in sorted({row["id"] for _, _, row in entries}, key=order.index):
        mine = [(env, position, row) for env, position, row in entries if row["id"] == cid]
        answered = [row for _, _, row in mine if row.get("response") is not None]
        intact = [row for row in answered if search_state(row) == "intact"]
        parts = {}
        for env, _, row in mine:
            if row.get("response") is not None:
                parts.setdefault(_identity(env, row) + version_tuple(row), []).append(row)
        inputs[cid] = {
            "all": _measure(cases[cid], answered),
            "intact": _measure(cases[cid], intact),
            "parts": [] if len(parts) < 2 else [
                {"key": key, "all": _measure(cases[cid], rows),
                 "intact": _measure(cases[cid], [r for r in rows if search_state(r) == "intact"])}
                for key, rows in sorted(parts.items(), key=lambda kv: str(kv[0]))],
            "failed": _count(row.get("failed") for _, _, row in mine if row.get("response") is None),
            "groups": sorted({_identity(env, row) for env, _, row in mine}, key=str),
            "search": {state: [(env.get("pass"), position) for env, position, row in mine
                               if row.get("response") is not None and search_state(row) == state]
                       for state in ("broken", "unknown")},
        }
    versions = {version_tuple(row) for _, _, row in entries if row.get("response") is not None}
    headline = (len(versions) == 1 and None not in next(iter(versions))
                and all(len(v["groups"]) == 1 for v in inputs.values()))
    return {"skipped": skipped, "inputs": inputs, "versions": sorted(versions, key=str), "headline": headline}


def fraction(pair):
    k, n = pair
    interval = exact_interval(k, n)
    if interval is None:
        return f"{k}/{n}"
    return f"{k}/{n} [{interval[0]:.2f}, {interval[1]:.2f}]"


def _per_doc(pairs):
    """문서마다의 수 — SOP 는 번호만 적는다. 사례에 절차 문서가 없으면 그렇다고 적는다."""
    return " · ".join(f"{d.split()[0] if d.startswith('SOP-') else d} {fraction(p)}" for d, p in pairs.items()) or "(사례의 절차 문서 없음)"


def _measure_lines(m, label):
    return [f"  [{label}] n={m['n']} · 고른 것 {json.dumps(m['picks'], ensure_ascii=False)} · 결과 "
            f"{json.dumps(m['outcomes'], ensure_ascii=False)}",
            f"    A {fraction(m['approve'])} · 깨끗한 A {fraction(m['cleanApprove'])} · 금지 효과 {fraction(m['forbiddenEffect'])}",
            f"    A 의 절차 인용 {_per_doc(m['approveCites'])} · 일곱 가운데 하나라도 {fraction(m['approveCitesAny'])}"
            f" · 깨끗하고 인용한 A {fraction(m['cleanApproveCited'])}",
            f"    근거에 온 절차 문서 {_per_doc(m['evidence'])}"]


def report_lines(out):
    lines = ["머리 수치 — 판 칸 한 벌 · 입력마다 한 무리" if out["headline"]
             else "머리 수치 아님 — 판 칸이 갈렸거나 같은 입력이 아닌 줄이 섞였다"]
    if out["skipped"]:
        lines.append(f"⚠ 사례 판이 달라 안 센 기록: {out['skipped']}")
    lines.append("판 칸 " + json.dumps(out["versions"], ensure_ascii=False))
    for cid, value in out["inputs"].items():
        lines.append(f"## {cid} — 무리 {len(value['groups'])} · 실패 {json.dumps(value['failed'], ensure_ascii=False)}"
                     f" · 고장 {value['search']['broken']} · 모름 {value['search']['unknown']}")
        if not value["parts"]:
            lines += _measure_lines(value["all"], "전부") + _measure_lines(value["intact"], "온전한 것만")
            continue
        lines.append(f"  ⚠ 갈래 {len(value['parts'])} — 같은 입력 칸이나 판 칸이 다른 줄은 합치지 않는다")
        for i, part in enumerate(value["parts"], 1):
            lines.append(f"  갈래 {i}: " + json.dumps(part["key"], ensure_ascii=False))
            lines += _measure_lines(part["all"], "전부") + _measure_lines(part["intact"], "온전한 것만")
    return lines


def _ancestry_warnings(records):
    """설계서와 셈을 마지막으로 고친 커밋이 기록마다의 `narratorCommit` 의 조상인가(설계서 §5) — 아니면 판 뒤에 고친 것이다."""
    last = subprocess.run(["git", "log", "-1", "--format=%H", "--", SPEC, SELF], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    out = []
    for record in records:
        commit = record["env"].get("narratorCommit")
        if not last or not commit:
            out.append(f"⚠ 조상 검사를 못 했다 — {record['env'].get('pass')}")
            continue
        done = subprocess.run(["git", "merge-base", "--is-ancestor", last, commit], cwd=ROOT, capture_output=True)
        if done.returncode != 0:
            out.append(f"⚠ 설계서나 셈이 {record['env'].get('pass')} 의 판({commit[:7]}) 뒤에 고쳐졌다")
    return out


def main(argv=None):
    paths = list(sys.argv[1:] if argv is None else argv)
    records = [json.loads(pathlib.Path(p).read_text(encoding="utf-8")) for p in paths]
    for line in _ancestry_warnings(records) + report_lines(tally(load_cases(), records)):
        print(line)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
