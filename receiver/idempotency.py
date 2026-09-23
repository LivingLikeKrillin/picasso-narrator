"""멱등의 열쇠 — `BOUNDARY.md` §3.4.

사건당 설명은 한 건이다. 그 「같은 사건」을 무엇으로 가르는가가 여기 있다.

⛔ **전제 — 구동 열쇠는 한 바퀴에 하나다 (2026-09-22).** 열쇠의 앞자리가 실행인 이유는 재실행을
가르는 것인데, 같은 실행 안에서 그 값이 흔들리면 반대 일이 난다 — 같은 한 벌이 매번 새 구동으로
보여 설명이 다시 붙고 승인이 다시 나간다. 승인은 제안을 소모하므로 두 번째는 거절로 오고, 일어나지
않은 거절이 대장에 쌓인다. picasso 의 살아 있는 한 벌이 150 밀리초마다 새 구동 열쇠를 찍고 있었고
저쪽이 찾아 고쳤다. 이쪽 시험은 픽스처 한 벌(구동 하나)로만 돌아 이것을 못 본다. 여기 적는 것은
검사가 아니라 전제다 — 앞자리는 내보내는 쪽이 정하고 이 층은 그것이 한 바퀴에 하나라고 믿는다.
"""

#: `manifest.json` 에서 실행을 가르는 열쇠. **아직 규약으로 확정되지 않았다**
#: (picasso `docs/orchestration.md` §6 은 manifest 의 존재만 정했고 내용은 비웠다).
#: 확정되면 이 한 줄만 바뀐다.
RUN_KEY = "runId"

#: 줄의 뒷자리로 쓸 칸, 보는 순서대로. 번들은 내용 해시가 있고 탐색 줄은 없다 —
#: 없는 쪽을 위해 이 층이 해시를 **계산하지 않는다**. 계산하면 그 값의 원천이 둘이 되고,
#: 두 값이 갈릴 때 어느 쪽이 같은 사건인지 판정할 수 없다.
IDENTITY_KEYS = ("digest", "searchId")


class NoIdentity(Exception):
    """줄에 열쇠로 쓸 것이 없다.

    그냥 넘기면 그 줄이 매 구동마다 다시 설명되거나 영영 안 된다. **어느 쪽이든
    조용하다** — 그래서 멈춘다.
    """


class NoRunIdentity(Exception):
    """한 벌에 실행 식별자가 없다. **추측해서 진행하지 않는다.**"""


def idempotency_key(record, manifest):
    """`(실행, 줄의 식별자)`. **식별자 하나로는 모자란다.**

    `digest` 도 `incidentId` 도 시드와 가상 시계에서 나오는 결정적 값이라 같은
    시드의 재실행에서 그대로 반복된다. 저쪽의 결함이 아니라 결정성의 의도된
    결과다 — 그러나 이쪽이 해시만으로 멱등을 걸면 **두 번째 실행부터 모든 사건이
    「이미 본 것」이 되어 설명이 하나도 안 붙는다.**

    :raises NoRunIdentity: manifest 에 실행 식별자가 없을 때. 조용히 넘어가면
        위 고장이 아무 신호 없이 일어난다.
    """
    run = manifest.get(RUN_KEY)
    if not run:
        raise NoRunIdentity(
            f"한 벌의 manifest 에 {RUN_KEY!r} 가 없다 — 재실행을 가를 수 없다"
        )
    for key in IDENTITY_KEYS:
        if key in record:
            return (run, record[key])
    raise NoIdentity(f"줄에 {IDENTITY_KEYS} 중 아무것도 없다")
