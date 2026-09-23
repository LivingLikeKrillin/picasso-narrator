"""한 바퀴를 명령 한 줄로 — `SEQUENCES.md` 1.

    python -m receiver <한 벌 디렉터리> --out <기록 디렉터리> [--approve <승인 창구 URL>]

⛔ **한 바퀴(`once`)는 2026-09-22 까지 pytest 밖에서 돈 적이 없었다.** 부르는 것이 시험뿐이라
시퀀스 1 은 시험으로는 참이고 운영으로는 꺼져 있었다. 측정(`eval/measure.py`)은 질의를 하나씩
따로 물었지 바퀴를 돌지 않았다. 이 명령이 그 자리를 채운다.

**승인은 깃발이다.** `--approve` 가 없으면 시도하지 않는다 — `BOUNDARY.md` §6.7 의 「기본값
끔」이 이 한 줄이다. 켜면 대장(`approvals.jsonl`)이 같이 선다(§6.1).

**재는 것과 도는 것을 같게 둔다.** 검색 조건이 `eval/measure.py` 의 기본 실험군과 같다 —
사건 질의에서 설계 문서를 빼고(`INCIDENT_EXCLUDED`) 식별자 채널을 켠다(T2, 2026-09-20 채택).
여기만 다르게 두면 평가표의 수가 실제 운영의 것이 아니게 된다. ⚠ 저쪽 스크립트의 기본
실험군이 옮겨가면 여기도 같이 옮긴다 — 둘을 묶는 시험은 없다.
"""

import argparse
import os
import pathlib
import sys

from explainer.client import INCIDENT_EXCLUDED, nexus_client
from explainer.transport import http_transport
from receiver.approval import AttemptStore, approval_client
from receiver.approval_reply import ApprovalRefused
from receiver.export import MANIFEST, UnknownSchema
from receiver.idempotency import NoRunIdentity
from receiver.run import once
from recorder.store import RecordStore

EXPLANATIONS = "explanations.jsonl"
APPROVALS = "approvals.jsonl"


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m receiver",
        description="한 벌을 읽어 설명을 붙이고, 켜져 있으면 승인을 시도한다.")
    parser.add_argument("export", type=pathlib.Path,
                        help="picasso 가 낸 한 벌의 디렉터리 (manifest.json 이 있는 곳)")
    parser.add_argument("--out", type=pathlib.Path, required=True,
                        help="기록 디렉터리. explanations.jsonl 과 approvals.jsonl 이 여기 쌓인다")
    parser.add_argument("--nexus", default="http://localhost:8000", help="Nexus 주소")
    parser.add_argument("--token", default=os.environ.get("NEXUS_TOKEN"),
                        help="Nexus Bearer 토큰. 안 주면 NEXUS_TOKEN 환경 변수. 값은 저장소에 두지 않는다")
    parser.add_argument("--tenant", default="picasso")
    parser.add_argument("--approve", default=None, metavar="URL",
                        help="승인 창구. 주면 켜진다. 기본은 끔 (BOUNDARY.md 6.7)")
    parser.add_argument("--limit", type=int, default=3, help="설명 재시도 상한")
    return parser


