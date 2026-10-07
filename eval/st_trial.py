"""검색 텍스트 칸 — 검색은 Q3, 질문은 쿼리에(두 경로 한 회차 실행). 설계서 `docs/superpowers/specs/2026-10-06-검색-텍스트-칸.md`.

**실행.** 설명 경로는 골든셋 열다섯을 항목마다 두 실험군(G0 오늘 그대로 · GS 같은 질의에 `search_text` = Q3)으로, 진단 경로는 권고
사례 스물하나(반복 R02 뺌)를 사례마다 두 실험군(D0 오늘 그대로 · DS 같은 질의와 답변 컨텍스트에 `search_text` = Q3)으로 잇달아 부른다::

    KHALA_ROOT=<khala 저장소> python -m eval.st_trial run g-1 --path g --out eval/st/g-1.json
    KHALA_ROOT=<khala 저장소> python -m eval.st_trial run d-1 --path d --out eval/st/d-1.json
    KHALA_ROOT=<khala 저장소> python -m eval.st_trial run g-1r --path g --out eval/st/g-1r.json --only G4:GS,G7   # 줄 다시

**평가 도구.** 기록만 읽는 순수 함수다 — `eval/st/` 의 기록 전부를 읽어 경로마다 성립 · 지표 · 가드레일 지표 · 1차 결과 변수를 내고 두
경로를 함께 판정한다::

    python -m eval.st_trial tally

요청 본문은 운영 클라이언트 `nexus_client` 가 짓고 S 쪽은 전송 자리에서 `search_text` 키 하나만 더한다. 지표와 가드레일 지표는 앞 두 생성
실행(`eval/gen_trial.py` · `eval/gen_diag_trial.py`)의 것을 그대로 쓰고, 기록 쓰기(줄마다 · `complete`) · 줄 단위 다시 부르기 · 성립 검사 ·
제목 짝 · 기대 버전 필드는 이 파일에 둔다. 앞 실행들의 실행기와 `eval/recommend.py` · `eval/measure.py` 는 고치지 않는다.
"""

import collections
import copy
import datetime
import hashlib
import json
import os
import pathlib
import sys

from eval import ask_trial as at
from eval import fusion_trial as ft
from eval import gen_diag_trial as gdt
from eval import gen_trial as gt
from eval import query_trial as qt
from eval import recommend as rec
from eval import recommend_score as rs
from eval.run import ABORT_AFTER, fixture_history, load, load_truth, query_for
from eval.score import INCIDENT, QUERY, SEARCH, cites_doc
from explainer.client import ANSWER_TOP_K, INCIDENT_EXCLUDED, nexus_client
from explainer.transport import TRANSPORT_FAILED, http_transport
from receiver.pipeline import ask_and_record
from recorder.outcome import Outcome

SPEC = "docs/superpowers/specs/2026-10-06-검색-텍스트-칸.md"
#: 첫 실행 전에 커밋되어 있어야 하는 것(설계서 §4) — 설계서 · 이 실행기와 시험 · 가져다 쓰는 실행기와 채점 모듈.
COMMITTED = (SPEC, "eval/st_trial.py", "tests/test_eval_st_trial.py", "eval/gen_trial.py", "eval/gen_diag_trial.py",
             "eval/ask_trial.py", "eval/query_trial.py", "eval/fusion_trial.py", "eval/recommend.py",
             "eval/recommend_score.py", "eval/score.py", "eval/run.py", "explainer/client.py", "receiver/pipeline.py",
             "eval/st/.gitkeep")
ARMS_G = ("G0", "GS")
ARMS_D = ("D0", "DS")
PATHS = {"g": ARMS_G, "d": ARMS_D}
#: 채점 키의 제목 짝(설계서 머리 MUST 1) — (옛 제목, 새 제목). 골든셋 · 사례 파일이 옛 제목을 키로 쓰고, picasso 용어 반영(`c09921b`)
#: 뒤의 재적재는 새 제목을 싣는다. 원문 H1 의 백틱은 인용 제목 · 근거 문서 제목에서 벗겨져 오므로 백틱 없이 적는다. 채점에는 이 짝 하나만
#: 쓴다.
TITLE_PAIR = ("합성 기체(fixture)의 정지 코드 표면 — Synthetic Stop-Code Surface",
              "합성 기체(fixture)의 정지 코드 API 표면 — Synthetic Stop-Code Surface")
