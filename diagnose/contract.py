"""진단 계약 — `docs/superpowers/specs/2026-09-27-진단-계약-초안.md`.

**요청을 믿지 않고 읽는다.** 요청은 koshei 의 투영이 짓지만, 칸이 빠지거나 버전이 다른 것을 조용히
넘기면 이 계층에서는 「값이 없다」로 보인다 — 형식이 어긋난 것과 관측이 없는 것이 같은 모양이 된다
(`receiver/export.py` 의 `UnknownSchema` 와 같은 까닭). 어긋나면 [ContractViolation] 이고 **재시도하지
않는다** — 다시 보내도 같다. **앞에서 잡는 까닭은 말이 맞게 멈추려는 것이다** — 못 잡은 모양은 뒤에서
AttributeError 같은 엉뚱한 예외로 터지고, 워커가 뜻밖의 예외도 재시도하지 않게 해 두었지만 그 이름으로는
무엇이 어긋났는지 koshei 가 알 수 없다.
"""

import re
from dataclasses import dataclass

from receiver.export import SCHEMA_VERSION

#: 이 계층이 읽고 쓰는 계약의 버전. **한 버전만 받는다.**
CONTRACT_VERSION = "0.6"

#: 후보의 종류(계약 §3.1). 늘리려면 계약을 먼저 고친다.
KINDS = ("APPROVE_REMEDY", "CHOOSE_SOURCE", "OPERATOR_DECISION", "ESCALATE")

#: 종류마다 `ref` 에 있어야 하는 칸 — 값이 없으면 `null` 이고 칸은 빼지 않는다(§3.1, koshei 투영 v1). ⛔ 빠지면 비재시도
#: 예외다 — 칸 이름이 바뀐 요청을 「모름」으로 조용히 읽으면 답변 컨텍스트가 후보를 못 보인 채 권고가 나간다(2026-09-30,
#: `CHOOSE_SOURCE` 의 대체 자리가 `source` 에서 `alternative` 로 바뀜). 더 있는 칸은 받는다.
REF_KEYS = {
    "APPROVE_REMEDY": ("robotId", "jobOrderId", "searchId"),
    "CHOOSE_SOURCE": ("jobOrderId", "material", "missingSource", "alternative", "searchId"),
    "OPERATOR_DECISION": ("executionId", "unitId", "decision"),
}

#: 늘 들어가는 후보의 고정 식별자.
ESCALATE = "ESCALATE"

#: 요청에 **있어야 하는** 칸. 값이 `null` 이어도 키는 있어야 한다(계약 §2).
REQUIRED = ("contractVersion", "episodeId", "attempt", "snapshot", "candidates",
            "candidatesVersion", "unknowns", "history")

#: 응답의 칸, 계약 §4 의 순서대로. **하나도 빼지 않는다** — 값이 없으면 `null`, 빈 목록은 `[]`.
RESPONSE_KEYS = ("contractVersion", "episodeId", "attempt", "outcome", "candidateId", "picked",
                 "sawCandidatesVersion", "rationale", "card", "cause", "citations",
                 "unverifiedClaims", "uncitedSentences", "versions", "elapsedSeconds")

#: 확인 불가 항목과 이력 항목의 칸(계약 §3.3 · §3.4). **키를 빼지 않는다** — 값이 없으면 `null` 이다(§2).
UNKNOWN_KEYS = ("subject", "what", "since", "source")
HISTORY_KEYS = ("attempt", "candidatesVersion", "diagnosis", "approval", "dispatch", "evidence", "closedAs", "at")

_VERSION = re.compile(r"sha256:[0-9a-f]{64}")


class ContractViolation(Exception):
    """요청이 계약과 어긋난다. **다시 보내도 같다** — 재시도하지 않는다."""


@dataclass(frozen=True)
class Request:
    """읽은 요청. 후보 · 확인 불가 · 이력은 받은 사전 그대로 든다 — 이 계층이 모양을 바꾸지 않는다."""

    episode_id: str
    attempt: int
    candidates: tuple
    candidates_version: str
    snapshot: dict
    unknowns: tuple
    history: tuple

    @property
    def key(self):
        """결과 캐시의 멱등성 키 `(episodeId, attempt, candidatesVersion)`(계약 §6)."""
        return (self.episode_id, self.attempt, self.candidates_version)

    @property
    def candidate_ids(self):
        return tuple(c["candidateId"] for c in self.candidates)


def parse_request(payload):
    """요청 하나를 읽는다. 어긋나면 [ContractViolation]."""
    if not isinstance(payload, dict):
        raise ContractViolation("요청이 JSON 객체가 아니다")
    missing = [k for k in REQUIRED if k not in payload]
    if missing:
        raise ContractViolation(f"요청에 칸이 없다: {missing}")
    if payload["contractVersion"] != CONTRACT_VERSION:
        raise ContractViolation(
            f"읽을 줄 아는 계약 판은 {CONTRACT_VERSION!r} 인데 {payload['contractVersion']!r} 가 왔다")
    episode_id, attempt = payload["episodeId"], payload["attempt"]
    if not isinstance(episode_id, str) or not episode_id:
        raise ContractViolation(f"episodeId 가 비었다: {episode_id!r}")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise ContractViolation(f"attempt 는 1 이상의 정수다: {attempt!r}")
    version = payload["candidatesVersion"]
    if not isinstance(version, str) or not _VERSION.fullmatch(version):  # match 의 $ 는 끝 줄바꿈을 받는다
        raise ContractViolation(f"candidatesVersion 은 sha256:<16진 소문자 64자> 다: {version!r}")
    return Request(
        episode_id=episode_id,
        attempt=attempt,
        candidates=_candidates(payload["candidates"]),
        candidates_version=version,
        snapshot=_snapshot(payload["snapshot"]),
        unknowns=_items(payload["unknowns"], "unknowns", UNKNOWN_KEYS, ("subject",)),
        history=_items(payload["history"], "history", HISTORY_KEYS,
                       ("diagnosis", "approval", "dispatch", "evidence")),
    )


