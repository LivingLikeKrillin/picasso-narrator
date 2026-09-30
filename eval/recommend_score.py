"""권고 측정의 채점 — 설계서 `docs/superpowers/specs/2026-09-30-권고-측정.md` §3.

**순수 함수다.** 기록(`{env, complete, rows}`)과 사례 파일만으로 다시 센다. 파생값(표지 갈래 · 꾸밈 · 맨 정수 조각 · 인용 없음의
원인)은 기록에 넣지 않고 여기서 매번 센다 — 정규식을 고쳐도 옛 기록을 다시 센다(함정 3). 비율은 `(k, n)` 짝이고 `n` 이 0 이어도
짝 그대로 돌려준다 — 적을 때 `k/n` 으로 적으므로 0 과 「없음」이 섞이지 않는다.

    python -m eval.recommend_score                              # eval/last-recommendations.json
    python -m eval.recommend_score A.json B.json                # 사례마다 뒤의 기록
    python -m eval.recommend_score A.json --allow-drift         # 사례 파일이 바뀌었어도(머리에 적는다)
"""

import hashlib
import json
import pathlib
import re
import sys
import unicodedata

from diagnose.answer import resolve
from diagnose.fields import _GROUP
from recorder.card import HEAD_LINES, LABELS, parse_card

ROOT = pathlib.Path(__file__).resolve().parent.parent
CASES = ROOT / "eval" / "goldenset-recommend.json"
RECORD = ROOT / "eval" / "last-recommendations.json"
READINGS = ROOT / "eval" / "recommend-readings.json"

ESCALATE = "ESCALATE"

#: 사례마다의 채점 칸 — 이 칸과 파일의 `version` · `criteria` 가 바뀌면 다른 측정이다(설계서 §0).
SCORING_KEYS = ("id", "tier", "request", "requestSha256", "expect", "mustNotPick", "reading", "removed",
                "procedureDocs", "repeatOf", "seen")


def load_cases(path=CASES):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def scoring_hash(doc):
    """사례 파일의 판 · 판독 기준 · 사례마다의 채점 칸의 sha256. 차례와 빈칸에 흔들리지 않게 정규화한다."""
    body = {"version": doc["version"], "criteria": doc["criteria"],
            "cases": [{k: case[k] for k in SCORING_KEYS} for case in doc["cases"]]}
    text = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── 조각 — 답 하나에서 세는 것(설계서 §3.2 · §3.4~3.7) ──

#: `1005cd1` 앞의 머리 줄 정규식 — 제목 기호(`#`)를 안 받았다. 옛 파서로 센 후보 밖(M2)에 쓴다.
HEAD_OLD = re.compile(r"^\s*(?:[-*]\s*)?(?:\*\*)?(권고|이유)(?:\*\*)?\s*[:：]\s*(?:\*\*)?\s*(.*?)\s*$")

#: 느슨한 탐지 — 줄머리의 꾸밈(인용 · 제목 · 목록 · 강조) 뒤에 표지 이름이 오고, 그 뒤가 콜론 · 줄 끝 · 「사항」 · 대시인 줄.
#: 본문의 「권고하지 않는다」 같은 문장은 안 걸린다.
LOOSE = re.compile(
    r"^\s*(?P<quote>(?:>\s*)+)?(?P<heading>#{1,6}\s*)?(?P<list>(?:[-*+]|\d+[.)])\s+)?(?P<emph>\*\*|__|\*|_)?"
    r"(?P<label>권고|이유|절차|먼저|금지|갈림|근거 세기)(?:\*\*|__|\*|_)?(?=\s*[:：]|\s*$|\s+사항|\s+[-–—]\s)"
)

#: 인용 같은 글 — khala 가 못 읽은 표기(원인 (b)).
CITELIKE = re.compile(r"출처\s*[:：]|\[[^\]\n]*(?:§|SOP-)[^\]\n]*\]")