#: 같은 머지에서 H1 이 바뀐 아홉 문서의 옛 제목 → 새 제목(picasso `1483e9f` → `c09921b` 의 `docs/`). 앞 실행과의 견줌에만 쓴다 — 앞
#: 기록의 근거 문서 칸에 이 문서들이 자주 들어 있어 짝 하나만 옮기면 견줌의 차이가 대부분 제목 바뀜이 된다.
RENAMES = {
    "ADR 9 — 소비 표면이 없는 선언의 계약 유입 차단 원칙": "ADR 9 — 소비 API 표면이 없는 선언의 계약 유입 차단 원칙",
    "ADR 10 — 계약 투영 속성과 발신자 내부 설정의 분리 기준": "ADR 10 — 계약 프로젝션 속성과 발신자 내부 설정의 분리 기준",
    "ADR 40 — 사건 번들과 대안 탐색을 계약이 아닌 조회 결과로 두고, 탐색 깊이를 세 걸음으로 제한":
        "ADR 40 — 인시던트 번들과 조치 탐색을 계약이 아닌 조회 결과로 두고, 탐색 깊이를 세 단계로 제한",
    "ADR 45 — 자격 강등은 선언의 주인이 들고, 철회는 지우지 않고 표시한다":
        "ADR 45 — 권한 강등은 선언의 소유자가 들고, 철회는 지우지 않고 표시한다",
    "ADR 48 — 결과 통보에 바깥 형식을 두고, 승인 답과 실행 · 단위 · 인스턴스로 잇는다":
        "ADR 48 — 작업 응답에 바깥 형식을 두고, 승인 응답과 실행 · 단위 · 인스턴스로 잇는다",
    "시스템 한계 및 미결 과제 대장 (Known Limits & Technical Debt)":
        "시스템 한계 및 오픈 항목 과제 레지스터 (Known Limits & Technical Debt)",
    "오케스트레이션 — 세 층과 자원 소유": "오케스트레이션 — 세 계층과 자원 소유",
    "컴포넌트 교체 지점(Seams) 명세서 — 실물 전환 및 확장 가이드":
        "컴포넌트 접합부(Seams) 명세서 — 실제 하드웨어 전환 및 확장 가이드",
    TITLE_PAIR[0]: TITLE_PAIR[1],
}
#: 기대 버전 필드(설계서 §3) — 답한 모든 줄의 (모델, 프롬프트 버전, 코퍼스 버전, 검색 설정 지문)이 정규화 없이 이 값과 같아야 한다.
#: 코퍼스 버전은 재적재 뒤 근거만 받는 요청 하나의 응답에서 읽어 실행 전에 따로 커밋한다 — 비어 있으면 `run` 이 거부한다.
#: ⛔ **`8de8f67e2073` 을 읽었다 (2026-10-06 실측).** G9 의 GS 꼴(`evidence_only`)로 한 번 물었다 — 프롬프트 · 검색 설정이 위 값과 같고,
#: 정지 코드 문서의 `doc_title` 이 `TITLE_PAIR` 의 새 제목과 같고, 되울린 `search_text_len` 이 보낸 길이(334)와 같았다.
#: ⛔ **`a9dfe99ac26c` 로 바뀌었다 (2026-10-07 실측).** 설계서 §3 대로 khala #577 의 합성 SOP 안내 문서(`picasso:README.md`)를 실행 전에
#: 넣었다(사용자 결정, khala 가 손으로 적재). 바뀐 것은 그 문서 하나이고 SOP 여섯 편은 그대로다(khala 통지). 같은 꼴의 요청으로 다시 읽어
#: 같은 값을 봤고 프롬프트 · 검색 설정 · 제목 · `search_text_len` 은 앞과 같았다.
EXPECTED = {"model": "claude-sonnet-5", "prompt": "efe1e242c0e3", "corpus": "a9dfe99ac26c", "search": "b071397c854c"}
KST = datetime.timezone(datetime.timedelta(hours=9))
#: 경계 시각(설계서 §3) — 실행의 모든 줄이 이 시각들 뒤여야 한다. `search_text` 라이브(khala 기록 행 2655 부터) · 프롬프트 버전
#: `efe1e242c0e3`(앱 재시작, 행 2659 부터) · 머지된 picasso main `c09921b` 를 처음 읽은 재적재의 끝(khala 통지: 21:04:49~21:14:59 성공,
#: 문서 44건 중 14건 바뀜) · 합성 SOP 안내 문서 적재의 끝(khala 통지: 10-07 00:03:34 KST, 파일 7개 중 1개 바뀜).
BOUNDARIES = {
    "searchText": datetime.datetime(2026, 10, 6, 6, 42, 56, tzinfo=KST),
    "promptVersion": datetime.datetime(2026, 10, 6, 19, 54, 23, tzinfo=KST),
    "corpus": datetime.datetime(2026, 10, 6, 21, 14, 59, tzinfo=KST),
    "syntheticSop": datetime.datetime(2026, 10, 7, 0, 3, 34, tzinfo=KST),
}
#: `ask_and_record` 의 시도 한도 — `eval/measure.py` 와 같다. 실행 끝에 다시 부르는 실행은 줄마다 한 번이다.
LIMIT = gt.LIMIT
GOLDEN = gt.GOLDEN
TRUTH = gt.TRUTH
FIXTURES = "tests/fixtures/picasso"
TENANT = rec.TENANT
#: 곧바로 멈추는 상태와 사유 — 다시 해도 같다(설계서 §1 멈춤).
STOP = gt.STOP
ABORT_ON = rec.ABORT_ON
#: 실행 끝에 그 줄을 한 번 더 부를 생성 실패의 사유 — 다시 할 만한 것과 전송이 끊긴 것.
RERUN_REASONS = gt.RERUN_REASONS
FOLDER = ft.ROOT / "eval" / "st"
CANDIDATE = "운영 질의 변경을 사전 등록할 후보"
KEEP = "운영 질의 그대로"
NAMES = {"g": "설명 경로", "d": "진단 경로"}
sha = gt.sha


def body_sha(body):
    """보낸 본문의 sha256 — 직렬화를 박는다(키 차례 정렬, 한글 그대로, 빈칸 없는 구분자)."""
    text = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def plain(body):
    """`search_text` 를 뺀 본문 — 두 실험군에서 같아야 하는 것(설계서 §3 처치)."""
    return {key: value for key, value in body.items() if key != "search_text"}


# ── 계획 ──

def plan_g(golden=GOLDEN):
    """설명 경로 — 항목마다 두 실험군의 (질의, 답변 컨텍스트, 검색 텍스트)와 부르는 차례(설계서 §1).

    G0 는 측정기의 질의(`query_for`, Q0)에 답변 컨텍스트도 검색 텍스트도 없음, GS 는 같은 Q0 에 검색 텍스트 = 질문 제거의 Q3. 질의 줄은
    Q3 이 Q0 와 같은 글이라 GS 도 검색 텍스트를 안 보낸다(음성 대조). 홀수째 항목은 G0 먼저, 짝수째는 GS 먼저."""
    entries = load(golden)
    built = qt.queries(golden=pathlib.Path(golden))
    history = fixture_history()
    out = []
    for i, entry in enumerate(entries):
        q0 = query_for(entry, prior=history)
        three = at.texts(built[entry["id"]])
        if three["Q0"] != q0:
            raise ValueError(f"{entry['id']}: 물음 떼기의 Q0 가 측정기의 질의와 다르다")
        query_line = entry["kind"] == QUERY
        if not query_line and not three["Q3"].strip():
            raise ValueError(f"{entry['id']}: Q3 가 비었다 — 검색 텍스트로 보낼 글이 없다")
        out.append({"entry": entry, "order": ARMS_G if i % 2 == 0 else ARMS_G[::-1],
                    "exclude": tuple(INCIDENT_EXCLUDED) if entry["kind"] in (INCIDENT, SEARCH) else (),
                    "G0": {"query": q0, "context": None, "searchText": None},
                    "GS": {"query": q0, "context": None, "searchText": None if query_line else three["Q3"]}})
    return out


def plan_d(doc=None):
    """진단 경로 — 사례마다(반복 R02 뺌) 두 실험군의 (질의, 답변 컨텍스트, 검색 텍스트)와 부르는 차례(설계서 §1).

    D0 는 권고 측정기가 지을 글 그대로(Q0 · `render`), DS 는 같은 글에 검색 텍스트 = Q3. 홀수째 사례는 D0 먼저, 짝수째는 DS 먼저."""
    doc = doc or rs.load_cases()
    built = qt.queries(doc)
    out = []
    for i, prep in enumerate(p for p in rec.prepare(doc) if not p["case"]["repeatOf"]):
        cid = prep["case"]["id"]
        three = at.texts(built[cid])
        if three["Q0"] != prep["query"]:
            raise ValueError(f"{cid}: 물음 떼기의 Q0 가 진단의 질의와 다르다")
        if not three["Q3"].strip():
            raise ValueError(f"{cid}: Q3 가 비었다 — 검색 텍스트로 보낼 글이 없다")
        out.append({"prep": prep, "order": ARMS_D if i % 2 == 0 else ARMS_D[::-1], "exclude": tuple(rec.EXCLUDE),
                    "D0": {"query": prep["query"], "context": prep["context"], "searchText": None},
                    "DS": {"query": prep["query"], "context": prep["context"], "searchText": three["Q3"]}})
    return out


def targets(only, arms):
    """`--only` 의 항목 → (항목 → 다시 부를 실험군). `G4:GS` 는 그 줄만, `G4` 는 두 실험군 다."""
    out = {}
    for token in only:
        key, _, arm = token.partition(":")
        if arm and arm not in arms:
            raise SystemExit(f"모르는 실험군: {token}")
        out.setdefault(key, set()).update({arm} if arm else set(arms))
    return out


