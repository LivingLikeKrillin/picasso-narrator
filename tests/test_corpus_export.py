"""설명 기록을 코퍼스가 받을 모양으로 — khala 가 확정한 적재 입력(2026-09-22 회신)."""

import pytest

from corpus.export import DEFAULT_LABELS, body_without_card, cited_lines, document, export, filename, title
from recorder.outcome import Outcome
from recorder.record import Record
from recorder.store import RecordStore

KEY = ("run-2026-09-19T22:59:50.326061Z-1",
       "1b2afa127508ad837ab7599d00901e53c29ba50832c67b7928b42dfa1dde2b4a")
SUBJECT = {"robotId": "hum-05", "failureClass": "LOCALIZATION_LOST", "unitId": "PUMP-01.travel",
           "at": "2026-09-06T00:01:40Z", "digest": KEY[1]}
ANSWER = (
    "**절차:** SOP-05 다 [출처: SOP-05 자기 위치 상실 복구, 3. 가장 먼저 보는 것]\n"
    "**먼저:** 적재 상태부터 [출처: SOP-05 자기 위치 상실 복구, 3. 가장 먼저 보는 것]\n"
    "**금지:** 수동 이동 금지 [출처: SOP-05 자기 위치 상실 복구, 3. 가장 먼저 보는 것]\n"
    "**갈림:** recurrenceSeen [출처: picasso — 표준 용어 사전 (Glossary), 2. 인터페이스 계약]\n"
    "**근거 세기:** E0 [출처: 운영 시나리오 명세서, 2. 근거 등급]\n"
    "\n---\n\n"
    "**원인 후보 순위**\n\n1순위 — 실제 위치추정 유실이다."
)
CITATIONS = [
    {"title": "SOP-05 자기 위치 상실 복구", "section": "3. 가장 먼저 보는 것", "verified": True,
     "provenance_tier": "authored"},
    {"title": "운영 시나리오 명세서", "section": None, "verified": False, "provenance_tier": "authored"},
]
HUM04 = {"robotId": "hum-04", "failureClass": "GRASP_FAILED", "unitId": "RACK-204.S01"}


def _given(key=KEY, subject=SUBJECT, answer=ANSWER):
    return Record(key=key, outcome=Outcome.GIVEN, answer=answer, citations=CITATIONS, elapsed=118.2,
                  diagnostics={"usage": {"model": "claude-sonnet-5"}, "evidence": 38, "weak_evidence": False},
                  subject=dict(subject))


def test_한_건이_파일_하나이고_머리말이_적재_모양이다(tmp_path):
    """khala 가 확정한 모양이다 — 마크다운 + YAML 머리말, `title` 에 사건 열쇠, `updated` 는 사건
    시각, `doc_type` 은 자유 문자열. **머리말은 질의가 못 읽으므로** 기체·분류·자리·시각을 본문
    한 절에도 적는다. 전체 해시는 본문에 있고 제목에는 앞 열두 자만 든다. 검증은 인용마다이므로
    갈래 문장은 몇 건 중 몇 건으로 센다."""
    store = RecordStore(tmp_path / "explanations.jsonl")
    store.append(_given())

    written, kinds = export(store, tmp_path / "out", doc_type="explanation")

    files = sorted((tmp_path / "out").glob("*.md"))
    assert (written, kinds, len(files)) == (1, {"GIVEN": 1}, 1)
    text = files[0].read_text(encoding="utf-8")
    _, front, body = text.split("---\n", 2)
    assert 'title: "narrator 설명 · hum-05 · LOCALIZATION_LOST · 2026-09-06T00:01:40Z · 1b2afa127508"' in front
    assert 'doc_type: "explanation"' in front
    assert "updated: 2026-09-06T00:01:40Z" in front
    assert 'labels: ["synthetic"]' in front
    assert "## 이 문서" in body
    assert "hum-05" in body and "LOCALIZATION_LOST" in body and "PUMP-01.travel" in body
    assert KEY[1] in body
    assert "LLM" in body and "사람이 쓴 문서가 아니" in body
    assert "인용 2 건 중 검증 1 건" in body


