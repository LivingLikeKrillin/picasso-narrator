"""실물 스택에 골든셋 한 바퀴를 돌리고 표를 찍는다.

    python eval/measure.py          # 저장소 뿌리에서

**이것이 `RESULTS.md` 의 모든 수치를 낸 자리다.** 한동안 세션 임시 폴더에 있었고
(없어지는 자리였다) 여기로 옮겼다 — **재는 절차가 산출물과 같이 있어야** 다음 사람이
같은 것을 잰다.

`eval/run.py` 의 `collect` 와 다른 점은 **표시와 진단**뿐이다. 묻는 길은 같다
(`receiver.pipeline.ask_and_record`) — 평가가 실제로 도는 길과 달라지면 **재는 것이
도는 것과 달라진다**(2026-09-19, 그 결함을 한 번 겪었다).

**필요한 것**: `nexus-app` 이 8000 에 떠 있고 호스트에 `claude_llm_bridge` 가 8900 에
있어야 한다. 없으면 전부 `unavailable` 로 찍힌다. 한 바퀴에 20~40분 걸린다.

**`USED` 는 거친 셈법이다.** 번들에만 있는 표지어가 답에 나타나는지만 본다 — 답이 그
칸을 읽고 다른 말로 옮기면 안 잡히고, 번들을 질의에 통째로 싣기 때문에 **복창해도
잡힌다.** 수만으로 「쓰였다」를 주장하지 않는다(`RESULTS.md`).
"""


import os, sys, json, io, time
sys.path.insert(0, '.')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
from eval.run import (ABORT_AFTER, fixture_history, load, load_truth, query_for,
                      run_env, straight_failures)
from eval.score import INCIDENT, QUERY, SEARCH, score
from receiver.pipeline import ask_and_record
from explainer.client import nexus_client, ANSWER_TOP_K, INCIDENT_EXCLUDED
from explainer.transport import http_transport
from recorder.card import parse_card
from recorder.outcome import Outcome

USED = {
    "G1": ["hum-02", "E0", "InspectAsset"],
    "G2": ["hum-04", "X_FIXTURE_GRIPPER_SLIP", "RACK-204.S03", "E2"],
    "G3": ["hum-05", "navigate_to", "PUMP-ROOM-1"],
    "G4": ["hum-06", "X_FIXTURE_E9001", "RACK-204.S05"],
    "G5": ["hum-03", "OUT-07", "HU-1042", "FLEET"],
    "G6": ["hum-07", "RACK-204.S06", "E2"],
    "G7": ["hum-08", "RACK-204.S07", "X_FIXTURE_E4412"],
    "G8": ["hum-09", "RACK-204.S08", "X_FIXTURE_E2075"],
    "G9": ["hum-10", "RACK-204.S09", "X_FIXTURE_E6130"],
}

entries = load('eval/goldenset.json')
truth = load_truth('tests/fixtures/picasso/ground-truth.jsonl')
# **실험군.** khala 사전 등록(`PROCEDURE_RETRIEVAL_PREREGISTRATION.md`)의 T0 과 T2 다.
# **기본이 T2 다 (2026-09-20 채택).** 주 변수가 6/8 에서 7/8 로 올랐고 내려간 사건이 없었다.
# 대조군을 다시 보려면 `python eval/measure.py T0` 으로 부른다.
#
# ⚠ **이것은 이 층의 채택이지 khala 의 기본값이 아니다.** 저쪽 회귀 판(라벨 80 질의)은 전부
# 식별자형 토큰이 없는 질의라 그 판이 기본값 판단에 아무 말도 안 한다 — `RESULTS.md` 의
# 「부 변수 1(회귀)」 절에 적었다. 깃발이라 이 층이 켜도 다른 소비자에게 안 닿는다.
#
# ⛔ **한 번에 하나만 움직인다.** T2 는 식별자 채널 하나만 켜고 나머지는 T0 과 같다.
ARM = (sys.argv[1] if len(sys.argv) > 1 else 'T2').upper()

#: 코퍼스 적재 시각. **저쪽 신고값이고 관측이 아니다** — khala 가 고칠 때 알려 주기로 한
#: 값을 여기 옮겨 적는다. 안 고치고 판을 돌리면 기록이 조용히 낡으므로, 코퍼스가 바뀌었다는
#: 말을 받으면 **이 줄부터 고친다.**
# ⛔ 신고값이다 — 응답에 안 온다. 재적재 때마다 khala 가 준 경계로 손으로 올린다. 2026-09-23 에 한 판이
# 옛 값(04:39:29Z)으로 찍혀 기록의 env 를 손으로 정정했다 — 이 줄을 안 올리면 기록이 거짓말을 한다.
# 경계 이력: 04:39:29Z(재적재) → 18:46:01Z(용어집 §7 · 설계 명세 숨김, 조각 -147) → 19:32:48Z(ADR 셋 BOM 고침, 조각 18)
# → 19:38:55Z(용어집 §7 의 unresolved·resolution 구분, 조각 3).
CORPUS_VERSION = '2026-09-22T19:38:55Z'