# ── 실행 ──

def with_search_text(transport, text):
    """전송 감싸기 — `text` 가 있을 때만 본문 사본에 `search_text` 키 하나를 더해 보낸다. 운영 클라이언트를 고치는 것이 아니라 그 본문에
    전송 자리에서 더한다(설계서 §1 요청 짓기)."""

    def send(method, url, headers, body):
        return transport(method, url, headers, dict(body, search_text=text) if text else dict(body))

    return send


def echo_of(body):
    """응답이 되울린 칸 — 받은 쪽에서 처치를 보는 재료. 앞 실행의 되울림에 검색 텍스트 길이 · 식별자 채널 요청 여부 · 점수 둘을 더한다.
    성공 봉투가 아니면 `None`."""
    out = gt.echo_of(body)
    if out is None:
        return None
    data = body["data"]
    out.update({key: data.get(key) for key in ("search_text_len", "identifier_channel_asked", "top_bm25", "top_distance",
                                               "weak_evidence", "evidence_only")})
    return out


def _capture(transport, sent, statuses, echoes, cuts):
    """보낸 본문 · 상태 · 되울림 · 연결 불가 여부를 시도마다 적는 전송. 연결 불가는 시도의 사유가 `unavailable` 인 것이다 — 이 계층의
    전송이 붙인 599 든, 브리지가 죽어 khala 가 200 에 실은 `llm_failure_reason` 이든(khala `llm/failure.py` 의 분류)."""

    def capture(method, url, headers, body):
        sent.append(body)
        try:
            answer = transport(method, url, headers, body)
        except ValueError as broken:  # JSON 아닌 응답(프록시 502 같은 것) — 전송 실패로 받는다
            answer = ("broken", {"detail": f"{type(broken).__name__}: {broken}"[:300]})
        statuses.append(answer[0])
        echoes.append(echo_of(answer[1]))
        cuts.append(_reason_of(answer) == "unavailable")
        return answer

    return capture


def _reason_of(answer):
    """한 시도의 실패 사유 — 전송이 끊긴 599 는 본문의 사유, 성공 봉투는 `data.llm_failure_reason`."""
    status, body = answer
    if not isinstance(body, dict):
        return None
    if status == TRANSPORT_FAILED:
        return body.get("llm_failure_reason")
    data = body.get("data") if body.get("success") else None
    return data.get("llm_failure_reason") if isinstance(data, dict) and data.get("llm_failed") else None


def _extend(row, intended, sent, statuses, cuts):
    """앞 실행의 줄에 이 실행의 칸을 더한다(설계서 §1 기록) — 시도마다 보낸 본문과 `search_text` 를 뺀 본문의 sha256, 보낸 검색 텍스트,
    마지막 시도가 보낸 빼는 종류 · 테넌트 · 식별자 채널, 상태와 연결 불가."""
    last = sent[-1] if sent else {}
    row.update(
        planSearchTextSha256=sha(intended["searchText"]),
        sentBodySha256=[body_sha(body) for body in sent],
        sentPlainSha256=[body_sha(plain(body)) for body in sent],
        sentSearchTextSha256=[sha(body.get("search_text")) for body in sent],
        sentSearchTextLen=len(last.get("search_text") or ""),
        sentKeysAll=[sorted(body) for body in sent],
        sentExclude=list(last.get("exclude_doc_types") or []), sentTenant=last.get("tenant"),
        sentIdentifierChannel=last.get("identifier_channel") is True,
        statuses=list(statuses), unreachable=bool(cuts) and all(cuts),
    )
    return row


def stop_of(statuses, reason, straight, cut, rerun):
    """멈출 까닭과 그것이 기반 장애인가 — `(까닭, 기반 장애인가)`, 없으면 `None`. 401 · 403 · 422 와 `quota` · `auth` 는 곧바로이고
    기반 장애다. 잇단 실패 둘은 다시 부르는 실행에서는 안 멈추고, 둘 다 연결 불가였을 때만 기반 장애다(설계서 머리 MUST 2)."""
    hit = [status for status in statuses if status in STOP]
    if hit:
        return f"상태 {hit[0]} — 곧바로 멈춘다", True
    if reason in ABORT_ON:
        return f"{reason} 는 다음 줄도 같다 — 곧바로 멈춘다", True
    if not rerun and straight >= ABORT_AFTER:
        return f"{ABORT_AFTER} 줄이 잇달아 실패했다(마지막 사유 {reason!r})", cut >= ABORT_AFTER
    return None


def _halt(out, env, rows, why, basis, clock):
    """멈춘다 — 까닭과 기반 장애 여부, 끝 시각과 khala 코드 식별 정보를 적고 그 줄까지의 기록을 남긴다."""
    env.update(stopped={"why": why, "basis": basis}, endedAt=clock(), khalaAfter=ft.khala_identity())
    rec.write(out, env, rows, complete=False)
    raise SystemExit(f"{why}. 기록은 complete=false 로 남았다")


def _warm(transport, base, token):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    try:
        status, response = transport("POST", base.rstrip("/") + "/search", headers, dict(ft.WARM))
    except ValueError:
        status, response = "broken", {}
    return ft.stop_reason("예열", status, response) or (None if status == 200 else f"멈춘다 — 예열이 {status}")


def _measurers(*paths):
    return {path: ft.git("rev-parse", f"HEAD:{path}") for path in paths}


def environment_g(name, base, clock):
    git = ft.git
    return {
        "at": clock(), "pass": name, "path": "g", "arms": list(ARMS_G), "limit": LIMIT,
        "narratorCommit": git("rev-parse", "HEAD"),
        "golden": git("rev-parse", f"HEAD:{GOLDEN}"), "fixtures": git("rev-parse", f"HEAD:{FIXTURES}"),
        "truth": git("rev-parse", f"HEAD:{TRUTH}"),
        "measurers": _measurers("eval/st_trial.py", "eval/gen_trial.py", "eval/ask_trial.py", "eval/query_trial.py",
                                "eval/score.py", "eval/run.py", "explainer/client.py", "composer/query.py",
                                "receiver/pipeline.py", "recorder/record.py"),
        "nexus": base, "token": "NEXUS_TOKEN", "tenant": TENANT, "topK": ANSWER_TOP_K, "identifierChannel": True,
        "exclude": {"incidentAndSearch": list(INCIDENT_EXCLUDED), "query": []},
        "expected": dict(EXPECTED), "boundaries": {k: v.isoformat() if v else None for k, v in BOUNDARIES.items()},
        "khalaBefore": ft.khala_identity(), "stopped": None,
    }