def run(args, transport=http_transport):
    """한 바퀴. **전송은 주입받아** 시험이 실물 없이 물린다. 돌린 결과를 사람이 읽을 줄로 돌려준다.

    **한 벌이 아직 아니면 돌지 않고 말한다.** `once` 는 「아직 아니다」와 「새것 없음」을 둘 다
    0 으로 돌려주는데, 사람이 부르는 자리에서는 그 둘의 다음 행동이 다르다 — 앞은 기다리거나
    경로를 보고, 뒤는 할 일이 없다. 판이 낯설거나 구동 열쇠가 없는 한 벌도 같다 — 읽는 쪽이
    멈추는 것은 맞고(`receiver/export.py`), 여기서는 추적 정보가 아니라 **어느 파일의 무엇**인지를
    문장으로 말한다.

    **창구에 못 닿으면 설명은 적은 채로 멈추고 그렇게 말한다**(`BOUNDARY.md` §6.8). 멈춘 그 줄은
    대장에 안 남았으므로 다음 바퀴가 그 줄부터 다시 부른다. 조용히 0 으로 끝내면 사람이 승인이
    나간 줄 안다.

    ⚠ **이 바퀴의 시도를 대장의 자리로 자른다**(`before`). 같은 기록 디렉터리를 두 프로세스가
    쓰면 남의 줄이 이 바퀴의 것으로 보인다. 한 프로세스 전제다.
    """
    # ⛔ 코드에 박힌 개발 토큰이 잴 뿐인 층에 필요 없는 권한이 딸린 신원이었다 (khala 실측 2026-09-23). 값은 환경에서만 온다.
    if not args.token:
        raise SystemExit("Nexus 토큰이 없다. --token 이나 NEXUS_TOKEN 으로 준다. 값은 저장소에 두지 않는다 (.secrets/nexus-tokens.env)")
    if not (args.export / MANIFEST).exists():
        return [f"한 벌이 아직 아니다: {args.export / MANIFEST} 가 없다. "
                "내보내는 쪽이 아직 쓰는 중이거나 경로가 틀렸다"]
    args.out.mkdir(parents=True, exist_ok=True)
    store = RecordStore(args.out / EXPLANATIONS)
    search = nexus_client(args.nexus, token=args.token, tenant=args.tenant, transport=transport,
                          exclude_doc_types=INCIDENT_EXCLUDED, identifier_channel=True)
    attempts = AttemptStore(args.out / APPROVALS) if args.approve else None
    approve = approval_client(args.approve, transport) if args.approve else None
    before = len(attempts.load()) if attempts is not None else 0

    try:
        explained = once(args.export, store, search, limit=args.limit, approve=approve, attempts=attempts)
    except (UnknownSchema, NoRunIdentity) as unreadable:
        raise SystemExit(f"{args.export / MANIFEST}: {unreadable}. 이 한 벌은 안 읽는다. 내보내는 쪽의 판을 본다")
    except ApprovalRefused as refused:
        # ⛔ **먼저 허락된 시도를 삼키고 있었다 (Chunk 1 검토, 2026-09-22).** 제안이 둘인데 첫째가
        # 허락되고 둘째에서 끊기면 「대장에 안 남았다」라고만 말해 사람이 아무것도 안 나간 줄
        # 알았다 — 허락 하나는 이미 대장에 있고 picasso 가 그것을 실행 중이다. 이미 적힌 것을
        # 먼저 찍고, 안 남은 것은 멈춘 그 줄로 좁혀 말한다.
        landed = attempts.load()[before:] if attempts is not None else []
        raise SystemExit("\n".join(
            [_attempt_line(a) for a in landed]
            + [f"승인 창구에 못 닿았거나 내가 잘못 보냈거나 저쪽이 모르는 판을 냈다: {refused}. "
               f"설명은 {args.out / EXPLANATIONS} 에 적혔고 멈춘 그 줄은 대장에 안 남았다. "
               "다음 바퀴가 그 줄부터 다시 부른다"]))

    lines = [f"설명 {explained} 건 적음: {args.out / EXPLANATIONS}"]
    if attempts is None:
        lines.append("승인 시도 없음: --approve 를 안 줬다 (기본값 끔, BOUNDARY.md 6.7)")
        return lines
    made = attempts.load()[before:]
    if not made:
        lines.append("승인 시도 없음: 이 구동에서 부를 수 있는 제안이 없거나 전부 이미 불렀다")
    lines += [_attempt_line(a) for a in made]
    return lines


def _attempt_line(attempt):
    """대장의 한 줄을 사람이 읽을 한 줄로. 허락이든 거절이든 같은 모양이다."""
    verdict = "허락" if attempt.granted else f"거절 {attempt.refusal}"
    return f"승인 시도 {attempt.searchId} {attempt.robotId} {attempt.sawSkillTypes}: {verdict}"


def main(argv=None):
    # Windows 콘솔의 기본 코덱이 cp949 라 그대로 찍으면 한글이 깨진다.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    for line in run(build_parser().parse_args(argv)):
        print(line)
