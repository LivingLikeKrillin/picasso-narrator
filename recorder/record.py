"""사건에 붙는 한 건 — `BOUNDARY.md` §3.4.

**빈 칸 하나로 접지 않는다.** 설명이 없는 이유 셋은 서로 다른 상태이고, 운영자가
그 셋을 구별하지 못하면 「근거가 없는 것」과 「시스템이 고장난 것」이 같아 보인다.
"""

from dataclasses import dataclass, field

from recorder.outcome import Outcome, classify


@dataclass(frozen=True)
class Record:
    """한 사건(또는 한 탐색 줄)에 붙는 설명 한 건."""

    key: tuple
    outcome: Outcome
    answer: str = ""
    citations: list = field(default_factory=list)
    #: 「생성 실패」일 때만 값이 있다. 「재시도 n/n」의 n 둘이다.
    attempts: int = 0
    limit: int = 0
    #: 왜 실패했나. **「안 끝났다」와 「키가 없다」는 다음 행동이 다르다** —
    #: 앞은 다시 눌러 볼 일이고 뒤는 사람이 가서 고칠 일이다.
    reason: str = ""
    #: 몇 초 걸렸나. **타임아웃을 올리면 느림이 가려지는데, 이 값이 남으면 안 가려진다.**
    #: 「빨리 죽었다」와 「오래 매달렸다」도 다른 고장이라 실패에도 적는다.
    elapsed: float = 0.0
    #: **저쪽이 스스로 잰 값.** `elapsed` 는 내 벽시계라 검색과 합성이 한 덩어리로
    #: 섞이는데, 응답의 `timing_ms` 가 그 둘을 갈라 놓는다(검색 0.1~1.8초 · 합성
    #: 7~45초, 2026-09-19 실측). 밖에서 초시계로 추정하던 것을 안에서 재 주고
    #: 있었고, 나는 그것을 버리고 있었다. 근거 조각은 **개수만** 적는다 —
    #: 본문은 35KB 고, 「몇 개를 넣어 몇 개를 인용했나」는 개수로 이미 답이 된다.
    diagnostics: dict = field(default_factory=dict)
    #: 어느 사건이었나 — 재발을 세는 데 필요한 칸만(`receiver/history.py`). 탐색 줄과
    #: 옛 기록에는 없다. **비어 있으면 「모른다」이지 「없었다」가 아니다.**
    subject: dict = field(default_factory=dict)


def _diagnostics(data):
    """저쪽이 적어 보낸 계측만 골라 낸다. **본문은 안 담는다.**"""
    return {
        "timing": dict(data.get("timing_ms") or {}),
        "evidence": len(data.get("evidence_snippets") or []),
        # ⛔ **검색이 준 것을 안 남기면 못 짚은 이유를 못 가른다 (2026-09-20 실측).**
        # J 판에서 G1 이 SOP-01 을 인용하지 않았는데, 검색이 안 줬는지 답이 빠뜨렸는지
        # 기록으로 가를 수 없었다. 답은 「근거에 없다」고 적었지만 그것은 모델의 진술이지
        # 관측이 아니다. **제목만 담는다** — 본문은 여전히 안 담는다(35KB 다).
        # ⛔ **「안 켰다」와 「켰는데 식별자가 없었다」를 가른다** (khala 사전 등록 §5.5 의
        # 음성 대조군). 한 값으로 뭉치면 처치가 조용히 무시된 것을 못 본다. 키가 없는 옛
        # 응답에서는 `None` 이고, 그것은 「그 판에는 이 칸이 없었다」다.
        "identifierChannel": data.get("identifier_channel"),
        "identifierChannelAsked": data.get("identifier_channel_asked"),
        "evidenceDocs": sorted({
            s.get("doc_title") for s in (data.get("evidence_snippets") or [])
            if isinstance(s, dict) and s.get("doc_title")
        }),
        "usage": dict(data.get("usage") or {}),
        # **갈래를 가른 값.** 판정만 적고 근거를 안 적으면 규칙을 고쳤을 때 옛 기록을
        # 다시 판정할 수 없다. 키가 없으면 `None` 으로 남긴다 — 거짓과 구별돼야 한다.
        "weak_evidence": data.get("weak_evidence"),
        # **그 판정을 만든 점수 둘.** `weak_evidence` 는 `top_distance > 0.48` **그리고**
        # `top_bm25 < 1.5` 일 때 선다. 판정만 담으면 **문턱에 겨우 걸린 것과 한참 밖인
        # 것이 같은 값으로 보인다.** 그 문턱은 아직 가설이고(표본 17 이 전부 지은 것,
        # 중간 구간 최대 0.470 과 문턱 0.48 사이가 0.010), **옮길 트리거를 볼 수 있는
        # 쪽은 질의를 지은 이쪽**이지 서버가 아니라 저쪽이 응답에 실었다(khala `#537`).
        #
        # ⚠ **`None` 은 0 이 아니다** — 그 경로가 **못 낸 것**이다. 0 으로 접으면
        # 「가장 가까운 것이 딱 붙어 있었다」로 읽힌다.
        "top_distance": data.get("top_distance"),
        "top_bm25": data.get("top_bm25"),
        # **저쪽이 코드로 판정한 둘.** 인용 쪽은 내 셈(`citations[].verified`)과 겹치는데,
        # 겹치는 것이 요점이다 — **갈리면 내 대표 수치가 틀린 것**이고 안 담으면 갈렸다는
        # 사실조차 안 보인다. 숫자 쪽은 내가 세는 것이 아예 없다: 답의 유의미한 숫자가
        # LLM 에게 보여준 것에 실재하는지를 저쪽이 값-일치로 본다(`nexus/llm/numbers.py`).
        # ⛔ **「지어낸 통계」로 읽으면 안 된다**(실측 2026-09-19). 이 층의 답에는 수치
        # 주장이 사실상 없고 숫자는 거의 전부 **인용의 절 번호**다(§15.148 · §3.2).
        # 걸리는 것은 대개 **안 본 절을 짚은 것**이고, 작지만 다른 축이다. 어느 숫자가
        # 걸렸는지는 못 본다 — 저쪽이 개수만 내보낸다.
        "unverified_citations": data.get("unverified_citations"),
        "unverified_numbers": data.get("unverified_numbers"),
    }


