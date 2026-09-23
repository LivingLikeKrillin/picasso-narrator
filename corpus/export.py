"""설명 기록을 코퍼스가 받을 모양으로 내보낸다 — `BOUNDARY.md` §3.4 의 기록을 khala 적재 입력으로.

    python -m corpus.export <explanations.jsonl> --out <디렉터리> --doc-type <이름> [--labels synthetic]

⛔ **이 층의 설명은 아무 데로도 안 돌아가고 있었다 (2026-09-22).** 다음 사건의 검색도 운영자
질의도 지난 설명을 못 봤다. khala 가 적재 입력의 모양을 확정해 보냈고(마크다운 + YAML 머리말,
한 사건이 파일 하나, 인용은 `title` 을 읽는다), 자리와 표시와 이름 셋은 소유자 결정으로 남겼다.
그래서 여기는 **그 셋을 인자로 받고 나머지를 확정한다.** 테넌트는 적재 명령의 깃발이라 파일에
없다 — 그 깃발이 곧 「경로가 찍는」 표시다.

**절이 조각 경계다**(khala, 2026-09-22). 그래서 셋을 지킨다.

- 운영자 카드 다섯 줄은 제 절 하나에 둔다 — 다른 것과 섞으면 카드 절반만 실린 조각이 인용된다
- 어떤 절도 다른 절을 가리키기만 하지 않는다 — 조각은 혼자 가므로 필요한 값은 그 절 안에 적는다
- 기체·분류·시각은 제목에 들고, 자리까지 넷은 본문 한 절에 적는다 — 머리말은 질의가 못 읽는다

**새 사실을 만들지 않는다.** 기록에 있는 것만 옮긴다. ⛔ **답이 없는 기록도 문서로 낸다 (2026-09-22,
khala 가 짚었다).** 처음엔 안 냈는데, 그러면 hum-04 가 세 번 섰고 하나가 생성 실패일 때 코퍼스에는
두 건만 있고 물으면 「두 번」이 오며 셋째가 빠졌다는 표시가 어디에도 없다 — 값이 있는데 전달이
없는 것이다. 문서로 내되 설명 대신 「설명 없음」 절과 사유를 둔다. 「아직인가 · 실패인가 · 근거가
없어서인가」가 코퍼스에서도 갈린다(`BOUNDARY.md` §3.4).

**「LLM 이 만든 것」 표시를 `synthetic` 에 태우지 않는다**(khala). `synthetic` 은 내용이 지어낸
것인가이고 실제 사건을 설명하면 `--labels ""` 로 빼는 것이 옳다. LLM 이 만들었다는 것은 제목
머리와 「이 문서」 절, 그리고 적재의 테넌트가 든다.

**머리말은 YAML 이 읽는다.** 제목과 종류와 표는 저쪽에서 온 검증 안 된 문자열을 품으므로
따옴표로 감싼다 — JSON 문자열이 곧 YAML 의 큰따옴표 문자열이다. `updated` 는 저쪽 예시대로
맨 글자다.
"""

import argparse
import json
import pathlib
import re
import sys

from recorder.card import HEAD_LINES, LABELS, LINE, parse_card
from recorder.outcome import Outcome
from recorder.store import RecordStore

#: 제목 머리. **인용은 객체의 `title` 을 읽으므로** 모든 조각이 이 낱말을 들고 다닌다 — 출처 등급
#: (khala 결정 B)이 정해지기 전에도 출처가 제목에서 보인다.
TITLE_HEAD = "narrator 설명"

#: 자칭할 수 있는 표는 `synthetic` 하나다(khala `labels.py`). 미믹 시나리오의 사건을 푼 설명은
#: 「지어낸 문서」가 맞아 기본으로 붙인다. 실제 사건이면 `--labels ""` 로 뺀다 — 이 표는 내용이
#: 지어낸 것인가이지 누가 썼나가 아니다.
DEFAULT_LABELS = ("synthetic",)

#: 제목에 넣는 해시의 길이. 전체(64자)는 본문 「이 문서」 절에 있다.
DIGEST_HEAD = 12

#: 파일 이름에 못 쓰는 글자를 바꾼다. 구동 열쇠에 `:` 가 든다. ⚠ 안전하지 않은 글자 묶음을 `-`
#: 하나로 접으므로 서로 다른 열쇠가 한 파일이 될 수는 있다 — 지금 열쇠(sha256 · `search-N` ·
#: `run-<시각>-<n>`)로는 안 난다.
UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")

#: 답이 없는 갈래. 문서는 내되 설명 대신 「설명 없음」 절을 둔다.
UNANSWERED = (Outcome.NO_EVIDENCE, Outcome.GENERATION_FAILED)