def environment_d(name, base, clock, doc):
    git = ft.git
    return {
        "at": clock(), "pass": name, "path": "d", "arms": list(ARMS_D), "maxAttempts": rec.MAX_ATTEMPTS,
        "narratorCommit": git("rev-parse", "HEAD"),
        "cases": {"blob": git("rev-parse", "HEAD:eval/goldenset-recommend.json"), "scoringHash": rs.scoring_hash(doc)},
        "requests": git("rev-parse", "HEAD:eval/recommend-requests"),
        "measurers": _measurers("eval/st_trial.py", "eval/gen_diag_trial.py", "eval/gen_trial.py", "eval/ask_trial.py",
                                "eval/query_trial.py", "eval/recommend.py", "eval/recommend_score.py", "diagnose/core.py",
                                "diagnose/context.py", "diagnose/judge.py", "explainer/client.py", "composer/query.py",
                                "receiver/pipeline.py"),
        "nexus": base, "token": "NEXUS_TOKEN", "tenant": TENANT, "topK": ANSWER_TOP_K, "identifierChannel": True,
        "excludeDocTypes": list(rec.EXCLUDE),
        "expected": dict(EXPECTED), "boundaries": {k: v.isoformat() if v else None for k, v in BOUNDARIES.items()},
        "khalaBefore": ft.khala_identity(), "stopped": None,
    }


def run_g(name, out, token, base, transport=http_transport, clock=ft._now, golden=GOLDEN, only=None):
    """설명 경로 한 회차 실행 — 웜업 한 번 뒤 항목마다 두 실험군을 `ask_and_record`(시도 한도 2)로 잇달아 부르고 줄마다 기록을 다시
    쓴다(`complete` 는 실행 끝에서만 참). 멈추면 `env.stopped` 를 적고 그 줄까지의 기록을 남긴다.

    `only` 는 실행 끝에 다시 부를 줄이다(`targets`, 차례 규칙은 그대로). 다시 부르는 실행은 줄마다 시도 하나이고 잇단 실패로는 안
    멈춘다."""
    rerun = only is not None
    wanted = targets(only, ARMS_G) if rerun else None
    work = [item for item in plan_g(golden) if wanted is None or item["entry"]["id"] in wanted]
    if rerun and {item["entry"]["id"] for item in work} != set(wanted):
        raise SystemExit(f"모르는 항목이 있다: {sorted(set(wanted) - {item['entry']['id'] for item in work})}")
    env = environment_g(name, base, clock)
    env["only"] = sorted(only) if rerun else None
    rows = []
    why = _warm(transport, base, token)
    if why:
        _halt(out, env, rows, why, True, clock)
    straight = cut = 0
    for item in work:
        entry = item["entry"]
        for arm in (a for a in item["order"] if wanted is None or a in wanted[entry["id"]]):
            intended = item[arm]
            sent, statuses, echoes, cuts = [], [], [], []
            capture = _capture(transport, sent, statuses, echoes, cuts)
            search = nexus_client(base, token, TENANT, with_search_text(capture, intended["searchText"]),
                                  exclude_doc_types=item["exclude"], identifier_channel=True,
                                  answer_context=intended["context"])
            at_ = clock()
            record = ask_and_record(("golden", entry["id"], arm), intended["query"], search, 1 if rerun else LIMIT)
            row = _extend(gt.row_of(entry, arm, intended, sent, record, at=at_, echo=echoes[-1] if echoes else None),
                          intended, sent, statuses, cuts)
            rows.append(row)
            rec.write(out, env, rows, complete=False)
            print(f"{name} {entry['id']} {arm} {record.outcome.value} {record.elapsed}s", flush=True)
            failed = record.outcome is Outcome.GENERATION_FAILED
            straight = straight + 1 if failed else 0
            cut = cut + 1 if failed and row["unreachable"] else 0
            halt = stop_of(statuses, record.reason if failed else None, straight, cut, rerun)
            if halt:
                _halt(out, env, rows, f"{entry['id']} {arm}: {halt[0]}", halt[1], clock)
    env.update(endedAt=clock(), khalaAfter=ft.khala_identity())
    rec.write(out, env, rows, complete=True)


def client_for(base, token, transport, received):
    """`run_diagnosis` 가 받는 `client(answer_context) -> search`. 함수가 지은 답변 컨텍스트와 질의를 [received] 에 적고 **그대로**
    보낸다 — 본문은 권고 측정기(`eval.recommend.client_for`)가 짓는다."""

    def client(context):
        seen = {"context": context, "query": None}
        received.append(seen)
        search = rec.client_for(base, token, transport=transport)(context)

        def send(query):
            seen["query"] = query
            return search(query)

        return send

    return client


def run_d(name, out, token, base, transport=http_transport, clock=ft._now, only=None, doc=None, commit=None):
    """진단 경로 한 회차 실행 — 앞 진단 경로 실행기와 같은 짜임이다(`run_diagnosis` 를 `run_case` 로). 함수가 지은 글을 그대로 보내고
    DS 는 전송 감싸기로 `search_text` 만 더한다. 멈춤 · `env.stopped` · 다시 부르기는 설명 경로 실행과 같다."""
    doc = doc or rs.load_cases()
    rerun = only is not None
    wanted = targets(only, ARMS_D) if rerun else None
    work = [item for item in plan_d(doc) if wanted is None or item["prep"]["case"]["id"] in wanted]
    if rerun and {item["prep"]["case"]["id"] for item in work} != set(wanted):
        raise SystemExit(f"모르는 사례가 있다: {sorted(set(wanted) - {item['prep']['case']['id'] for item in work})}")
    env = environment_d(name, base, clock, doc)
    env["only"] = sorted(only) if rerun else None
    commit = commit or ft.git("rev-parse", "--short", "HEAD")
    rows = []
    why = _warm(transport, base, token)
    if why:
        _halt(out, env, rows, why, True, clock)
    straight = cut = 0
    for item in work:
        prep = item["prep"]
        cid = prep["case"]["id"]
        for arm in (a for a in item["order"] if wanted is None or a in wanted[cid]):
            intended = item[arm]
            sent, statuses, echoes, cuts, received = [], [], [], [], []
            capture = _capture(transport, sent, statuses, echoes, cuts)
            at_ = clock()
            row = rec.run_case(prep, client_for(base, token, with_search_text(capture, intended["searchText"]), received),
                               commit, rerun=rerun, budget=1 if rerun else rec.MAX_ATTEMPTS)
            row = _extend(gdt.row_of(row, arm, intended, sent, received, at=at_, echo=echoes[-1] if echoes else None),
                          intended, sent, statuses, cuts)
            # 진단 경로의 연결 불가는 시도 기록의 사유로 본다 — 모든 시도가 `unavailable` 이면 연결 불가다
            row["unreachable"] = bool(row["attempts"]) and all(a.get("reason") == "unavailable" for a in row["attempts"])
            rows.append(row)
            rec.write(out, env, rows, complete=False)
            print(f'{name} {cid} {arm} {(row["response"] or {}).get("outcome") or "실패:" + str(row["failed"])} '
                  f'표지={row["rawPick"]!r} 시도={len(row["attempts"])}', flush=True)
            failed = row["response"] is None
            straight = straight + 1 if failed else 0
            cut = cut + 1 if failed and row["unreachable"] else 0
            halt = stop_of(statuses, row["failed"], straight, cut, rerun)
            if halt:
                _halt(out, env, rows, f"{cid} {arm}: {halt[0]}", halt[1], clock)
    env.update(endedAt=clock(), khalaAfter=ft.khala_identity())
    rec.write(out, env, rows, complete=True)


