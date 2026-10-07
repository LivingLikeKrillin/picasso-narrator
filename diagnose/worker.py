"""Temporal 액티비티 워커 — 진단 계약 0.6 §2. 큐 `narrator-tq`, 액티비티 `diagnose`.

**얇다.** 판단은 `diagnose.core` 에 있고 여기는 Temporal 과 주고받기만 한다 — 하트비트, 취소, 예외의 모양.

**예외의 모양이 재시도를 정한다.** 재시도할 만한 생성 실패만 재시도 가능하다. 계약 위반 · 답변 컨텍스트를 못 지음 ·
재시도 안 할 생성 실패 · **이 계층의 뜻밖의 예외**는 `non_retryable` 이다 — 모르는 것을 재시도 가능으로 치지
않는다(계약 §5 의 `other` 와 같은 까닭). 재시도의 주인은 Temporal 하나다 — 이 계층은 한 번만 묻는다.

**취소는 이 계층이 스스로 본다.** 동기 액티비티의 스레드에 SDK 가 취소 예외를 던져 넣지 않게 하고
(`no_thread_cancel_exception`), 기다리는 고리가 `is_cancelled` 를 본다 — 던져 넣은 예외가 잡기와 적기 사이에
떨어지면 잡은 것이 임대가 끝날 때까지 남는다. 취소는 하트비트의 답으로만 오므로 늦으면 수십 초 걸린다.

**khala 에 가는 호출은 동시 한도를 넘지 않는다.** 취소돼 떠난 백그라운드 스레드도 khala 를 끝까지 부르므로, 활동 칸이
비었다고 새 진단이 바로 khala 에 가면 한도를 넘는다. 그래서 호출을 한 프로세스의 세마포어로 감싼다. ⚠ **그 문은 이
프로세스 안의 것이다** — 같은 브리지를 부르는 다른 것(설명 파이프라인 실행 `python -m receiver` · 측정)과 함께 돌리면 한도를 넘는다.

    python -m diagnose.worker      # 저장소 뿌리에서. 설정은 환경 변수(아래 main). 내릴 때는 Ctrl+C

⚠ **우아하게 내리는 길은 Ctrl+C 하나다.** 다른 신호(SIGTERM · Ctrl+Break · 창 닫기)로 끝나면 도는 진단도, 취소로 끝난
시도의 백그라운드 스레드도 기다리지 않는다 — 그 답은 버려지고, 임대가 끝나면 다음 시도가 khala 를 다시 부른다.
"""

import asyncio
import logging
import os
import pathlib
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from temporalio import activity
from temporalio.client import Client
from temporalio.exceptions import ApplicationError, CancelledError
from temporalio.worker import Worker

from diagnose.context import ContextTooLarge
from diagnose.contract import ContractViolation
from diagnose.core import Cancelled, diagnose, drain
from diagnose.judge import DiagnoseFailed
from diagnose.store import FirstResultStore
from explainer.client import INCIDENT_EXCLUDED, nexus_client
from explainer.transport import http_transport

TASK_QUEUE = "narrator-tq"

#: 하트비트 간격(초). koshei 의 HeartbeatTimeout 30 초 안에 세 번(계약 §2).
BEAT = 10.0

#: 결과 캐시의 자리. **저장소 뿌리에 고정한다** — 작업 디렉터리를 따르면 다른 자리에서 띄운 워커가 다른
#: 저장소를 써서 「저장소는 하나」(계약 §6)가 깨진다. 같은 까닭으로 한 호스트의 워커는 한 체크아웃에서 띄운다 —
#: 체크아웃마다 제 저장소를 가진다. 둘에서 띄우려면 `NARRATOR_DIAGNOSE_STORE` 로 같은 절대 경로를 준다.
STORE = pathlib.Path(__file__).resolve().parents[1] / "diagnose-first-result.sqlite3"

#: 워커를 내릴 때 도는 진단을 기다리는 시간 — StartToClose 540 초(계약 §2). 짧으면 내리는 사이 백그라운드 스레드가
#: 프로세스와 함께 죽어 다음 시도가 khala 를 다시 부른다.
SHUTDOWN = timedelta(seconds=540)