#: 갈래의 이름. 사람이 읽는 자리에 사전 값 그대로 찍지 않는다.
KIND = {
    Outcome.GIVEN: "설명",
    Outcome.UNCITED: "인용 없는 답",
    Outcome.NO_EVIDENCE: "근거 없음",
    Outcome.GENERATION_FAILED: "생성 실패",
}

MARK = "picasso-narrator 가 Nexus 의 답변 경로(LLM)로 만든 설명이다. 사람이 쓴 문서가 아니고, 판정이 아니라 설명이다."


def export(store, out_dir, doc_type, labels=DEFAULT_LABELS):
    """기록마다 파일 하나. `(내보낸 수, 갈래별 수)`.

    파일 이름은 열쇠에서 결정적으로 나온다 — 다시 내보내면 같은 파일을 덮어쓴다.
    """
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written, kinds = 0, {}
    for record in store.load():
        kinds[record.outcome.value] = kinds.get(record.outcome.value, 0) + 1
        (out_dir / filename(record)).write_text(document(record, doc_type, labels),
                                                encoding="utf-8", newline="\n")
        written += 1
    return written, kinds


def filename(record):
    run, ident = record.key
    return f"{UNSAFE.sub('-', run)}__{UNSAFE.sub('-', ident)}.md"


def quoted(value):
    """YAML 이 그대로 읽는 문자열. JSON 문자열은 곧 YAML 의 큰따옴표 문자열이다."""
    return json.dumps(str(value), ensure_ascii=False)


def title(record):
    """사건을 가리키는 제목. **쉼표와 대괄호와 줄바꿈을 안 쓴다** — 인용이 `[출처: 제목, 절]` 꼴이라
    쉼표가 제목을 절에서 가르고 대괄호가 인용을 닫으며, 줄바꿈은 머리말을 깨뜨린다."""
    run, ident = record.key
    subject = record.subject or {}
    if subject.get("robotId"):
        parts = [TITLE_HEAD, subject["robotId"], subject.get("failureClass") or "분류 모름",
                 subject.get("at") or "시각 모름", ident[:DIGEST_HEAD]]
    else:
        parts = [TITLE_HEAD, f"탐색 줄 {ident}", run]
    flat = " · ".join(" ".join(str(part).split()) for part in parts)
    return flat.replace(",", " ").replace("[", "(").replace("]", ")")


def body_without_card(answer):
    """답에서 카드 줄을 뺀 나머지. 카드는 제 절에 따로 서므로 여기 다시 있으면 같은 문장이 두 조각에
    산다.

    ⛔ **파서와 같은 규칙으로 걷는다 (2026-09-22, 검토가 찾았다).** `parse_card` 는 표지마다 첫 줄만
    카드로 잡는다. 앞 열두 줄의 모든 표지 줄을 걷으면 표지로 시작하는 본문 문장이 카드에도 설명에도
    없어진다. 카드를 걷었을 때만 머리의 빈 줄과 구분선을 같이 걷고, 본문 한가운데의 구분선 앞에는
    빈 줄을 둔다 — 바로 위 줄이 제목으로 읽히면 절이 하나 생기고 절은 조각 경계다.
    """
    lines = (answer or "").splitlines()
    kept, seen = [], set()
    for i, line in enumerate(lines):
        match = LINE.match(line) if i < HEAD_LINES else None
        if match and match.group(1) not in seen:
            seen.add(match.group(1))
            continue
        kept.append(line)
    while kept and (not kept[0].strip() or (seen and kept[0].strip() == "---")):
        kept.pop(0)
    spaced = []
    for line in kept:
        if line.strip() in ("---", "===") and spaced and spaced[-1].strip():
            spaced.append("")
        spaced.append(line)
    return "\n".join(spaced).strip()


def kind_of(record):
    """갈래 한 문장. 검증은 인용마다이므로 몇 건 중 몇 건으로 센다 — 「검증된 인용이 붙어 있다」는
    검증 안 된 인용이 옆 절에 있을 때 거짓이었다(2026-09-22, 검토가 찾았다)."""
    if record.outcome is Outcome.GIVEN:
        cited = record.citations or []
        return f"설명 · 인용 {len(cited)} 건 중 검증 {sum(1 for c in cited if c.get('verified'))} 건"
    if record.outcome is Outcome.UNCITED:
        return "인용 없는 답 — 근거는 맞았으나 합성이 인용을 못 붙였다. 읽되 그대로 믿지 않는다"
    if record.outcome is Outcome.NO_EVIDENCE:
        return "근거 없음 — 검색이 이 사건에 맞는 근거를 못 찾았다"
    return f"생성 실패 — 재시도 {record.attempts}/{record.limit}, 사유 {record.reason or '모름'}"