#: 맨 정수의 제외(설계서 §3.7). 차례에 뜻이 있다 — 날짜 · 시각을 식별자보다 먼저 지운다.
EXCLUDE = (
    re.compile(r"\d{4}-\d{2}-\d{2}(?:T[0-9:.]+Z?)?"),
    re.compile(r"\d{1,2}:\d{2}(?::\d{2})?"),
    re.compile(r"\bE[0-3]\b"),
    re.compile(r"§\s*\d+(?:\.\d+)*(?:\s*[①-⑳])?"),
    re.compile(r"\d+(?:\.\d+)*\s*(?:절|항)(?:\s*[①-⑳])?"),
    re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:[-.:#][A-Za-z0-9_]+)+"),
)
BARE = re.compile(r"(?<![0-9.,§])[0-9](?![0-9]|[.,][0-9]|%)")
CIRCLED = re.compile(r"[①-⑳]")

#: 판독 기준 C1 의 대리값(설계서 §2.4) — 판독자 앞에 놓는 자동 짚음이고 판독 값은 판독자의 것이다. ⚠ 맨 `E2` 는 (가)로 안
#: 친다 — 보류 단위의 질의는 모두 `requiredEvidence=E2` 를 실어 「E2 에 못 미친다」에도 나온다.
EQUIPMENT = re.compile(r"MATCHED|설비")
HUMAN = re.compile(r"육안|현물|직접\s*확인|눈으로|사람이[^.。]{0,20}확인")

#: 투영이 뺀 조치를 가리키는 말(M3 대리값).
REMOVED_WORDS = {
    "REWORK": re.compile(r"REWORK|재작업|다시\s*(?:실행|돌리|돌려|작업)", re.I),
    "CHOOSE_SOURCE": re.compile(r"CHOOSE_SOURCE|대체\s*(?:위치|슬롯|자리)|BIN-B", re.I),
}


def norm(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text or "")).strip()


def names_doc(title, doc):
    """인용 제목이 그 문서를 대나 — 같거나, 여섯 자 이상인 제목이 문서 제목의 앞부분이다(설계서 §3.4)."""
    t, d = norm(title), norm(doc)
    return bool(t) and (t == d or (len(t) >= 6 and d.startswith(t)))


def head_value_with(pattern, answer, label):
    for line in (answer or "").splitlines()[:HEAD_LINES]:
        match = pattern.match(line)
        if match and match.group(1) == label:
            return match.group(2)
    return None


def loose_lines(answer, label):
    """`[(줄 번호, 줄)]` — 느슨한 탐지에 걸린 그 표지의 줄 전부."""
    return [(i, line) for i, line in enumerate((answer or "").splitlines())
            if (m := LOOSE.match(line)) and m.group("label") == label]


def marker_bucket(row):
    """후보 밖(M2)의 갈래. 풀렸으면 `None`, 아니면 `(갈래, 줄)` — 줄은 (ii) · (iii) 에서만."""
    if row["resolved"] is not None:
        return None
    if row["rawPick"] is not None:
        return ("iv", None)
    found = loose_lines(row["answer"], "권고")
    early = [line for i, line in found if i < HEAD_LINES]
    if early:
        return ("ii", early[0])
    if found:
        return ("iii", found[0][1])
    return ("i", None)


def out_of_candidates_old(row):
    """옛 파서(`1005cd1` 앞)로 풀었으면 후보 밖이었나."""
    raw = head_value_with(HEAD_OLD, row["answer"], "권고")
    return raw is None or resolve(raw, row["aliases"]) is None


def decorations(answer):
    """`{표지: [꾸밈 종류]}` — 앞 12줄에서 느슨한 탐지가 처음 잡은 표지 줄마다. 꾸밈이 없으면 `["plain"]`."""
    out = {}
    for line in (answer or "").splitlines()[:HEAD_LINES]:
        m = LOOSE.match(line)
        if not m or m.group("label") in out:
            continue
        kinds = []
        if m.group("quote"):
            kinds.append("quote")
        if m.group("heading"):
            kinds.append("heading")
        listed = (m.group("list") or "").strip()
        if listed:
            kinds.append("numbered" if listed[0].isdigit() else "bullet")
        emph = m.group("emph")
        if emph:
            kinds.append("bold" if len(emph) == 2 else "italic")
        out[m.group("label")] = kinds or ["plain"]
    return out


def uncited_cause(row):
    """`UNCITED` 의 원인(설계서 §3.5) — a 아무것도 안 댐 · b khala 가 못 읽은 표기 · c 검증의 엄격함 · d 근거에 없는 문서.
    인용 여럿이 섞이면 하나라도 근거 문서에 맞을 때 c 다."""
    citations = row["response"]["citations"]
    if not citations:
        return "b" if CITELIKE.search(row["answer"] or "") else "a"
    docs = (row.get("diagnostics") or {}).get("evidenceDocs") or []
    if any(names_doc(c.get("title"), d) for c in citations for d in docs):
        return "c"
    return "d"