# ── 평가 도구 — 기록만 읽는다(설계서 §2 · §3) ──

def _title(title, pairs):
    for old, new in pairs:
        if rs.names_doc(title, new) and not rs.names_doc(title, old):
            return old
    return title


def canon(row, pairs=(TITLE_PAIR,)):
    """제목 짝으로 읽은 줄의 사본 — 셀 때만 쓰고 기록은 그대로다(설계서 머리 MUST 1). 답의 글에서 새 제목을 옛 제목으로 바꾸고, 인용 제목과
    근거 문서는 새 제목을 대는 것(같거나 앞부분, `names_doc`)이고 옛 제목을 안 대는 것이면 옛 제목으로 바꾼다. 설명 경로는 `answer` ·
    `citations` · `evidenceDocs`, 진단 경로는 `answer` · `response.citations` · `evidenceDocs` 다."""
    row = copy.deepcopy(row)
    for old, new in pairs:
        if row.get("answer"):
            row["answer"] = row["answer"].replace(new, old)
    diagnostics = row.get("diagnostics")
    if diagnostics and diagnostics.get("evidenceDocs") is not None:
        diagnostics["evidenceDocs"] = sorted({_title(title, pairs) for title in diagnostics["evidenceDocs"]})
    citations = (row["response"] or {}).get("citations") if "response" in row else row.get("citations")
    for citation in citations or []:
        if isinstance(citation, dict) and citation.get("title"):
            citation["title"] = _title(citation["title"], pairs)
    return row


def _answered(row):
    """답한 줄 — 설명 경로는 생성 실패가 아닌 줄, 진단 경로는 응답이 있는 줄."""
    if "response" in row:
        return row["response"] is not None
    return row["outcome"] != Outcome.GENERATION_FAILED.value


def _pending(row):
    """실행 끝에 한 번 다시 부를 줄인가 — 검색 부분 실패이거나 다시 할 만한 생성 실패."""
    reason = row["failed"] if "response" in row else row["reason"]
    return rs.search_broken(row) or (not _answered(row) and reason in RERUN_REASONS)


def _basis_only(record):
    """집계에서 빼는 기록인가 — 답한 줄 0 인 채 기반 장애로 멈춘 전체 실행 기록뿐이다(설계서 머리 MUST 2). 다시 부른 기록은 빼지
    않는다 — 빼면 그 줄의 다음 다시 부르기가 「한 번만」을 넘어 받아들여진다."""
    return (record["env"].get("only") is None and (record["env"].get("stopped") or {}).get("basis") is True
            and not any(_answered(row) for row in record["rows"]))


def _name_problems(path, full, excluded):
    """전체 실행 기록의 이름(설계서 머리 MUST 2) — `<경로>-1` 이고, `<경로>-2` 는 같은 경로의 `-1` 이 답한 줄 0 인 기반 장애 기록으로
    빠졌을 때만 받는다. 결과를 보고 실행을 고를 여지를 막는다."""
    first, second = f"{path}-1", f"{path}-2"
    return sorted(name for name in full if not (name == first or (name == second and first in excluded)))


def _after(moment):
    """줄의 시각이 모든 경계 시각 뒤인가 — 시간대를 가진 시각으로 바꿔 견준다. 못 읽거나 시간대가 없거나 경계가 비었으면 아니다."""
    try:
        when = datetime.datetime.fromisoformat(moment)
    except (TypeError, ValueError):
        return False
    if when.tzinfo is None:
        return False
    return all(bound is not None and when > bound for bound in BOUNDARIES.values())


def _expected():
    return (EXPECTED["model"], EXPECTED["prompt"], EXPECTED["corpus"], EXPECTED["search"])


def _merge(records):
    """기록 여럿(시각 차례) → 줄마다 마지막 것. 다시 부른 기록(`env.only`)의 줄은 앞에서 다시 부를 줄이던 것만, 한 번만 덮는다."""
    latest, reruns, bad = {}, collections.Counter(), []
    for record in records:
        is_rerun = record["env"].get("only") is not None
        for row in record["rows"]:
            key = (row["id"], row["arm"])
            if is_rerun:
                reruns[key] += 1
                if key not in latest or not _pending(latest[key]) or reruns[key] > 1:
                    bad.append(f"{row['id']} {row['arm']}")
            latest[key] = row
    return latest, reruns, bad


def _client_sha(path, intended, exclude):
    """운영 클라이언트가 계획한 (질의, 답변 컨텍스트)로 지을 본문의 sha256 — 가짜 전송을 달아 다시 짓는다."""
    seen = []

    def transport(method, url, headers, body):
        seen.append(body)
        return 200, {}

    if path == "g":
        nexus_client("http://x", "t", TENANT, transport, exclude_doc_types=exclude, identifier_channel=True,
                     answer_context=intended["context"])(intended["query"])
    else:
        rec.client_for("http://x", "t", transport=transport)(intended["context"])(intended["query"])
    return body_sha(seen[0])


def _row_problems(path, label, row, intended, exclude, built):
    """줄 하나의 처치(설계서 §3) — 보낸 것이 계획과 운영 본문인가, 받은 쪽 되울림이 보낸 것과 같은가."""
    problems = []
    if not row["sentPlainSha256"]:
        problems.append(f"{label}: 보낸 본문이 없다")
    elif any(h != built for h in row["sentPlainSha256"]):
        problems.append(f"{label}: search_text 를 뺀 본문이 운영 클라이언트의 본문과 다르다")
    if row["sentQuerySha256"] != sha(intended["query"]) or row["planQuerySha256"] != sha(intended["query"]):
        problems.append(f"{label}: 보낸 질의가 계획과 다르다")
    if row["sentContextSha256"] != sha(intended["context"]) or row["planContextSha256"] != sha(intended["context"]):
        problems.append(f"{label}: 보낸 답변 컨텍스트가 계획과 다르다")
    want = sha(intended["searchText"])
    if any(h != want for h in row["sentSearchTextSha256"]) or row["planSearchTextSha256"] != want:
        problems.append(f"{label}: 보낸 search_text 가 계획과 다르다")
    if any(("search_text" in keys) is not bool(intended["searchText"]) for keys in row.get("sentKeysAll") or [[]]):
        problems.append(f"{label}: search_text 키를 보냈는지가 계획과 다르다")
    if row["sentSearchTextLen"] != len(intended["searchText"] or ""):
        problems.append(f"{label}: 적은 search_text 길이가 계획과 다르다")
    if (sorted(row["sentExclude"]) != sorted(exclude) or row["sentTenant"] != TENANT
            or row["sentIdentifierChannel"] is not True):
        problems.append(f"{label}: 보낸 빼는 종류 · 테넌트 · 식별자 채널이 계획과 다르다")
    if path == "d":
        if sha(row["sentQuery"]) != row["sentQuerySha256"] or sha(row["sentContext"]) != row["sentContextSha256"]:
            problems.append(f"{label}: 적은 글이 보낸 글의 해시와 다르다")
        if (row["querySha256"] != sha(intended["query"]) or row["contextSha256"] != sha(intended["context"])
                or row["receivedQuerySha256"] != [row["querySha256"]]
                or row["receivedContextSha256"] != [row["contextSha256"]]):
            problems.append(f"{label}: 진단 함수가 지은 글이 운영 글이 아니다")
    echo = row.get("echo")
    if echo is None:
        if _answered(row):
            problems.append(f"{label}: 되울림이 없다")
        return problems
    if echo.get("search_text_len") != row["sentSearchTextLen"]:
        problems.append(f"{label}: search_text 길이 되울림 {echo.get('search_text_len')} ≠ 보낸 {row['sentSearchTextLen']}")
    if echo.get("answer_context_len") != row["sentContextLen"]:
        problems.append(f"{label}: 답변 컨텍스트 길이 되울림 {echo.get('answer_context_len')} ≠ 보낸 {row['sentContextLen']}")
    if sorted(echo.get("excluded_doc_types") or []) != sorted(row["sentExclude"]):
        problems.append(f"{label}: 빼는 종류 되울림 {echo.get('excluded_doc_types')}")
    if echo.get("searched_tenants") != [row["sentTenant"]]:
        problems.append(f"{label}: 테넌트 되울림 {echo.get('searched_tenants')}")
    if echo.get("identifier_channel_asked") is not row["sentIdentifierChannel"]:
        problems.append(f"{label}: 식별자 채널 요청 되울림 {echo.get('identifier_channel_asked')}")
    return problems