#: `python -m` 으로 돌면 `__name__` 이 `__main__` 이라 이름을 박는다
log = logging.getLogger("diagnose.worker")


def make_client(base, token, tenant, transport=http_transport):
    """진단 경로의 클라이언트 — `answer_context -> search`. 사건 질의에서 설계 문서를 빼고(`INCIDENT_EXCLUDED`) 식별자 채널을
    켠다. [main] 과 시험이 같은 함수를 쓰게 모듈 수준에 둔다 — 권고 측정기의 클라이언트(`eval/recommend.py` 의 `client_for`)와는
    빼는 종류의 `case` 하나만 다르다."""

    def client(answer_context):
        return nexus_client(base, token=token, tenant=tenant, transport=transport,
                            exclude_doc_types=INCIDENT_EXCLUDED, identifier_channel=True,
                            answer_context=answer_context)

    return client


def make_activity(client, store, commit, gate=None, search_text=False):
    """`diagnose` 액티비티. 의존을 주입받아 테스트가 실제 서비스 없이 문다. [search_text] 는 검색 텍스트(Q3)를 실을지다 —
    기본은 꺼짐이고 [main] 이 켠다."""

    # ⛔ **입력에 타입 힌트를 달지 않는다 (묶음 5 검토, 2026-09-28).** SDK 는 힌트로 입력을 먼저 풀고, 못 풀면 이 함수에
    # 들어오기 전에 재시도할 실패(`Failed decoding arguments`)로 적는다 — 객체가 아닌 요청이 계약 위반(재시도 안 함,
    # 계약 §5 의 「요청 해독 불가」)이 아니게 됐다. 모양은 `parse_request` 가 본다. 인자 수가 틀린 호출은 여전히 SDK 가
    # 재시도할 실패로 적는데 그대로 둔다 — 함수 몸에 들어오기 전이라 khala 를 안 부르고, koshei 의 호출 모양은 하나다.
    @activity.defn(name="diagnose", no_thread_cancel_exception=True)
    def diagnose_activity(payload) -> dict:
        try:
            return diagnose(payload, client=client, store=store, commit=commit, gate=gate,
                            beat=_beat, cancelled=activity.is_cancelled, poll=BEAT, search_text=search_text)
        except Cancelled as error:
            raise CancelledError(str(error)) from error
        except (ContractViolation, ContextTooLarge) as error:
            raise ApplicationError(str(error), type=type(error).__name__, non_retryable=True) from error
        except DiagnoseFailed as error:
            # 사유는 khala 가 준 값이다 — 글자가 아니면 SDK 가 실패를 못 적고 재시도할 실패로 바꿔 적는다
            raise ApplicationError(str(error), type=str(error.reason),
                                   non_retryable=not error.retryable) from error
        except Exception as error:  # 뜻밖의 것 — 모르는 것을 재시도 가능으로 치지 않는다
            raise ApplicationError(str(error) or type(error).__name__, type=type(error).__name__,
                                   non_retryable=True) from error

    return diagnose_activity


def _beat():
    """하트비트 한 번. ⛔ **제때 안 받아진 하트비트는 실패가 아니다 (묶음 5 검토, 2026-09-28).** 동기 액티비티의
    하트비트는 이벤트 루프가 10초 안에 받지 않으면 `TimeoutError` 를 던진다. 그대로 올리면 뜻밖의 예외라 재시도하지
    않는 실패가 되는데, 진단은 멀쩡하다 — 백그라운드 스레드가 멱등성 키를 쥐고 답을 적는다. 다음 주기에 다시 알리고, 끝내 안
    닿으면 서버의 HeartbeatTimeout 이 이 시도를 끝낸다(계약 §5). 루프가 닫혔다는 것 같은 다른 예외는 그대로 올린다."""
    try:
        activity.heartbeat()
    except TimeoutError:
        activity.logger.warning("하트비트가 10초 안에 안 받아졌다 — 다음 주기에 다시 알린다")