def bare_integers(rationale):
    """이유 글의 맨 정수 조각(설계서 §3.7). 대괄호 무리와 미리 박은 제외를 지운 뒤에 센다."""
    text = _GROUP.sub(" ", rationale or "")
    for pattern in EXCLUDE:
        text = pattern.sub(" ", text)
    return [m.group(0) for m in BARE.finditer(text)] + CIRCLED.findall(text)


def clean(response):
    """koshei 의 `requireClean` — 권고이고, 이유가 있고, 두 목록이 비었다."""
    return (response["outcome"] == "RECOMMENDED" and bool(response["rationale"])
            and response["uncitedSentences"] == [] and response["unverifiedClaims"] == [])


def reading_proxy(rationale):
    """기준 C1 의 자동 대리값 — (가) 설비의 근거와 (나) 사람의 현물 확인이 둘 다 이유 글에 있나."""
    return bool(rationale) and bool(EQUIPMENT.search(rationale) and HUMAN.search(rationale))


def names_removed(row, case):
    """투영이 뺀 조치를 표지 값이나 이유 글이 가리키나(M3 대리값). 인용 제목은 빼고 본다 — SOP-03 제목에 「대체 슬롯」이 있다."""
    text = _GROUP.sub(" ", (row["rawPick"] or "") + "\n" + (row["response"]["rationale"] or ""))
    return any(REMOVED_WORDS[r["action"]].search(text) for r in case["removed"])


# ── 표 — 사례 파일과 기록의 줄로 설계서 §3 의 수를 센다 ──

#: 모델에게 가는 글이 바이트까지 같은 `promptVersion` 무리(khala 편지 24) — 앞의 것을 뒤의 것으로 읽는다.
PROMPT_SAME = {"81377584ff5a": "73536dc7c9c0"}


def effective(row):
    """바깥 루프가 실제로 하는 것 — `RECOMMENDED` 면 그 후보, 아니면 ESCALATE(ESCALATED)."""
    response = row["response"]
    return response["candidateId"] if response["outcome"] == "RECOMMENDED" else ESCALATE


def version_tuple(row):
    v = row["response"]["versions"]
    return (v["modelId"], PROMPT_SAME.get(v["promptVersion"], v["promptVersion"]), v["corpusVersion"],
            v["searchFingerprint"])


def merge(records):
    """기록 여럿 → `(env, rows)`. 사례마다 뒤의 기록이 이긴다. **사례 파일 판이 다른 기록은 합치지 않는다.**"""
    hashes = {r["env"]["cases"]["scoringHash"] for r in records}
    if len(hashes) != 1:
        raise SystemExit(f"사례 파일 판이 다른 기록은 합치지 않는다: {sorted(hashes)}")
    rows = {}
    for record in records:
        for row in record["rows"]:
            rows[row["id"]] = row
    return records[-1]["env"], list(rows.values())