def test_머리말_값은_YAML_이_그대로_읽는다():
    """⛔ **Chunk 1 검토가 찾았다 (2026-09-22).** 제목과 종류를 맨 글자로 적으면 `: ` 나 `#` 이 드는
    순간 YAML 이 파일을 못 읽거나 제목을 조용히 자른다. 기체·분류·자리·시각은 저쪽 저장소에서
    그대로 온 검증 안 된 문자열이다. 따옴표로 감싼다 — JSON 문자열은 곧 YAML 의 큰따옴표 문자열이다.
    `updated` 는 저쪽 예시대로 맨 글자다."""
    yaml = pytest.importorskip("yaml")
    record = _given(subject={**SUBJECT, "failureClass": "FAIL: gripper #7"})

    front = yaml.safe_load(document(record, doc_type="a: b", labels=("synthetic", "x]y")).split("---\n", 2)[1])

    assert front["title"] == title(record)
    assert "FAIL: gripper #7" in front["title"]
    assert front["doc_type"] == "a: b"
    assert front["labels"] == ["synthetic", "x]y"]
    assert front["updated"]


def test_카드는_제_절에_있고_설명에는_다시_없다():
    """**절이 조각 경계다**(khala). 카드가 다른 것과 섞이면 절반만 실린 조각이 인용되고, 설명 절에
    카드가 다시 있으면 같은 문장이 두 조각에 산다."""
    text = document(_given(), doc_type="explanation", labels=DEFAULT_LABELS)

    sections = text.split("\n## ")
    card = next(s for s in sections if s.startswith("운영자 카드"))
    explanation = next(s for s in sections if s.startswith("설명"))

    assert "절차: SOP-05 다" in card and "근거 세기: E0" in card
    assert "SOP-05 다 [출처" not in explanation
    assert "1순위 — 실제 위치추정 유실이다." in explanation
    assert body_without_card(ANSWER).startswith("**원인 후보 순위**")


def test_카드_뒤에_같은_표지로_시작하는_본문_문장은_남는다():
    """⛔ **Chunk 1 검토가 찾았다 (2026-09-22).** 파서는 표지마다 첫 줄만 카드로 잡는데 걷어내기는
    앞 열두 줄의 모든 표지 줄을 걷었다. 표지로 시작하는 본문 문장이 카드에도 설명에도 없어졌다.
    파서와 같은 규칙으로 첫 것만 걷는다."""
    answer = "**절차:** A\n**금지:** 수동 금지\n산문\n**금지:** 이건 본문 문장이다\n마지막 줄"

    assert body_without_card(answer) == "산문\n**금지:** 이건 본문 문장이다\n마지막 줄"


def test_본문_구분선은_빈_줄_뒤에_두고_카드_없는_답의_머리는_안_걷는다():
    """구분선 바로 위 줄은 마크다운이 제목으로 읽는다 — 절이 하나 생기고 절은 조각 경계다. 그리고
    카드를 하나도 안 걷었으면 머리의 구분선은 답의 것이라 그대로 둔다."""
    assert body_without_card("문장\n---\n다음") == "문장\n\n---\n다음"
    assert body_without_card("---\n\n# 제목\n본문") == "---\n\n# 제목\n본문"


def test_답이_없는_기록도_문서로_내되_설명_없음이라_적는다(tmp_path):
    """⛔ **khala 가 짚었다 (2026-09-22).** 처음엔 답 없는 기록을 안 냈다. hum-04 가 세 번 섰고 하나가
    생성 실패면 코퍼스에는 두 건만 있고, 물으면 「두 번」이 오며 셋째가 빠졌다는 표시가 어디에도
    없다 — 값이 있는데 전달이 없는 것이다. 문서로 내되 설명 대신 「설명 없음」과 사유를 적는다."""
    store = RecordStore(tmp_path / "explanations.jsonl")
    store.append(_given())
    store.append(Record(key=("run-1", "a"), outcome=Outcome.NO_EVIDENCE,
                        answer="검색된 문서에 없는 것으로 보입니다.",
                        subject={**HUM04, "at": "2026-09-06T00:00:02Z"}))
    store.append(Record(key=("run-1", "b"), outcome=Outcome.GENERATION_FAILED, attempts=3, limit=3,
                        reason="timeout", subject={**HUM04, "at": "2026-09-06T00:00:03Z"}))

    written, kinds = export(store, tmp_path / "out", doc_type="explanation")

    assert written == 3
    assert kinds == {"GIVEN": 1, "NO_EVIDENCE": 1, "GENERATION_FAILED": 1}
    failed = (tmp_path / "out" / filename(store.load()[2])).read_text(encoding="utf-8")
    assert "## 설명 없음" in failed and "재시도 3/3" in failed and "timeout" in failed
    assert "## 운영자 카드" not in failed and "hum-04" in failed
    none = (tmp_path / "out" / filename(store.load()[1])).read_text(encoding="utf-8")
    assert "## 설명 없음" in none and "근거 없음" in none and "검색된 문서에 없는 것으로 보입니다." in none