def from_failure(key, attempts, limit, reason="", elapsed=0.0, subject=None):
    """상한까지 해봤고 안 됐다.

    **몇 번인지를 함께 적는다.** 「실패」만 적으면 한 번 튄 것과 계속 죽어 있는
    것이 같아 보이고, 운영자가 다시 눌러 볼지 사람을 부를지 정하지 못한다.
    """
    return Record(
        key=key,
        outcome=Outcome.GENERATION_FAILED,
        attempts=attempts,
        limit=limit,
        reason=reason,
        elapsed=elapsed,
        subject=dict(subject or {}),
    )


def from_answer(key, data, attempts=0, limit=0, elapsed=0.0, subject=None):
    """Nexus 가 답한 것을 한 건으로 옮긴다. **갈래는 `classify` 가 정한다.**

    「근거 없음」도 여기로 온다 — **실패가 아니라 정상 출력**이라 재시도 횟수가
    붙지 않는다. 실패로 적으면 「근거 없음 비율 상승 → 코퍼스가 낡았다」는
    신호(§7)가 고장 건수로 오염되고, 운영자는 다시 눌러 보게 된다.
    """
    outcome = classify(data)
    # **「재시도 n/n」은 생성 실패의 표지다.** 성공이나 「근거 없음」에 붙으면 셋의
    # 구별이 흐려지고, 운영자가 「됐는데 세 번 걸렸나」를 읽게 된다.
    failed = outcome is Outcome.GENERATION_FAILED
    # **강등 응답의 본문은 설명이 아니라 근거 더미다.** 합성이 실패하면 Nexus 가
    # 「아래 근거를 직접 확인해주세요」와 함께 검색된 근거를 통째로 싣는다(2026-09-19
    # 실측 — 블록 17개, 35KB). 사람에게는 쓸모가 있지만 이 층의 「설명」 칸에 들어갈
    # 것은 아니다. 담으면 셋이 흐려진다 — 실패인데 답이 있는 것처럼 보이고, 기록이
    # 실패마다 수십 KB 씩 불어난다. 근거는 다시 물으면 다시 온다.
    return Record(
        key=key,
        outcome=outcome,
        answer="" if failed else (data.get("answer") or ""),
        citations=list(data.get("citations") or []),
        reason=data.get("llm_failure_reason") or "" if failed else "",
        attempts=attempts if failed else 0,
        limit=limit if failed else 0,
        elapsed=elapsed,
        diagnostics=_diagnostics(data),
        subject=dict(subject or {}),
    )