def _treatment(path, key, item, rows):
    """한 항목 · 사례의 두 실험군 — 줄마다의 처치와, `search_text` 를 뺀 본문 · 질의(진단 경로는 답변 컨텍스트도)가 두 실험군에서 같은가."""
    arms = PATHS[path]
    problems = []
    for arm in arms:
        problems += _row_problems(path, f"{key} {arm}", rows[arm], item[arm], item["exclude"],
                                  _client_sha(path, item[arm], item["exclude"]))
    if len({h for arm in arms for h in rows[arm]["sentPlainSha256"]}) > 1:
        problems.append(f"{key}: 두 실험군의 search_text 를 뺀 본문이 다르다")
    base, treat = (rows[arm] for arm in arms)
    if base["sentQuerySha256"] != treat["sentQuerySha256"]:
        problems.append(f"{key}: 두 실험군의 질의가 다르다")
    if path == "d" and base["sentContextSha256"] != treat["sentContextSha256"]:
        problems.append(f"{key}: 두 실험군의 답변 컨텍스트가 다르다")
    return problems


def primary(path, base, treat):
    """1차 결과 변수의 여유(설계서 §2) — 설명 경로 GS ≥ G0(여유 0), 진단 경로 DS ≥ D0 − 1(여유 한 칸)."""
    if path == "g":
        return treat["procedureDoc"][0] >= base["procedureDoc"][0]
    return treat["procedureCited"][0] >= base["procedureCited"][0] - 1


def verdict(g, d):
    """두 경로가 다 승격되어야 운영 질의 변경을 사전 등록할 후보다. 운영을 바꾸는 것이 아니다."""
    return CANDIDATE if g.get("advance") is True and d.get("advance") is True else KEEP


def _item(row, retrieved, cited):
    d = row.get("diagnostics") or {}
    echo = row.get("echo") or {}
    no_evidence = (row.get("recordOutcome") if "response" in row else row["outcome"]) == Outcome.NO_EVIDENCE.value
    return {"outcome": ((row["response"] or {}).get("outcome") or f"실패:{row['failed']}") if "response" in row
            else row["outcome"],
            "procedureCited": cited, "procedureRetrieved": retrieved,
            "weak": d.get("weak_evidence"), "bm25": d.get("top_bm25"), "distance": d.get("top_distance"),
            "route": echo.get("route_used"), "noEvidence": no_evidence,
            "answerLen": len(row.get("answer") or ""), "sends": row.get("sends")}


