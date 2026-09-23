"""한 바퀴 — `BOUNDARY.md` §3, §6.7.

v1 은 발행 없이 **적재 + 주기 스캔**이다. 이 함수가 그 한 바퀴이고, 주기를 도는
것은 부르는 쪽이 한다 — 여기서 돌면 시험이 시계를 들어야 한다.

⛔ **승인 시도가 이 바퀴에 안 물려 있었다 (2026-09-22 까지).** 조각(`candidates` ·
`try_approve` · `AttemptStore`)은 각자 시험으로 서 있었고 잇는 것만 없어서, 시퀀스 1 은
시험으로는 참이고 운영으로는 꺼져 있었다. 이제 `approve` 를 주면 물린다. **기본값은 끔이다**
(§6.7) — 안 주면 이 바퀴는 전과 똑같이 설명만 붙인다.
"""

from receiver.approval import pending, try_approve
from receiver.approval_reply import ApprovalRefused
from receiver.idempotency import RUN_KEY, NoRunIdentity
from receiver.pipeline import explain
from receiver.scan import scan


def once(directory, store, search, limit=3, approve=None, attempts=None):
    """한 벌을 보고 아직 설명이 안 붙은 것에 설명을 붙이고, 켜져 있으면 승인을 시도한다.

    **커서는 저장소다**(§3.2) — 적힌 것이 곧 처리한 것이고, 그래서 재기동해도
    같은 사건을 다시 설명하지 않는다. 처리 표시를 따로 두면 그 둘이 갈릴 때
    어느 쪽이 참인지 판정할 수 없다. 시도의 커서도 같다 — `AttemptStore` 가 곧 커서다.

    :param approve: 승인 창구(`approval_client`). **`None` 이 기본이고 그러면 시도하지
        않는다**(§6.7). 켜면 `attempts` 도 있어야 한다 — §6.1 이 감사를 요구하고, 대장
        없이 나간 시도는 사후 검토할 것이 없다.
    :param attempts: 시도의 대장(`AttemptStore`).
    :returns: 이번에 적은 설명의 건수. 한 벌이 아직 아니면 0 이다. 시도는 대장에서 센다.
    :raises ValueError: 창구는 줬는데 대장이 없을 때. **켜기 전에** 막는다.
    :raises ApprovalRefused: 창구에 못 닿았거나 내가 잘못 보냈을 때(§6.8). 설명은 이미
        적힌 뒤이고 그 시도는 대장에 안 적혔으므로, 다음 바퀴가 같은 줄을 다시 부른다.
    """
    if approve is not None and attempts is None:
        raise ValueError("승인 시도를 켜면 대장이 있어야 한다 (BOUNDARY.md 6.1 감사)")
    batch = scan(directory, store.seen())
    if batch is None:
        return 0
    records = explain(batch, search, limit, prior=store.subjects())
    for record in records:
        store.append(record)
    if approve is not None:
        attempt_pending(batch, attempts, approve)
    return len(records)


def attempt_pending(batch, attempts, approve, approver_id="narrator-1"):
    """이 구동에서 아직 안 부른 제안마다 한 번 시도하고 대장에 적는다.

    **설명 뒤에 도는 것은 순서의 규칙이 아니라 잃지 않기 위한 배치다.** 설명과 승인의 순서는
    고정이 아니고(`SEQUENCES.md` 1) 설명은 승인의 전제가 아니다(불변식 3) — 설명이 통째로
    죽어도 여기는 돈다. 다만 창구에 못 닿으면 예외로 멈추므로, 설명을 먼저 적어 두어야 그
    멈춤이 설명을 잃게 하지 않는다.

    **못 닿음을 거절로 적지 않는다**(§6.8). 거절은 200 이고 `Attempt` 로 남는다. 못 닿은
    것은 안 남고 올라간다 — 안 남았으므로 다음 바퀴가 다시 부른다. 하나씩 적으므로 중간에
    멈춰도 그전 것은 남는다.

    **400 과 모르는 판에서도 멈춘다 (Chunk 1 검토, 2026-09-22).** 못 닿음과 달리 둘은 결정적이라
    다음 바퀴도 같은 자리에서 같은 이유로 멈춘다 — 그래도 건너뛰지 않는다. 400 은 이 층이
    잘못 보낸 것이고 모르는 판은 저쪽이 판을 올린 것이라 둘 다 사람이 봐야 하고, 요청 모양이
    줄마다 같으므로 한 줄만 그런 경우는 없다. 건너뛰면 결함이 조용해진다. 대신 **멈춘 줄의
    이름을 문장에 싣는다** — 어디서 멈췄는지는 보여야 한다.
    """
    run_id = batch.manifest.get(RUN_KEY)
    if not run_id:
        raise NoRunIdentity(f"한 벌의 manifest 에 {RUN_KEY!r} 가 없다 — 시도를 가를 수 없다")
    for proposal in pending(batch.proposals, run_id, attempts.seen()):
        try:
            attempt = try_approve(proposal, approve, approver_id=approver_id, run_id=run_id)
        except ApprovalRefused as refused:
            raise ApprovalRefused(f"{proposal['searchId']} 에서 멈췄다: {refused}") from refused
        attempts.append(attempt)
