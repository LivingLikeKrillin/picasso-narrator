"""옛 기록을 스택 없이 다시 센다 — `RESULTS.md` 「다시 재는 법」.

    python eval/rescore.py                      # eval/last-answers.json
    python eval/rescore.py path/to/answers.json
    python eval/rescore.py path/to/answers.json path/to/goldenset.json   # 옛 판은 그때의 골든셋과 함께

`rows` 를 `Record` 로 되돌려 순수 함수 `score` 에 넣는다. **인용 객체는 옛 판에 없다**
(제목만 저장했다). 그래서 인용 검증(지표 3)은 판 당시 출력의 값을 쓴다. 본문으로 세는 것
(절차 적중 · 어긋남 · 카드)과 **계측으로 세는 것**(검색이 준 문서)은 여기서 다시 센다.

⛔ **기록의 모양이 둘이다.** I 판(`722bebe`)은 줄의 배열이고 `env` 가 없다 — `measure.py`
가 `{"env", "rows"}` 로 바뀐 것이 그 2분 뒤였다. 둘 다 읽는다([rows_of]).
"""

import io
import json
import sys

sys.path.insert(0, ".")

from eval.run import load
from eval.score import cites_doc, score, section_match
from recorder.outcome import Outcome
from recorder.record import Record


def load_version(path="eval/goldenset.json"):
    """지금 골든셋의 판. 안 맞을 때 무엇과 무엇이 안 맞는지 말하려고 쓴다."""
    with open(path, encoding="utf-8") as handle:
        return json.load(handle).get("version")


def rows_of(saved):
    """`(rows, env)`. 옛 판은 배열이고 `env` 가 없다. 새 판은 `{"env", "rows"}` 다."""
    if isinstance(saved, list):
        return saved, None
    return saved["rows"], saved.get("env")


def records_from_rows(rows):
    """기록의 줄을 채점할 기록으로. 본문과 갈래와 **계측**을 되살린다.

    ⛔ **계측을 빠뜨리면 거기 기대는 지표가 조용히 `None` 이 된다 (2026-09-20 실측).**
    검색이 준 문서(`evidenceDocs`)와 근거 없는 수(`unverified_numbers`)가 계측에 있다.
    본문만 되살리던 판에서는 K 판 기록을 다시 세도 검색 쪽 수가 안 나왔다.
    """
    return [
        Record(key=("rescore", row["id"]), outcome=Outcome(row["outcome"]),
               answer=row.get("answer") or "", diagnostics=dict(row.get("diagnostics") or {}))
        for row in rows
    ]


def load_rows(path, goldenset="eval/goldenset.json"):
    """기록을 읽어 `(rows, env)`. **골든셋과 안 맞으면 멈춘다.**

    ⛔ **골든셋이 자라면 옛 기록은 다시 셀 수 없다.** 무엇이 안 맞는지를 말해야
    사람이 「옛 판으로 세려면 그 판의 골든셋을 꺼내라」를 안다.
    """
    rows, env = rows_of(json.load(open(path, encoding="utf-8")))
    entries = load(goldenset)
    if [e["id"] for e in entries] != [r["id"] for r in rows]:
        version = (env or {}).get("goldensetVersion")
        raise SystemExit(
            f"골든셋과 기록이 안 맞는다. 골든셋 {len(entries)} 항목 · 기록 {len(rows)} 줄. "
            f"기록이 돈 골든셋 판: {version if version is not None else '안 찍힌 판'}. "
            f"지금 골든셋 판: {load_version(goldenset)}. "
            "옛 판을 다시 세려면 그때의 골든셋을 함께 꺼낸다 "
            "(예: git show <커밋>:eval/goldenset.json)."
        )
    return rows, env


def report(entries, rows, env):
    """채점표를 찍는다. **본문으로 세는 것과 계측으로 세는 것만 다시 센다** — 인용 검증은
    판 당시 출력의 값이다(인용 객체는 기록에 없다)."""
    result = score(entries, records_from_rows(rows))
    print("환경", json.dumps(env, ensure_ascii=False) if env else "없음 (env 이전 기록)")
    for entry, row in zip(entries, rows):
        procedure = entry.get("procedure")
        if not procedure:
            continue
        # ⛔ **분모에서 빠진 줄을 빗나간 줄로 찍지 않는다.** `score` 는 설명이 안 선 답을
        # 분모에서 빼는데(`GENERATION_FAILED`) 이 표가 그것을 「문서✗」로 찍으면, 읽는
        # 사람이 세는 수와 아래 비율의 분모가 갈린다. 0 은 「해봤는데 못 했다」이고 없음은
        # 「잴 것이 없었다」라는 구별이 사람이 읽는 자리에서 무너진다.
        if Outcome(row["outcome"]) is Outcome.GENERATION_FAILED:
            mark = "설명 안 섬 (분모 밖)"
        else:
            answer = row.get("answer") or ""
            doc = "문서○" if cites_doc(answer, procedure["doc"]) else "문서✗"
            kind = section_match(answer, procedure["doc"], procedure["section"])
            mark = f'{doc} {"절○ " + kind if kind else "절✗   "}'
        print(f'{entry["id"]:3} {mark:20} 기대 {procedure["doc"][:24]} §{procedure["section"]}')
    print()
    print(f"절차 문서 인용  {result.procedure_doc_cited}  (센 것 {result.counted_procedures})")
    print(f"절차 절 인용    {result.procedure_section_cited}")
    print(f"  검색이 줬나   {result.procedure_doc_retrieved}  (검색 목록이 있는 줄 {result.counted_retrieved} 적중)")
    print(f"  받고 인용했나 {result.procedure_cited_when_retrieved}   <- 이 층의 몫")
    print(f"탐색 줄 절차    {result.search_procedure_cited}  (센 것 {result.counted_searches})")
    print(f"어긋남 없음     {result.contradiction_free}  (센 것 {result.counted_checked})")
    print(f"카드 완성       {result.cards_complete}")


def main(path="eval/last-answers.json", goldenset="eval/goldenset.json"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    rows, env = load_rows(path, goldenset=goldenset)
    report(load(goldenset), rows, env)


if __name__ == "__main__":
    main(*sys.argv[1:])