def _path_tally(path, records, golden, truth_path, doc, head, reference, excluded=()):
    """경로 하나 — 성립 검사(전역 검사는 `tally` 가 더한다)와 지표 · 가드레일 지표 · 1차 결과 변수 · 서술."""
    arms = PATHS[path]
    latest, reruns, bad = _merge(records)
    if path == "g":
        work = plan_g(golden)
        keys = {item["entry"]["id"]: item for item in work}
    else:
        work = plan_d(doc)
        keys = {item["prep"]["case"]["id"]: item for item in work}
    out = {"records": [str(r["env"].get("pass")) for r in records], "rows": sum(len(r["rows"]) for r in records),
           "badReruns": bad}
    out["fullPasses"] = [str(r["env"].get("pass")) for r in records if r["env"].get("only") is None]
    out["badNames"] = _name_problems(path, out["fullPasses"], excluded)
    # 기록을 지은 평가 도구 코드가 집계 때의 HEAD 와 같은가 — 집계는 지금 코드로 계획을 다시 짓는다
    out["measurerDrift"] = sorted({f"{r['env'].get('pass')} {k}" for r in records
                                   for k, v in (r["env"].get("measurers") or {}).items() if v != head(k)}
                                  | {str(r["env"].get("pass")) for r in records if not r["env"].get("measurers")})
    out["stopped"] = [str(r["env"].get("pass")) for r in records if r["env"].get("stopped")]
    out["incomplete"] = [str(r["env"].get("pass")) for r in records if r.get("complete") is not True]
    if path == "g":
        heads = {"golden": head(GOLDEN), "fixtures": head(FIXTURES), "truth": head(TRUTH)}
        out["frozen"] = sorted({f"{r['env'].get('pass')} {k}" for r in records for k, v in heads.items()
                                if r["env"].get(k) != v})
    else:
        out["frozen"] = sorted({str(r["env"].get("pass")) for r in records
                                if (r["env"].get("cases") or {}).get("scoringHash") != rs.scoring_hash(doc)})
    out["missing"] = [f"{key} {arm}" for key in keys for arm in arms if (key, arm) not in latest]
    out["early"] = sorted(f"{row['id']} {row['arm']}" for r in records for row in r["rows"] if not _after(row.get("at")))
    out["broken"] = sorted(f"{row['id']} {row['arm']}" for row in latest.values() if rs.search_broken(row))
    out["pending"] = sorted(f"{key[0]} {key[1]}" for key, row in latest.items()
                            if _pending(row) and not rs.search_broken(row) and not reruns[key])
    out["failedAfterRerun"] = sorted(f"{key[0]} {key[1]}" for key, row in latest.items()
                                     if not _answered(row) and reruns[key])
    treatment = []
    for key, item in keys.items():
        rows = {arm: latest.get((key, arm)) for arm in arms}
        if all(rows.values()):
            treatment += _treatment(path, key, item, rows)
    out["treatment"] = treatment
    out["latest"] = latest
    if out["missing"]:
        return out
    view = {k: canon(row) for k, row in latest.items()}

    def row(key, arm):
        return view[(key, arm)]

    if path == "g":
        entries = [item["entry"] for item in work]
        truth = load_truth(truth_path)
        out["arms"] = {arm: gt.metrics(entries, [gt.to_record(row(e["id"], arm)) for e in entries], truth=truth)
                       for arm in arms}

        def retrieved(e, arm):
            return e["procedure"]["doc"] in ((row(e["id"], arm)["diagnostics"] or {}).get("evidenceDocs") or [])

        procedural = [e for e in entries if e["kind"] == INCIDENT and e.get("procedure")]
        # 둘 다 받은 사건은 두 실험군이 다 답한 사건으로만 센다 — 실패한 줄도 근거 묶음을 가지므로(설계서 §2)
        both = [e for e in procedural if all(_answered(row(e["id"], arm)) and retrieved(e, arm) for arm in arms)]
        out["bothRetrieved"] = [e["id"] for e in both]
        for arm in arms:
            out["arms"][arm]["citedWhenBoth"] = (sum(cites_doc(row(e["id"], arm)["answer"] or "", e["procedure"]["doc"])
                                                     for e in both), len(both))
            out["arms"][arm]["weakEvidence"] = sum(bool((row(e["id"], arm)["diagnostics"] or {}).get("weak_evidence"))
                                                   for e in entries if e["kind"] != QUERY)
        out["items"] = [{"id": e["id"], **{arm: _item(
            row(e["id"], arm), retrieved(e, arm) if e.get("procedure") else None,
            cites_doc(row(e["id"], arm)["answer"] or "", e["procedure"]["doc"]) if e.get("procedure") else None)
            for arm in arms}} for e in entries]
        out["guards"] = gt.guards(out["arms"]["G0"], out["arms"]["GS"])
    else:
        cases = {item["prep"]["case"]["id"]: item["prep"]["case"] for item in work}
        paired = {cid for cid in cases if all(_answered(row(cid, arm)) for arm in arms)}
        out["unpaired"] = sorted(set(cases) - paired)
        out["arms"] = {arm: gdt.metrics(doc, [row(cid, arm) for cid in cases], paired) for arm in arms}
        both = [cid for cid, case in cases.items() if case["procedureDocs"]
                and all(_answered(row(cid, arm)) and gdt._retrieved(row(cid, arm), case) for arm in arms)]
        out["bothRetrieved"] = both
        for arm in arms:
            out["arms"][arm]["citedWhenBoth"] = (sum(rs._grounded(row(cid, arm), cases[cid]) for cid in both), len(both))
        out["items"] = [{"id": cid, **{arm: _item(
            row(cid, arm), gdt._retrieved(row(cid, arm), case) if case["procedureDocs"] else None,
            rs._grounded(row(cid, arm), case) if case["procedureDocs"] and _answered(row(cid, arm)) else None)
            for arm in arms}} for cid, case in cases.items()]
        out["guards"] = gdt.guards(out["arms"]["D0"], out["arms"]["DS"])
    out["weakSplit"] = [item["id"] for item in out["items"]
                        if len({bool(item[arm]["weak"]) for arm in arms}) > 1]
    if reference is not None:
        prior = reference.get(path) or {}
        renamed = (TITLE_PAIR,) + tuple(RENAMES.items())
        out["reference"] = sorted(
            f"{key} {arm}" for key in keys for arm in arms if (arm, key) in prior
            and (latest[(key, arm)].get("diagnostics") or {}).get("evidenceDocs") is not None
            and set(canon(latest[(key, arm)], renamed)["diagnostics"]["evidenceDocs"]) != prior[(arm, key)])
    else:
        out["reference"] = None
    out["primary"] = primary(path, out["arms"][arms[0]], out["arms"][arms[1]])
    return out


def tally(records, golden=GOLDEN, truth_path=TRUTH, doc=None, head=None, reference=None):
    """기록 여럿 → 경로마다 설계서 §2 · §3 의 수와 두 경로의 판정. 시각 차례로 합치고 `env.path` 로 경로를 가른다. 답한 줄 0 인 채 기반
    장애로 멈춘 기록만 집계에서 빼고(`excluded`), 버전 필드 · khala 코드 식별 정보 · narrator 커밋은 두 경로를 합쳐 본다.

    `head(path)` 는 집계 때의 `HEAD` 의 객체 해시다(시험이 바꿔 끼운다). `reference` — 앞 실행의 경로 → (실험군, 항목) → 근거 문서 집합
    (적기만 한다)."""
    head = head or (lambda path: ft.git("rev-parse", f"HEAD:{path}"))
    doc = doc or rs.load_cases()
    records = sorted(records, key=lambda r: r["env"].get("at") or "")
    for record in records:
        if record["env"].get("path") not in PATHS:
            raise ValueError(f"경로를 모르는 기록: {record['env'].get('pass')} {record['env'].get('path')!r}")
    excluded = [r for r in records if _basis_only(r)]
    counted = [r for r in records if not _basis_only(r)]
    out = {"excluded": [str(r["env"].get("pass")) for r in excluded]}
    for path in PATHS:
        out[path] = _path_tally(path, [r for r in counted if r["env"]["path"] == path], golden, truth_path, doc, head,
                                reference, [str(r["env"].get("pass")) for r in excluded if r["env"]["path"] == path])
        out[path].pop("latest")
    # 버전 필드는 답한 모든 줄로 본다 — 다시 부른 줄에 덮인 줄도(설계서 §3 「답한 모든 줄」)
    answered = [row for r in counted for row in r["rows"] if _answered(row)]
    out["versions"] = sorted({json.dumps(gt._versions(row)) for row in answered})
    out["unknownVersions"] = sorted({f"{row['id']} {row['arm']}" for row in answered
                                     if any(v is None or v == "" for v in gt._versions(row))})
    out["expected"] = json.dumps(_expected())
    # 멈춘 기록은 제 경로를 이미 성립 안 함으로 만든다 — 다른 경로의 성립까지 깨지 않게 코드 식별 정보 검사에서는 뺀다
    finished = [r for r in counted if not r["env"].get("stopped")]
    out["khalaChanged"] = len({json.dumps(r["env"].get(side), sort_keys=True)
                               for r in finished for side in ("khalaBefore", "khalaAfter")}) > 1
    out["narratorChanged"] = len({r["env"].get("narratorCommit") for r in finished}) > 1
    # 모르는 칸(`None` · 빈 글자)을 먼저 적는다 — 그 줄 하나로도 버전 필드가 두 벌이 되므로 더 좁은 까닭을 앞에 둔다
    version_problem = ("모르는 버전 필드가 있다" if out["unknownVersions"]
                       else "버전 필드가 한 벌이 아니다" if len(out["versions"]) > 1
                       else "버전 필드가 기대 값과 다르다" if out["versions"] != [out["expected"]] else None)
    for path in PATHS:
        p = out[path]
        p["comparable"] = ("멈춘 기록이 있다" if p["stopped"]
                           else "전체 실행 기록이 하나가 아니다" if len(p["fullPasses"]) != 1
                           else "전체 실행 기록의 이름이 규칙과 다르다" if p["badNames"]
                           else "끝나지 않은 기록이 있다" if p["incomplete"]
                           else ("골든셋 · fixtures · 정답 데이터가 HEAD 와 다르다" if path == "g"
                                 else "사례 파일의 채점 칸이 다르다") if p["frozen"]
                           else "평가 도구 코드가 집계 때의 HEAD 와 다르다" if p["measurerDrift"]
                           else "빠진 줄이 있다" if p["missing"]
                           else version_problem if version_problem
                           else "경계 시각 앞의 줄이 있다" if p["early"]
                           else "검색 부분 실패가 남았다" if p["broken"]
                           else "다시 부를 실패가 남았다" if p["pending"]
                           else "다시 부른 줄이 검색 부분 실패 · 다시 부를 실패가 아니었거나 두 번이다" if p["badReruns"]
                           else "처치가 계획과 다르다" if p["treatment"]
                           else "khala 코드 식별 정보가 기록마다 다르다" if out["khalaChanged"]
                           else "narrator 커밋이 기록마다 다르다" if out["narratorChanged"] else None)
        if "arms" in p:
            p["advance"] = p["comparable"] is None and all(p["guards"].values()) and p["primary"]
    out["verdict"] = verdict(out["g"], out["d"])
    return out