def _commit():
    """이 계층의 버전 — 환경 변수가 있으면 그것, 없으면 짧은 커밋 해시. 환경 변수의 앞뒤 공백은 떼고 공백만이면 없는 것으로 본다 —
    koshei 는 버전 필드가 `null` 이거나 공백만이 아닌 글자이기를 본다. **추적하는 파일에 커밋하지 않은 고침이 있으면
    `-dirty` 가 붙는다** — `narratorCommit` 은 「왜 달라졌나」를 가르는 칸이라(계약 §4) 고친 채 돈 것을 깨끗한 버전으로 적지
    않는다. 새로 만들어 아직 추적하지 않는 파일은 못 본다."""
    given = (os.environ.get("NARRATOR_COMMIT") or "").strip()
    if given:
        return given
    return subprocess.run(["git", "describe", "--always", "--dirty", "--exclude=*"], capture_output=True,
                          text=True, check=True, cwd=STORE.parent).stdout.strip()


async def main():
    """환경 변수로 선다. **토큰 값은 저장소에 두지 않는다** — `NEXUS_TOKEN` 으로만 받는다."""
    token = os.environ.get("NEXUS_TOKEN")
    if not token:
        raise SystemExit("Nexus 토큰이 없다. NEXUS_TOKEN 으로 준다. 값은 저장소에 두지 않는다 (.secrets/nexus-tokens.env)")
    concurrency = os.environ.get("NARRATOR_DIAGNOSE_CONCURRENCY", "1")
    if not concurrency.isdecimal() or int(concurrency) < 1:
        raise SystemExit(f"NARRATOR_DIAGNOSE_CONCURRENCY 는 1 이상의 정수다(받은 값 {concurrency!r}). 브리지의 동시 한도에 맞춘다")
    concurrency = int(concurrency)
    base = os.environ.get("NEXUS_URL", "http://localhost:8000")
    tenant = os.environ.get("NEXUS_TENANT", "picasso")

    client = make_client(base, token, tenant, http_transport)
    gate = threading.BoundedSemaphore(concurrency)
    # 상대 경로는 작업 디렉터리가 아니라 저장소 뿌리에서 푼다(`STORE` 의 까닭). 절대 경로는 그대로고, 비었으면 기본 자리다
    store = FirstResultStore(STORE.parent / (os.environ.get("NARRATOR_DIAGNOSE_STORE") or STORE.name))
    commit = _commit()
    temporal = await Client.connect(os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"),
                                    namespace=os.environ.get("TEMPORAL_NAMESPACE", "default"))
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        worker = Worker(temporal, task_queue=TASK_QUEUE,
                        # 진단 경로에서 검색 텍스트(Q3)를 켜는 자리는 여기 하나다(설계서 `2026-10-07-운영-검색-텍스트`)
                        activities=[make_activity(client, store, commit, gate, search_text=True)],
                        activity_executor=executor, max_concurrent_activities=concurrency,
                        graceful_shutdown_timeout=SHUTDOWN)
        log.info("%s 에 선다 — 판 %s, 동시 한도 %d, 첫 결과 저장소 %s", TASK_QUEUE, commit, concurrency, store.path)
        try:
            await worker.run()
        finally:
            # 취소로 끝난 액티비티의 백그라운드 스레드는 위의 기다림에 안 든다 — 답을 적고 끝나기를 따로 기다린다(계약 §6).
            # `finally` 인 까닭은 Ctrl+C 다 — 그때 `run()` 은 우아한 종료를 마친 뒤 취소 예외를 다시 올린다.
            log.info("취소로 끝난 시도의 곁 스레드를 기다린다 — 길어야 %s", SHUTDOWN)
            if not await asyncio.get_running_loop().run_in_executor(None, drain, SHUTDOWN.total_seconds()):
                log.warning("곁 스레드가 %s 안에 안 끝났다 — 그 답은 버려지고, 임대가 끝나면 다음 시도가 다시 묻는다", SHUTDOWN)


if __name__ == "__main__":
    # SDK 의 알림(내리기 시작함 · 기다리는 시간)도 이것으로 보인다 — 안 보이면 내리는 동안 멈춘 줄 알고 Ctrl+C 를
    # 또 누르게 되고, 두 번째 Ctrl+C 는 SDK 의 우아한 종료를 끊는다(묶음 5 검토)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
