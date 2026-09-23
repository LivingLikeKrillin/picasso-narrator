"""기록 하나를 스택 없이 되감아 보인다 — `RESULTS.md` 「다시 재는 법」의 옆.

    python eval/replay.py                       # eval/last-answers.json 의 요약과 카드와 채점표
    python eval/replay.py --show G3 S1 Q3       # 그 줄의 본문까지
    python eval/replay.py path/to/answers.json --goldenset <그 판의 goldenset.json>

⛔ **실물 판은 20~40분이고 두 번 버렸다**(2026-09-20 벽 120 · 2026-09-22 생성 불가). 보이는
자리에서 그 판을 돌릴 수는 없다. 채점이 순수 함수라 기록만 있으면 스택 없이 다시 세듯이,
답과 카드도 기록에 있으므로 스택 없이 다시 읽는다.

**여기서 새로 만드는 수는 없다.** 줄의 값을 옮겨 보일 뿐이고 채점표는 `rescore.report` 가
찍는다. 요약 줄이 기록보다 낫게 보이는 순간 되감기가 측정을 대신하게 된다.
"""

import argparse
import io
import json
import sys

sys.path.insert(0, ".")

from eval.rescore import load_rows, report
from eval.run import load
from recorder.card import LABELS


def summary_line(row):
    """한 줄의 요약. **없는 칸은 빈 자리로 둔다** — I 판(`722bebe`)에는 `card` 가 없고, 가장 이른
    판(`653defc`)에는 `latencies` 도 `kind` 도 없다(2026-09-22 실측). 한 모양만 읽으면 기준선
    판을 되감을 수 없다."""
    wall = max(row.get("latencies") or [0])
    card = row.get("card") or {}
    marks = []
    if row.get("violations"):
        marks.append("어긋남:" + ",".join(row["violations"]))
    if row.get("truthHit"):
        marks.append("정답:" + row["truthHit"][0])
    if row.get("reason"):
        marks.append("사유=" + row["reason"])
    head = (f'{row["id"]:3} {row.get("kind", ""):8} {row.get("outcome", ""):17} {wall:6.0f}초  '
            f'인용 {row.get("verified", 0)}/{row.get("citations", 0):<3} '
            f'답 {row.get("answerLen", 0):5}자  카드 {len(card)}/{len(LABELS)}')
    return (head + "  " + "  ".join(marks)).rstrip()


def card_lines(row):
    """카드 다섯 줄. **없으면 없다고 말한다** — 지어내지 않는다(`recorder/card.py`)."""
    card = row.get("card") or {}
    if not card:
        return [f'{row["id"]}: 카드 없음']
    return [f'{row["id"]} {label}: {card.get(label, "(없음)")}' for label in LABELS]


def replay(rows, env, show=()):
    """요약 줄 전부, 줄마다 카드(없으면 「카드 없음」), 고른 줄의 본문. 순서대로 한 목록이다."""
    out = ["환경 " + (json.dumps(env, ensure_ascii=False) if env else "없음 (env 이전 기록)"), ""]
    out += [summary_line(row) for row in rows]
    out.append("")
    for row in rows:
        out += card_lines(row)
        out.append("")
    for row in rows:
        if row["id"] in show:
            out += [f"===== {row['id']} 본문 =====", row.get("answer") or "(답 없음)", ""]
    return out


def unknown_ids(rows, show):
    """`--show` 가 든 것 중 기록에 없는 id. ⛔ **경로를 `--show` 뒤에 적으면 경로가 id 로 읽힌다**
    (Chunk 2 검토, 2026-09-22) — 그러면 기본 기록이 되감기고, 엉뚱한 판의 그럴듯한 되감기가 아무
    말 없이 나온다. 기록에 없는 id 는 이름을 들어 멈춘다."""
    return sorted(set(show) - {row["id"] for row in rows})


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python eval/replay.py",
                                     description="기록 하나를 스택 없이 되감아 보인다.")
    parser.add_argument("path", nargs="?", default="eval/last-answers.json")
    parser.add_argument("--show", nargs="*", default=[], metavar="ID", help="본문까지 보일 줄")
    parser.add_argument("--goldenset", default="eval/goldenset.json",
                        help="옛 판을 되감을 때 그때의 골든셋 (예: git show <커밋>:eval/goldenset.json)")
    args = parser.parse_args(argv)
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    rows, env = load_rows(args.path, goldenset=args.goldenset)
    unknown = unknown_ids(rows, args.show)
    if unknown:
        raise SystemExit(f"모르는 줄: {', '.join(unknown)} — 이 기록에 없는 id 다. "
                         "경로를 --show 뒤에 적었다면 --show 앞으로 옮긴다")
    for line in replay(rows, env, show=set(args.show)):
        print(line)
    report(load(args.goldenset), rows, env)


if __name__ == "__main__":
    main()