def score(doc, rows, readings=None):
    """사례 파일과 기록의 줄 → 설계서 §3 의 표.

    판독 값(설계서 §5)은 **분모의 사례를 다 읽었을 때만** 센다 — 덜 읽었으면 `None`(판독 전)이다. 덜 읽은 사례를 「아니다」로
    세면 판독이 자동 값보다 낮게 거짓말한다. 판독에서 받는 후보는 그 사례의 판독 목록에 있는 것뿐이다.
    """
    cases = {c["id"]: c for c in doc["cases"]}
    by_id = {r["id"]: r for r in rows}
    readings = readings or {}
    listed = {(cid, r["candidate"]) for cid, c in cases.items() for r in c["reading"]}
    read = {(r["case"], r["candidate"]): bool(r.get("accept")) for r in readings.get("readings", [])}

    def ids(keep):
        return [cid for cid, c in cases.items() if c["repeatOf"] is None and keep(c)]

    def answered(cids):
        return [cid for cid in cids if cid in by_id and by_id[cid].get("response") is not None]

    def count(cids, hit):
        return (sum(bool(hit(cid)) for cid in cids), len(cids))

    def read_count(cids, table, hit=bool):
        if table is None or any(cid not in table for cid in cids):
            return None
        return count(cids, lambda cid: hit(table[cid]))

    def m4_read(expect, pick):
        needed = [(cid, pick[cid]) for cid in expect if (cid, pick[cid]) in listed]
        if "readings" not in readings or any(key not in read for key in needed):
            return None
        return count(expect, lambda cid: pick[cid] in cases[cid]["expect"] or read.get((cid, pick[cid]), False)
                     and (cid, pick[cid]) in listed)

    subsets = {"all": ids(lambda c: True), "core": ids(lambda c: c["tier"] == "core"),
               "extended": ids(lambda c: c["tier"] == "extended"), "unseen": ids(lambda c: not c["seen"])}
    # 실패 · 빠짐 · 판 칸은 반복(R02)까지 본다 — 비율에서 빠질 뿐 판의 일부다
    report = {"failed": {cid: by_id[cid].get("failed") for cid in cases
                         if cid in by_id and by_id[cid].get("response") is None},
              "missing": [cid for cid in cases if cid not in by_id]}
    for name, cids in subsets.items():
        done = answered(cids)
        expect = [cid for cid in done if cases[cid]["expect"] is not None]
        choice = [cid for cid in expect if _real_choice(cases[cid], by_id[cid])]
        forbid = [cid for cid in done if cases[cid]["mustNotPick"]]
        escalated = [cid for cid in expect if cases[cid]["procedureDocs"] and by_id[cid]["resolved"] == ESCALATE]
        pick = {cid: by_id[cid]["resolved"] for cid in done}
        outcome = {cid: by_id[cid]["response"]["outcome"] for cid in done}
        report[name] = {
            "answered": len(done),
            "outcomes": _count(outcome.values()),
            "M1": count(done, lambda cid: outcome[cid] == "RECOMMENDED"),
            "M2": count(done, lambda cid: pick[cid] is None),
            "M2old": count(done, lambda cid: out_of_candidates_old(by_id[cid])),
            "M2buckets": _count((marker_bucket(by_id[cid]) or ("resolved",))[0] for cid in done),
            "M2byOutcome": _count(f'{outcome[cid]}/{"out" if pick[cid] is None else "in"}' for cid in done),
            "M4marker": count(expect, lambda cid: pick[cid] in cases[cid]["expect"]),
            "M4read": m4_read(expect, pick),
            "M4effect": count(expect, lambda cid: effective(by_id[cid]) in cases[cid]["expect"]),
            "M4choice": count(choice, lambda cid: pick[cid] in cases[cid]["expect"]),
            "baselineM4": (len(expect), len(expect)),
            "forbiddenMarker": count(forbid, lambda cid: pick[cid] in cases[cid]["mustNotPick"]),
            "forbiddenEffect": count(forbid, lambda cid: outcome[cid] == "RECOMMENDED"
                                     and by_id[cid]["response"]["candidateId"] in cases[cid]["mustNotPick"]),
            "groundedEscalation": count(escalated, lambda cid: _grounded(by_id[cid], cases[cid])),
        }
    done = answered(subsets["all"])
    removed = [cid for cid in done if cases[cid]["removed"]]
    cleaned = [cid for cid in done if clean(by_id[cid]["response"])]
    recommended = [cid for cid in done if by_id[cid]["response"]["outcome"] == "RECOMMENDED"]
    approve = [cid for cid in cleaned if by_id[cid]["kinds"].get(by_id[cid]["resolved"]) == "APPROVE_REMEDY"]
    report["M3proxy"] = {cid: names_removed(by_id[cid], cases[cid]) for cid in removed}
    report["M3auto"] = count(removed, lambda cid: report["M3proxy"][cid])
    report["M3read"] = read_count(removed, readings.get("m3"))
    report["uncited"] = {cid: {"cause": uncited_cause(by_id[cid]), "marker": _marker_kind(by_id[cid])}
                         for cid in done if by_id[cid]["response"]["outcome"] == "UNCITED"}
    report["decorations"] = {cid: decorations(by_id[cid]["answer"]) for cid in done}
    report["decorationCounts"] = {
        "all": decoration_counts(report["decorations"]),
        "unseen": decoration_counts({cid: v for cid, v in report["decorations"].items() if not cases[cid]["seen"]}),
    }
    report["cards"] = count(done, lambda cid: all(label in parse_card(by_id[cid]["answer"]) for label in LABELS))
    report["cardsRead"] = read_count(done, readings.get("cards"))
    report["nullRationale"] = count(recommended, lambda cid: by_id[cid]["response"]["rationale"] is None)
    report["bareIntegers"] = {cid: bare_integers(by_id[cid]["response"]["rationale"]) for cid in cleaned}
    report["bareRatio"] = count(cleaned, lambda cid: report["bareIntegers"][cid])
    report["bareRatioApprove"] = count(approve, lambda cid: report["bareIntegers"][cid])
    report["bareRatioRead"] = read_count(cleaned, readings.get("bareIntegers"))
    report["readingProxy"] = {cid: {r["candidate"]: reading_proxy(by_id[cid]["response"]["rationale"])
                                    for r in cases[cid]["reading"] if by_id[cid]["resolved"] == r["candidate"]}
                              for cid in done if cases[cid]["reading"]}
    report["repeat"] = {c["id"]: _same(by_id.get(c["repeatOf"]), by_id.get(c["id"]))
                        for c in cases.values() if c["repeatOf"]}
    groups = {}
    for cid in cases:
        if cid in by_id and by_id[cid].get("response") is not None:
            groups.setdefault(version_tuple(by_id[cid]), []).append(cid)
    report["versions"] = [{"tuple": list(t), "cases": groups[t]}
                          for t in sorted(groups, key=lambda t: tuple("" if x is None else x for x in t))]
    # ⚠ 모르는 판(`None`)은 같다고 못 한다 — 한 벌이어도 `None` 이 섞이면 머리 수치가 아니다
    report["headline"] = (len(groups) == 1 and None not in next(iter(groups))
                          and not report["failed"] and not report["missing"])
    return report