#: 생성이 어느 인증 경로로 돌았나. **저쪽 신고값이다.** khala 가 #535 로 nexus/.env 의
#: API 키를 빼면서 구독 로그인으로 바뀌었다(2026-09-22). 그전 판들은 전부 키로 돌았다.
#: 모델도 프롬프트도 작업 디렉터리도 같고 **인증과 과금 경로만 다르다.**
#:
#: ⛔ **이 축을 가로질러 비교하지 않는다.** 이 축이 답의 질을 미는지는 아무도 모르고,
#: 모른다는 것이 비교해도 된다는 뜻이 아니다.
AUTH = 'subscription'
# ⛔ 코드에 글자로 박혀 있던 개발 토큰이 잴 뿐인 층에 필요 없는 권한이 딸린 신원이었다 (khala 실측 2026-09-23).
# 값은 환경에서만 온다. 새 신원(narrator-events, 읽기 전용)이 살면 그 값으로 바꾼다.
TOKEN = os.environ.get('NEXUS_TOKEN')
if not TOKEN:
    raise SystemExit('Nexus 토큰이 없다. NEXUS_TOKEN 으로 준다. 값은 저장소에 두지 않는다 (.secrets/nexus-tokens.env)')
assert ARM in ('T0', 'T2'), f'실험군은 T0 이나 T2 다. 받은 것: {ARM}'
IDENTIFIERS = ARM == 'T2'

# **묻는 방식이 갈래마다 다르다.** 사건 질의는 설계 문서를 빼고 묻고(`INCIDENT_EXCLUDED`)
# 도메인 밖 질의는 안 뺀다 — 운영자가 물을 때는 설계 문서도 답할 값이 있다.
#
# ⚠ **식별자 채널은 도메인 밖 질의에도 켠다.** 사전 등록 §5.5 의 음성 대조군이 그것이다 —
# 「켰는데 식별자가 없어 발화 안 함」을 봐야 스위치가 조용히 무시된 것과 구별된다.
def _client(exclude):
    return nexus_client('http://localhost:8000', token=TOKEN,
                        tenant='picasso', transport=http_transport,
                        exclude_doc_types=exclude, identifier_channel=IDENTIFIERS)

# 탐색 줄도 실패를 설명하는 자리라 사건과 같은 필터를 쓴다. 도메인 밖 질의만 안 쓴다.
CLIENTS = {INCIDENT: _client(INCIDENT_EXCLUDED), SEARCH: _client(INCIDENT_EXCLUDED),
           QUERY: _client(())}
timings = []

def timed_for(kind):
    def timed(query):
        t0 = time.monotonic()
        out = CLIENTS[kind](query)
        timings.append(time.monotonic() - t0)
        return out
    return timed

rows, records = [], []
print(f'실험군 {ARM} · 식별자 채널 {"켬" if IDENTIFIERS else "끔"}')
print(f'{"":3} {"결과":10} {"벽시계":>8} {"검색":>7} {"합성":>9} {"조각":>4} {"인용":>4} {"답":>6} {"약함":>5}  새칸')
history = fixture_history()
#: 연달아 이만큼 벽에 잘리면 판을 접는다. ⛔ **브리지 벽이 기본값으로 돌아가 있으면
#: 열둘이 전부 잘리는데 그걸 40분 뒤에 안다**(2026-09-20 실측 — T0 판 아홉 중 일곱이
#: 122~126초에 잘렸고 그것은 벽 120 이라는 뜻이었다). 호스트 브리지는 `.env` 를 안 읽으므로
#: 띄울 때 `NEXUS_LLM_BRIDGE_TIMEOUT` 을 직접 줘야 하고, 안 주면 조용히 120 으로 뜬다.
#: 접는 셈은 `eval/run.py` 에 있다 — 시험이 물리는 자리이고, 셈이 두 군데면 갈린다.
straight, last_reason = 0, ''

#: 사유별로 볼 자리가 다르다. 모르는 사유면 사유만 찍고 사람에게 넘긴다.
ABORT_HINTS = {
    'timeout': ['브리지의 벽이 낮게 떠 있는 쪽을 먼저 본다.',
                '배너가 실효 벽을 말한다. 기동 배너 한 줄을 확인한다.'],
    'unavailable': ['생성이 즉시 죽는다 — 벽이 아니다. 앱과 브리지 사이를 본다.',
                    '브리지가 사는지: POST /v1/generate 가 403 을 빨리 돌려주면 프로세스는 산 것이다.',
                    '그러면 남는 것은 컨테이너에서 못 닿거나 토큰이 안 맞는 쪽이고, 둘 다 khala 자리다.'],
}