def response(request, *, outcome, candidate_id, picked, rationale, card, cause, citations,
             unverified_claims, uncited_sentences, versions, elapsed):
    """응답 하나. 칸은 [RESPONSE_KEYS] 순서 그대로이고 **하나도 빼지 않는다.**"""
    return {
        "contractVersion": CONTRACT_VERSION,
        "episodeId": request.episode_id,
        "attempt": request.attempt,
        "outcome": outcome,
        "candidateId": candidate_id,
        "picked": picked,
        "sawCandidatesVersion": request.candidates_version,
        "rationale": rationale,
        "card": list(card),
        "cause": cause,
        "citations": list(citations),
        "unverifiedClaims": list(unverified_claims),
        "uncitedSentences": list(uncited_sentences),
        "versions": dict(versions),
        "elapsedSeconds": elapsed,
    }


def _candidates(value):
    if not isinstance(value, list) or not value:
        raise ContractViolation("candidates 는 비지 않은 목록이다")
    seen = set()
    for c in value:
        if not isinstance(c, dict) or not isinstance(c.get("candidateId"), str) or not c["candidateId"]:
            raise ContractViolation(f"후보의 candidateId 는 비지 않은 글자다: {c!r}")
        cid, kind = c["candidateId"], c.get("kind")
        if kind not in KINDS:
            raise ContractViolation(f"모르는 후보 종류: {kind!r}")
        if (kind == ESCALATE) != (cid == ESCALATE):
            raise ContractViolation(f"종류 ESCALATE 와 식별자 ESCALATE 는 함께 간다: {cid} · {kind}")
        if "ref" not in c:
            raise ContractViolation(f"후보에 ref 칸이 없다: {cid}")
        if not (isinstance(c["ref"], dict) or (c["ref"] is None and kind == ESCALATE)):
            raise ContractViolation(f"ref 는 객체다 — null 은 ESCALATE 만: {cid}")
        skills = c.get("sawSkillTypes")
        if skills is not None and not (isinstance(skills, list) and all(isinstance(x, str) for x in skills)):
            raise ContractViolation(f"sawSkillTypes 는 글자의 목록이다: {cid}")
        if kind != ESCALATE:
            missing = [key for key in REF_KEYS[kind] if key not in c["ref"]]
            if missing:
                raise ContractViolation(f"{kind} 의 ref 에 {' · '.join(missing)} 칸이 없다: {cid}")
        if kind == "APPROVE_REMEDY" and skills is None:
            raise ContractViolation(f"APPROVE_REMEDY 에는 sawSkillTypes 목록이 있어야 한다: {cid}")
        if cid in seen:
            raise ContractViolation(f"후보 식별자가 겹친다: {cid}")
        seen.add(cid)
    if ESCALATE not in seen:
        raise ContractViolation("ESCALATE 후보가 없다 — 늘 들어간다(계약 §3.1)")
    return tuple(value)


def _snapshot(value):
    if not isinstance(value, dict):
        raise ContractViolation("snapshot 은 객체다")
    for name in ("manifest", "incidents", "searches"):
        if name not in value:
            raise ContractViolation(f"snapshot 에 {name} 가 없다")
    manifest = value["manifest"]
    if not isinstance(manifest, dict):
        raise ContractViolation(f"snapshot 의 manifest 는 객체다: {manifest!r}")
    found = manifest.get("schemaVersion")
    if found != SCHEMA_VERSION:
        raise ContractViolation(f"읽을 줄 아는 적재 판은 {SCHEMA_VERSION!r} 인데 {found!r} 가 왔다")
    _rows(value["incidents"], "incidents", "digest")
    _rows(value["searches"], "searches", "searchId")
    if not value["incidents"] and not value["searches"]:
        raise ContractViolation("snapshot 에 질의로 옮길 줄이 없다 — 두 목록이 다 비었다")
    return value


def _rows(rows, name, identity):
    """picasso 줄 그대로인지 — 객체이고 그 줄의 식별자(`receiver/idempotency.py` 의 멱등성 키 칸)가 있다."""
    if not isinstance(rows, list):
        raise ContractViolation(f"snapshot 의 {name} 는 목록이다")
    for row in rows:
        if not isinstance(row, dict) or not row.get(identity):
            raise ContractViolation(f"snapshot 의 {name} 줄은 picasso 줄 그대로다({identity} 가 있다): {row!r}")


def _items(items, name, required, nested):
    """확인 불가 · 이력의 항목. 객체이고, 칸([required])이 다 있고, 안의 칸([nested])은 객체이거나 `null` 이다.
    빠진 칸을 `null` 로 읽지 않는다 — 「못 닿았다」와 「안 적혔다」가 같은 모양이 된다."""
    if not isinstance(items, list):
        raise ContractViolation(f"{name} 는 목록이다(없으면 []): {items!r}")
    for item in items:
        if not isinstance(item, dict):
            raise ContractViolation(f"{name} 의 항목은 객체다: {item!r}")
        missing = [key for key in required if key not in item]
        if missing:
            raise ContractViolation(f"{name} 항목에 칸이 없다: {missing}")
        for key in nested:
            if item.get(key) is not None and not isinstance(item[key], dict):
                raise ContractViolation(f"{name} 항목의 {key} 는 객체이거나 null 이다: {item[key]!r}")
    return tuple(items)