def test_시각이_없는_줄은_updated_를_안_적고_본문에_모름이라_적는다():
    """탐색 줄의 기록에는 주체가 없다. 없는 시각을 지어내지 않는다 — 머리말에서 빼고 본문에는
    모름이라 적는다. khala 는 `updated` 없는 문서를 받고 시각 범위 질의에서 안 떨군다."""
    text = document(_given(key=("run-1", "search-4"), subject={}), doc_type="explanation",
                    labels=DEFAULT_LABELS)

    assert "updated:" not in text
    assert 'title: "narrator 설명 · 탐색 줄 search-4 · run-1"' in text
    assert "시각 모름" in text


def test_인용_줄은_khala_가_렌더한_표시를_제목_뒤에_그대로_붙인다():
    """khala 의 인용 항목이 `provenance_tier` 와 렌더된 `provenance_mark` 를 든다(2026-09-23). 표시 문자열은
    그쪽이 정하고 이 층은 옮기기만 한다 — 등급으로 문자열을 고르면 표면마다 다른 말이 된다. 없거나 빈
    문자열이면 지금과 한 글자도 안 다르다 — 사건 질의의 인용은 전부 사람 글이라 그렇다."""
    record = Record(key=KEY, outcome=Outcome.GIVEN, answer=ANSWER, elapsed=1.0, diagnostics={},
                    subject=dict(SUBJECT), citations=[
        {"title": "narrator 설명 · hum-02 · X", "section": "설명", "verified": True,
         "provenance_tier": "machine_written", "provenance_mark": " [LLM 이 만든 설명]"},
        {"title": "SOP-01 파지 실패와 잔여 파지 처리", "section": "5. 절차", "verified": True,
         "provenance_tier": "authored", "provenance_mark": ""},
        {"title": "운영 시나리오 명세서", "section": None, "verified": False},
    ])

    lines = cited_lines(record)

    assert lines[0] == "- narrator 설명 · hum-02 · X [LLM 이 만든 설명] · 설명 · 검증됨"
    assert lines[1] == "- SOP-01 파지 실패와 잔여 파지 처리 · 5. 절차 · 검증됨"
    assert lines[2] == "- 운영 시나리오 명세서 · 검증 안 됨"


def test_제목에_쉼표와_대괄호와_줄바꿈이_없다():
    """인용이 `[출처: 제목, 절]` 꼴이다. 제목의 쉼표는 절을 삼키고 대괄호는 인용을 닫는다 — 이 층의
    채점기(`eval/score.py::cited_refs`)도 같은 규칙으로 읽는다. 줄바꿈은 머리말을 깨뜨린다."""
    head = title(_given(subject={**SUBJECT, "failureClass": "A,B [c]\nD"}))

    assert "," not in head and "[" not in head and "]" not in head and "\n" not in head
    assert "A B (c) D" in head


def test_다시_내보내면_같은_파일을_덮어쓴다(tmp_path):
    """파일 이름은 열쇠에서 결정적으로 나온다. 구동 열쇠에 든 콜론은 파일 이름에 못 쓴다."""
    store = RecordStore(tmp_path / "explanations.jsonl")
    store.append(_given())

    export(store, tmp_path / "out", doc_type="explanation")
    export(store, tmp_path / "out", doc_type="explanation")

    assert len(list((tmp_path / "out").glob("*.md"))) == 1
    assert ":" not in filename(_given())


def test_문서_종류는_소유자_결정이라_기본값이_없다(tmp_path, capsys):
    """khala 결정 C 가 나기 전에 값을 지어 넣으면 그 이름으로 적재된다. 빈칸은 빈칸으로 둔다.
    표는 빈 문자열이면 안 붙인다 — 실제 사건을 설명하면 그렇게 뺀다(`synthetic` 은 내용이 지어낸
    것인가이지 누가 썼나가 아니다)."""
    from corpus.export import main

    store = RecordStore(tmp_path / "explanations.jsonl")
    store.append(_given())

    with pytest.raises(SystemExit):
        main([str(tmp_path / "explanations.jsonl"), "--out", str(tmp_path / "out")])

    main([str(tmp_path / "explanations.jsonl"), "--out", str(tmp_path / "out"),
          "--doc-type", "explanation", "--labels", ""])

    assert "내보낸 것 1" in capsys.readouterr().out
    text = next((tmp_path / "out").glob("*.md")).read_text(encoding="utf-8")
    assert "labels: []" in text