def _real_choice(case, row):
    """고를 것이 있는 사례 — ESCALATE 밖 후보가 있고, 모든 후보가 기대인 것은 아니다."""
    candidates = set(row["kinds"])
    return len(candidates) > 1 and not candidates <= set(case["expect"])


def _grounded(row, case):
    """검증된 인용이 그 사례의 절차 문서를 대나(설계서 §3.4)."""
    return any(c.get("verified") is True and any(names_doc(c.get("title"), d) for d in case["procedureDocs"])
               for c in row["response"]["citations"])


def _marker_kind(row):
    if row["resolved"] is None:
        return "none"
    return "escalate" if row["resolved"] == ESCALATE else "other"


def _same(first, second):
    if not first or not second or first.get("response") is None or second.get("response") is None:
        return None
    return {"marker": first["resolved"] == second["resolved"],
            "outcome": first["response"]["outcome"] == second["response"]["outcome"],
            "versions": version_tuple(first) == version_tuple(second)}


def _count(values):
    out = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items()))


ROWS = (("M1 유효 선택", "M1", None), ("M2 후보 밖", "M2", None), ("M2 옛 파서", "M2old", None),
        ("M4 표지 · 자동", "M4marker", "baselineM4"), ("M4 표지 · 판독", "M4read", "baselineM4"),
        ("M4 효과", "M4effect", "baselineM4"), ("M4 고를 것 있는 사례", "M4choice", None),
        ("금지 · 표지", "forbiddenMarker", "zero"), ("금지 · 효과", "forbiddenEffect", "zero"),
        ("근거 있는 넘김", "groundedEscalation", None))
SUBSETS = (("전체", "all"), ("핵심", "core"), ("확장", "extended"), ("본 사례 뺌", "unseen"))


def fraction(pair):
    return "판독 전" if pair is None else f"{pair[0]}/{pair[1]}"


def decoration_counts(per_case):
    """`{표지: {꾸밈 종류: 답 수}}` — 한 줄에 꾸밈이 둘이면 둘 다 센다."""
    out = {}
    for labels in per_case.values():
        for label, kinds in labels.items():
            for kind in kinds:
                out.setdefault(label, {}).setdefault(kind, 0)
                out[label][kind] += 1
    return {label: dict(sorted(kinds.items())) for label, kinds in out.items()}