def cited_lines(record):
    """인용 한 줄씩. **표시는 khala 가 렌더해 보낸 문자열을 그대로 붙인다**(`provenance_mark`, 2026-09-23) —
    등급으로 문자열을 고르면 표면마다 다른 말이 되므로 이 층은 옮기기만 한다. 없거나 빈 문자열이면 그대로다."""
    lines = []
    for c in record.citations or []:
        where = f"{c.get('title')}{c.get('provenance_mark') or ''}" + (f" · {c.get('section')}" if c.get("section") else "")
        lines.append(f"- {where} · {'검증됨' if c.get('verified') else '검증 안 됨'}")
    return lines or ["(인용 없음)"]


def document(record, doc_type, labels):
    """기록 하나를 문서 하나로. 절마다 혼자 가도 말이 되게 적는다."""
    run, ident = record.key
    subject = record.subject or {}
    head = title(record)
    front = ["---", f"title: {quoted(head)}", f"doc_type: {quoted(doc_type)}"]
    if subject.get("at"):
        front.append(f"updated: {subject['at']}")
    front += ["labels: [" + ", ".join(quoted(label) for label in labels) + "]", "---"]

    facts = (f"기체 {subject.get('robotId') or '모름'} · 분류 {subject.get('failureClass') or '모름'} · "
             f"자리 {subject.get('unitId') or '모름'} · 시각 {subject.get('at') or '모름'}")
    about = ["## 이 문서", "", MARK, f"사건 열쇠: 구동 {run} · 식별자 {ident}.", facts + ".",
             f"갈래: {kind_of(record)}."]

    if record.outcome in UNANSWERED:
        middle = ["## 설명 없음", "", f"이 사건에는 설명이 없다. {kind_of(record)}."]
        if record.answer:
            middle += ["", "답: " + record.answer.strip()]
        middle += ["", "설명이 없다는 것과 사건이 없었다는 것은 다르다 — 이 문서가 그 자리를 든다."]
    else:
        card = parse_card(record.answer)
        middle = (["## 운영자 카드", ""] + [f"{label}: {card.get(label, '카드 없음')}" for label in LABELS]
                  + ["", "## 설명", "", body_without_card(record.answer) or "(본문 없음)"]
                  + ["", "## 인용", ""] + cited_lines(record))

    diagnostics = record.diagnostics or {}
    made = ["## 생성", "", f"갈래 {record.outcome.value} · 벽시계 {record.elapsed}초"]
    model = (diagnostics.get("usage") or {}).get("model")
    if model:
        made.append(f"모델 {model}")
    if diagnostics.get("evidence") is not None:
        made.append(f"검색이 준 조각 {diagnostics['evidence']}")
    if diagnostics.get("weak_evidence") is not None:
        made.append(f"근거 약함 {diagnostics['weak_evidence']}")

    sections = [f"# {head}", ""] + about + [""] + middle + [""] + made
    return "\n".join(front + [""] + sections) + "\n"


def main(argv=None):
    # Windows 콘솔의 기본 코덱이 cp949 라 그대로 찍으면 한글이 깨진다. 인자 읽기 앞에 둔다 — 사용법과
    # 오류도 한글이다. 시험의 갈무리 스트림처럼 재설정을 못 받는 출력도 있어 못 받으면 그냥 찍는다.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    parser = argparse.ArgumentParser(
        prog="python -m corpus.export",
        description="설명 기록을 khala 적재 입력(마크다운 + YAML 머리말)으로 내보낸다.")
    parser.add_argument("records", type=pathlib.Path, help="explanations.jsonl")
    parser.add_argument("--out", type=pathlib.Path, required=True, help="파일이 쌓일 디렉터리")
    parser.add_argument("--doc-type", required=True,
                        help="문서 종류. 소유자 결정(khala 결정 C)이라 기본값이 없다")
    parser.add_argument("--labels", default=",".join(DEFAULT_LABELS),
                        help="쉼표로 잇는다. 자칭할 수 있는 것은 synthetic 뿐이다. 빈 문자열이면 안 붙인다")
    args = parser.parse_args(argv)
    labels = tuple(label.strip() for label in args.labels.split(",") if label.strip())
    written, kinds = export(RecordStore(args.records), args.out, args.doc_type, labels)
    by_kind = " · ".join(f"{KIND[Outcome(name)]} {count}" for name, count in kinds.items())
    print(f"내보낸 것 {written}" + (f" · {by_kind}" if by_kind else ""))
    print(f"자리: {args.out} · 문서 종류 {args.doc_type} · 표 {list(labels)}")


if __name__ == "__main__":
    main()
