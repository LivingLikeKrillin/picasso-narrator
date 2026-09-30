"""첫 결과 저장소 — 계약 0.6 §6. 같은 열쇠의 두 번째 요청에는 첫 결과를 돌려준다."""

from diagnose.store import LEASE, Busy, Claimed, Done, FirstResultStore

KEY = ("ep-1", 1, "sha256:" + "0" * 64)
FIRST = {"outcome": "RECOMMENDED", "candidateId": "ESCALATE"}
SECOND = {"outcome": "UNCITED", "candidateId": None}


def test_처음_온_열쇠는_잡는다(tmp_path):
    """임대는 koshei 의 하트비트 기한(30 초)과 같다 — 잡은 채 죽은 워커의 열쇠를, 그 죽음을 알아챈 Temporal 이
    다시 보낸 시도가 곧바로 넘겨받게."""
    store = FirstResultStore(tmp_path / "first.sqlite3")

    assert LEASE == 30.0
    assert store.claim(KEY, "w1", now=100.0) == Claimed("w1")


def test_끝난_열쇠는_첫_결과를_돌려주고_덮지_않는다(tmp_path):
    """**끝난 것은 바뀌지 않는다.** 늦게 끝낸 쪽이 적으려 해도 먼저 적힌 것이 돌아온다 — 같은 질문에
    두 답이 생겨도 밖에 나가는 것은 하나다."""
    store = FirstResultStore(tmp_path / "first.sqlite3")
    store.claim(KEY, "w1", now=100.0)

    assert store.complete(KEY, FIRST, raw_pick="ESCALATE", resolved_pick="ESCALATE", now=101.0) == FIRST
    assert store.complete(KEY, SECOND, raw_pick=None, resolved_pick=None, now=102.0) == FIRST
    assert store.claim(KEY, "w2", now=103.0) == Done(FIRST)


def test_잡힌_열쇠는_다른_쪽을_기다리게_한다(tmp_path):
    """워커가 여럿이어도 저장소는 하나다 — 같은 파일을 두 저장소 객체가 연다(프로세스 둘의 흉내)."""
    path = tmp_path / "first.sqlite3"
    FirstResultStore(path).claim(KEY, "w1", now=100.0)

    assert FirstResultStore(path).claim(KEY, "w2", now=110.0) == Busy("w1")


def test_임대가_지나면_넘겨받는다(tmp_path):
    """**잡은 것은 임대다.** 잡은 쪽이 임대 안에 알리지 않으면 다른 쪽이 넘겨받는다 — 잡은 채 죽은
    워커가 열쇠를 영영 막지 않게. 알리면(`touch`) 임대가 늘어난다."""
    store = FirstResultStore(tmp_path / "first.sqlite3", lease=60.0)
    store.claim(KEY, "w1", now=100.0)

    assert store.touch(KEY, "w1", now=150.0) is True
    assert store.claim(KEY, "w2", now=200.0) == Busy("w1")
    assert store.claim(KEY, "w2", now=211.0) == Claimed("w2")
    assert store.touch(KEY, "w1", now=212.0) is False, "넘겨받힌 쪽의 알림은 안 먹는다"


def test_놓으면_다시_잡을_수_있다(tmp_path):
    """실패했으면 놓는다 — 다음 시도가 임대를 기다리지 않고 바로 잡는다. 남의 것은 못 놓는다."""
    store = FirstResultStore(tmp_path / "first.sqlite3")
    store.claim(KEY, "w1", now=100.0)

    store.release(KEY, "w2")
    assert store.claim(KEY, "w3", now=101.0) == Busy("w1")
    store.release(KEY, "w1")
    assert store.claim(KEY, "w3", now=102.0) == Claimed("w3")
