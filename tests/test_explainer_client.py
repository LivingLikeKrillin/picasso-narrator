"""Nexus 를 부르는 것 — `BOUNDARY.md` §3.

전송은 주입받는다. 이 조각의 관심사가 아니고, 시험이 실물 스택 없이 물려야 한다.
"""

from explainer.client import INCIDENT_EXCLUDED, nexus_client


def _capture():
    seen = {}

    def transport(method, url, headers, payload):
        seen.update(method=method, url=url, headers=headers, payload=payload)
        return 200, {"success": True, "data": {"citations": []}}

    return seen, transport


def test_질의는_선언된_테넌트로만_나간다():
    """요청이 범위를 넓히지 못한다 — 서버가 토큰으로 정한 범위 밖을 부르면 조용히
    `default` 로 좁혀진다(2026-09-18 실측). 그래도 **부르는 쪽이 아무 데나 묻지
    않는 것**이 규율이다. 넓히려면 선언을 고친다."""
    seen, transport = _capture()
    search = nexus_client("http://localhost:8000", token="t", tenant="picasso", transport=transport)

    search("깨진 사전 조건: 파지 없음")

    assert seen["url"].endswith("/search/answer")
    assert seen["payload"]["tenant"] == "picasso"
    assert seen["payload"]["query"] == "깨진 사전 조건: 파지 없음"
    assert seen["headers"]["Authorization"] == "Bearer t"


def test_근거_예산은_답변_경로의_것을_쓴다():
    """**8 은 저쪽이 검색 전용 경로에 정한 값이지 답변 경로의 값이 아니다.**

    Nexus 가 `AnswerRequest` 주석에 적어 뒀다 — 답변 경로의 예산은 **20** 이고,
    10 에서 자르다 놓친 것을 재서 올린 값이다(「12개는 코퍼스에 다 있었고 랭킹도
    20 안에 다 갖고 있었다 — 우리가 10에서 자르고 있었을 뿐이다」).

    ⛔ **내가 8 을 보내고 있었다** (실측 2026-09-19). 불투명한 정지 코드 건에서
    그 코드를 설명하는 문서는 **찾아왔는데 도입부 덩어리만** 왔다. 코드표가 든
    덩어리는 9~14위라 8 에서 잘렸고, 모델은 「제공된 근거에서 확인할 수 없습니다」
    라고 정확히 답했다. **지어내지 않은 것은 옳은데, 줄 것을 안 준 것은 내 쪽이다.**

        k= 8   문서 덩어리 1개(도입부)  · 코드가 든 덩어리 없음
        k=20   문서 덩어리 3~4개        · 코드가 든 덩어리 9~14위
    """
    calls = []
    client = nexus_client("http://x", token="t", tenant="picasso",
                          transport=lambda m, u, h, b: calls.append(b) or (200, {"data": {}}))

    client("질의")

    assert calls[0]["top_k"] == 20


def test_사건_질의는_설계_문서를_빼고_묻는다():
    """⛔ **설계 일지 한 편이 상위 20 중 다섯에서 일곱 자리를 매번 차지한다**
    (khala 실측 2026-09-20, `nexus/search/doc_type_filter.py`). 이 층의 I 판 인용 72건
    중 21건이 그 문서였다. 사건 질의의 청중은 운영자인데 그 문서는 설계 기록이다.

    **자리를 비우는 것이지 맞는 문서를 올리는 것이 아니다.** 절차 문서가 검색에 안 오는
    문제는 따로 열려 있다 — khala 가 그 구분을 자기 쪽 주석에도 적었다.

    **운영자 질의에는 안 보낸다.** 그때는 설계 문서도 답할 값이 있다.
    """
    sent = []

    def transport(method, url, headers, body):
        sent.append(body)
        return 200, {"success": True, "data": {}}

    nexus_client("http://x", token="t", tenant="picasso", transport=transport,
                 exclude_doc_types=INCIDENT_EXCLUDED)("사건 질의")
    nexus_client("http://x", token="t", tenant="picasso", transport=transport)("운영자 질의")

    assert sent[0]["exclude_doc_types"] == ["spec", "design_doc"]
    assert "exclude_doc_types" not in sent[1], "안 물었으면 키를 안 보낸다"


def test_식별자_채널은_물었을_때만_실린다():
    """⛔ **기본이 꺼짐이어야 측정이 선다** (khala 사전 등록 T2). 켜는 것이 기본이 되면
    대조군이 없어진다. 안 물었으면 키를 안 보낸다 — 빈 목록을 보내면 이 층이 물은 것으로
    저쪽 기록에 남는다."""
    sent = []

    def transport(method, url, headers, body):
        sent.append(body)
        return 200, {"success": True, "data": {}}

    nexus_client("http://x", token="t", tenant="picasso", transport=transport,
                 identifier_channel=True)("사건 질의")
    nexus_client("http://x", token="t", tenant="picasso", transport=transport)("대조군 질의")

    assert sent[0]["identifier_channel"] is True
    assert "identifier_channel" not in sent[1]
