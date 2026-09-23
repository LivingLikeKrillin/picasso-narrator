"""미처리분 고르기 — `BOUNDARY.md` §3.2.

**처리 표시는 읽는 쪽의 상태다.** 내보내는 쪽은 누가 어디까지 읽었는지 모르며,
알면 소비자마다 상태가 생긴다(picasso `docs/orchestration.md` §6).
"""

from receiver.idempotency import idempotency_key


def select_unprocessed(records, manifest, seen):
    """한 줄기에서 아직 설명이 안 붙은 것만. 순서는 열린 순서 그대로다.

    **줄기마다 따로 부른다.** 사건과 탐색은 다른 순간을 적고 짝이 대개 없으므로
    (`BOUNDARY.md` §4.1) 합쳐 거르면 갈래가 섞인다.

    :param seen: 이미 처리한 `(실행, 식별자)` 의 집합. 열쇠의 앞자리가 실행인
        이유는 뒷자리가 같은 시드의 재구동에서 그대로 반복되기 때문이다.
    """
    return [r for r in records if idempotency_key(r, manifest) not in seen]