def _reference(root=ft.ROOT):
    """앞 실행(생성 실행 두 경로의 첫 실행)의 근거 묶음 문서 집합 — G0 ↔ G0, GS ↔ G3, D0 ↔ D0, DS ↔ D3. 기록이 없으면 `None`."""
    out = {}
    for path, name, arms in (("g", "g-1.json", {"G0": "G0", "G3": "GS"}), ("d", "d-1.json", {"D0": "D0", "D3": "DS"})):
        file = root / "eval" / "gen" / name
        if not file.exists():
            return None
        out[path] = {}
        for row in json.loads(file.read_text(encoding="utf-8"))["rows"]:
            docs = (row.get("diagnostics") or {}).get("evidenceDocs")
            if row["arm"] in arms and docs is not None:
                out[path][(arms[row["arm"]], row["id"])] = set(docs)
    return out


def report_lines(out):
    lines = [f"버전 필드 {out['versions']} · 기대 {out['expected']} · 모르는 칸 {out['unknownVersions']} · "
             f"집계에서 뺀 기록 {out['excluded']} · khala 코드 식별 정보 {'기록마다 다름' if out['khalaChanged'] else '한 벌'}"]
    for path, arms in PATHS.items():
        p = out[path]
        lines.append(f"[{NAMES[path]}] 기록 {p['records']} · 줄 {p['rows']} · 검색 부분 실패 {p['broken']} · "
                     f"처치 {p['treatment'] or '계획대로'}")
        if "arms" not in p:
            lines += [f"⚠ 비교 안 함 — {p['comparable']}", "승격 — 판정 안 함"]
            continue
        key = "procedureDoc" if path == "g" else "procedureCited"
        base, treat = (p["arms"][arm][key] for arm in arms)
        lines.append(("성립" if p["comparable"] is None else f"⚠ 성립 안 함({p['comparable']})")
                     + f" — 1차 결과 변수 절차 문서 인용 {arms[0]} {base[0]}/{base[1]} · {arms[1]} {treat[0]}/{treat[1]}")
        for arm in arms:
            lines.append(f"{arm} " + json.dumps(p["arms"][arm], ensure_ascii=False))
        lines.append("가드레일 지표 " + json.dumps(p["guards"], ensure_ascii=False))
        lines.append(f"둘 다 받은 것 {p['bothRetrieved']} · 약함 판정이 갈린 쌍 {p['weakSplit']} · "
                     f"앞 실행과 근거 문서 집합이 다른 줄 {p['reference']}")
        for item in p["items"]:
            lines.append(f"  {item['id']:4} " + " · ".join(
                f"{arm} {item[arm]['outcome']} 절차 {item[arm]['procedureCited']}/{item[arm]['procedureRetrieved']} "
                f"약함 {item[arm]['weak']} bm25 {item[arm]['bm25']} 거리 {item[arm]['distance']} 경로 {item[arm]['route']}"
                for arm in arms))
        lines.append("승격 — " + ((arms[1] if p["advance"] else "없음") if p["comparable"] is None else "판정 안 함"))
    lines.append("판정 — " + out["verdict"])
    return lines


def refusals(now):
    """실행 전 거부(설계서 §3 · §4) — 기대 버전 필드 · 경계 시각이 비었거나 지금이 경계 시각 앞이면."""
    if any(value is None for value in EXPECTED.values()):
        return "기대 버전 필드가 비었다(코퍼스 버전) — 근거만 받는 요청으로 읽어 상수에 넣고 커밋한 뒤 돈다"
    if any(bound is None for bound in BOUNDARIES.values()):
        return "경계 시각이 비었다 — 재적재 시각을 받아 커밋한 뒤 돈다"
    if not all(now > bound for bound in BOUNDARIES.values()):
        return f"지금이 경계 시각 앞이다({now.isoformat()})"
    return None


def main(argv=None, now=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["run"] and len(args) >= 2 and "--out" in args[:-1] and "--path" in args[:-1]:
        name = args[1]
        path = args[args.index("--path") + 1]
        if path not in PATHS:
            raise SystemExit(f"--path 는 g 또는 d 다: {path!r}")
        out = pathlib.Path(args[args.index("--out") + 1])
        only = set(args[args.index("--only") + 1].split(",")) if "--only" in args[:-1] else None
        why = refusals(now or datetime.datetime.now(datetime.timezone.utc))
        if why:
            raise SystemExit(why)
        token = os.environ.get("NEXUS_TOKEN")
        if not token:
            raise SystemExit("Nexus 토큰이 없다. NEXUS_TOKEN 으로 준다")
        root = os.environ.get("KHALA_ROOT")
        if not root or ft.git("rev-parse", "HEAD", cwd=root) is None:
            raise SystemExit("KHALA_ROOT 가 khala 저장소를 가리켜야 한다(설계서 §3 코드 식별 정보)")
        problems = rec.frozen_problems() + [f"{p}: 커밋되지 않았다" for p in COMMITTED
                                            if ft.git("rev-parse", f"HEAD:{p}") is None]
        if problems:
            raise SystemExit("고친 트리에서는 돌지 않는다 — 커밋하고 돈다\n" + "\n".join(problems))
        if not out.parent.is_dir():
            raise SystemExit(f"기록을 둘 폴더가 없다: {out.parent}")
        if out.exists():
            raise SystemExit(f"기록이 이미 있다: {out}")
        base = os.environ.get("NEXUS_URL", "http://localhost:8000")
        (run_g if path == "g" else run_d)(name, out, token, base, only=only)
        return 0
    if args == ["tally"]:
        records = [json.loads(file.read_text(encoding="utf-8")) for file in sorted(FOLDER.glob("*.json"))]
        for line in report_lines(tally(records, reference=_reference())):
            print(line)
        return 0
    raise SystemExit(__doc__)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