for e in entries:
    text = query_for(e, prior=history)
    timings.clear()
    r = ask_and_record(("golden", e["id"]), text, timed_for(e["kind"]), 2)
    straight = straight_failures(straight, r.outcome)
    if straight:
        last_reason = r.reason or '(사유 없음)'
        if straight >= ABORT_AFTER:
            wall = max((max(timings) if timings else 0), 0)
            print()
            print(f'판을 접는다. {ABORT_AFTER} 건 연속으로 생성이 안 섰다. 사유={last_reason} · 마지막 {wall:.0f}초.')
            for line in ABORT_HINTS.get(last_reason, ['처음 보는 사유다. 그대로 적어서 사람에게 알린다.']):
                print(' ', line)
            raise SystemExit('고치고 다시 돌린다. 이 판의 기록은 안 남긴다.')
    records.append(r)
    ans = r.answer or ""
    used = [m for m in USED.get(e["id"], []) if m in ans]
    d = r.diagnostics or {}
    t = d.get("timing") or {}
    rows.append({
        "id": e["id"], "kind": e["kind"], "outcome": r.outcome.value, "reason": r.reason,
        "attempts": r.attempts, "queryLen": len(text), "answerLen": len(ans),
        "citations": len(r.citations),
        "verified": sum(1 for c in r.citations if c.get("verified")),
        "latencies": [round(x, 1) for x in timings],
        "diagnostics": d,
        "usedNewFields": used, "usedOf": len(USED.get(e["id"], [])),
        "violations": ([w for w in (e.get("mustNotClaim") or []) if w in ans]
                       if r.outcome is not Outcome.GENERATION_FAILED else []),
        "answer": ans,
        "card": parse_card(ans),
        "citationTitles": [c.get("title") for c in r.citations],
        "citationRefs": [
            {"title": c.get("title"), "section": c.get("section"), "verified": c.get("verified"),
             # 출처 등급과 렌더된 표시 (khala 2026-09-23). 사건 질의는 전부 authored 라 빈 값이지만 운영자
             # 질의를 기록하는 날 이 둘이 없으면 표시가 기록에서 사라진다. 해석하지 않고 옮긴다.
             "provenance_tier": c.get("provenance_tier"), "provenance_mark": c.get("provenance_mark")}
            for c in r.citations
        ],
        "truthHit": [c for c in ((truth.get(e.get("bundle",{}).get("incidentId")) or {}).get("cause") or [])
                     if c in ans],
    })
    llm = t.get("llm_ms")
    print(f'{e["id"]:3} {r.outcome.value:10} {str([round(x) for x in timings]):>8} '
          f'{str(t.get("bm25_ms","?"))+"ms":>7} {(str(llm)+"ms") if llm is not None else "-":>9} '
          f'{d.get("evidence","?"):>4} {len(r.citations):>4} {len(ans):>6} '
          f'{str(d.get("weak_evidence")):>5} '
          f'미검증수{d.get("unverified_numbers","?")} 미검증인용{d.get("unverified_citations","?")}  '
          f'{len(used)}/{len(USED.get(e["id"],[]))}'
          f'{"  정답:"+",".join(rows[-1]["truthHit"][:1]) if rows[-1]["truthHit"] else ("  정답X" if (truth.get(e.get("bundle",{}).get("incidentId")) or {}).get("cause") else "")}'
          f'{"  사유="+r.reason if r.reason else ""}'
          f'{"  어긋남:"+",".join(rows[-1]["violations"]) if rows[-1]["violations"] else ""}')

s = score(entries, records, truth=truth)
# 분모는 골든셋의 사건 수다. 글자 9 로 박혀 있다가 판 7(사건 열하나)에서 `11/9` 로 찍혔다 (2026-09-22).
n_incidents = sum(1 for e in entries if e["kind"] == INCIDENT)
print()
print(f'1순위 원인    {s.primary_cause_match}  (센 것 {s.counted_incidents} · 설계일지로 뺀 것 {s.journal_cited_incidents})')
print(f'어긋남 없음   {s.contradiction_free}  (센 것 {s.counted_checked})')
print(f'인용 검증     {s.citation_pass}  (인용 {s.counted_citations})')
print(f'모른다 비율   {s.admits_no_evidence}  (질의 {s.counted_queries})')
print(f'설명 안 섬    {s.failed_incidents}/{n_incidents}')
print(f'인용 없는 답  {s.uncited_incidents}/{n_incidents}')
print(f'지어낸 수     {s.ungrounded_number_incidents}/{n_incidents}')
print(f'절차 문서 인용 {s.procedure_doc_cited}  (센 것 {s.counted_procedures})')
print(f'절차 절 인용   {s.procedure_section_cited}')
print(f'  검색이 줬나  {s.procedure_doc_retrieved}  (적중 {s.counted_retrieved})')
print(f'  받고 인용    {s.procedure_cited_when_retrieved}  <- 이 층의 몫')
print(f'탐색 줄 절차   {s.search_procedure_cited}  (센 것 {s.counted_searches})')
print(f'카드 완성      {s.cards_complete}/{n_incidents}')
model = next((r["diagnostics"].get("usage", {}).get("model") for r in rows
               if (r.get("diagnostics") or {}).get("usage")), None)
env = run_env(top_k=ANSWER_TOP_K, model=model, goldenset='eval/goldenset.json',
              exclude_doc_types=INCIDENT_EXCLUDED, arm=ARM, corpus_version=CORPUS_VERSION, auth=AUTH,
              goldenset_version=json.load(open('eval/goldenset.json', encoding='utf-8'))['version'])
print()
print('환경', json.dumps(env, ensure_ascii=False))
json.dump({"env": env, "rows": rows},
          io.open('eval/last-answers.json', 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