def report_lines(report):
    """사람이 읽는 모양. 기준선은 「늘 ESCALATE」다(설계서 §2.1)."""
    lines = ["머리 수치 — 판 칸 한 벌 · 실패 없음 · 빠짐 없음" if report["headline"]
             else "머리 수치 아님 — 판 칸이 갈렸거나 실패 · 빠짐이 있다",
             f'{"":22}' + "".join(f"{label:>10}" for label, _ in SUBSETS) + f'{"기준선":>10}',
             f'{"답한 사례":22}' + "".join(f'{report[key]["answered"]:>10}' for _, key in SUBSETS)]
    for label, key, base in ROWS:
        all_ = report["all"][key]
        baseline = (report["all"][base] if base == "baselineM4" else
                    (0, all_[1]) if base == "zero" else None)
        lines.append(f"{label:22}" + "".join(f"{fraction(report[s][key]):>10}" for _, s in SUBSETS)
                     + (f"{fraction(baseline):>10}" if baseline else ""))
    lines += [
        "결과 분포 " + json.dumps(report["all"]["outcomes"], ensure_ascii=False),
        "M2 갈래 " + json.dumps(report["all"]["M2buckets"], ensure_ascii=False)
        + " · 결과별 " + json.dumps(report["all"]["M2byOutcome"], ensure_ascii=False),
        f'M3 대리값(뺀 조치를 가리킴) 자동 {fraction(report["M3auto"])} · 판독 {fraction(report["M3read"])} '
        + json.dumps(report["M3proxy"], ensure_ascii=False),
        "UNCITED 원인 × 표지 " + json.dumps(report["uncited"], ensure_ascii=False),
        "꾸밈(표지 × 종류) " + json.dumps(report["decorationCounts"]["all"], ensure_ascii=False)
        + " · 본 사례 뺌 " + json.dumps(report["decorationCounts"]["unseen"], ensure_ascii=False),
        f'카드 완결 자동 {fraction(report["cards"])} · 판독 {fraction(report["cardsRead"])} · 이유 없는 권고 '
        f'{fraction(report["nullRationale"])}',
        f'맨 정수 자동 {fraction(report["bareRatio"])} · 판독 {fraction(report["bareRatioRead"])} · APPROVE_REMEDY 자동 '
        f'{fraction(report["bareRatioApprove"])} · 조각 '
        + json.dumps({cid: hits for cid, hits in report["bareIntegers"].items() if hits}, ensure_ascii=False),
        "판독 대리값(C1) " + json.dumps(report["readingProxy"], ensure_ascii=False),
        "반복 " + json.dumps(report["repeat"], ensure_ascii=False),
        "판 칸 " + json.dumps(report["versions"], ensure_ascii=False),
        "실패 " + json.dumps(report["failed"], ensure_ascii=False) + " · 빠짐 " + json.dumps(report["missing"]),
    ]
    return lines


def main(argv=None):
    """기록(여럿이면 사례마다 뒤의 것)을 지금 사례 파일로 다시 센다. 사례 파일이 기록 때와 다르면 멈춘다."""
    args = list(sys.argv[1:] if argv is None else argv)
    drift_ok = "--allow-drift" in args
    paths = [a for a in args if a != "--allow-drift"] or [str(RECORD)]
    records = [json.loads(pathlib.Path(p).read_text(encoding="utf-8")) for p in paths]
    doc = load_cases()
    env, rows = merge(records)
    head = []
    if env["cases"]["scoringHash"] != scoring_hash(doc):
        if not drift_ok:
            raise SystemExit("사례 파일이 기록 때와 다르다 — 다시 세지 않는다(--allow-drift 로 켜면 머리에 적는다)")
        head.append("⚠ 사례 판이 다름 — 기록 때의 사례 파일로 잰 수치가 아니다")
    if not all(r.get("complete") for r in records):
        head.append("⚠ 끝나지 않은 기록이 섞였다(complete=false)")
    readings = None
    if READINGS.exists():
        readings = json.loads(READINGS.read_text(encoding="utf-8"))
        if readings.get("scoringHash") != scoring_hash(doc):
            head.append("⚠ 판독 파일이 다른 사례 판의 것이라 판독 값을 안 쓴다")
            readings = None
        elif sorted(readings.get("records") or []) != sorted(r["env"]["at"] for r in records):
            head.append("⚠ 판독 파일이 다른 기록들의 것이라 판독 값을 안 쓴다(판독의 records 와 다시 센 기록의 env.at)")
            readings = None
    for line in head + report_lines(score(doc, rows, readings)):
        print(line)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
