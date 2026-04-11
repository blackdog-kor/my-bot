import logging
import os
import sys
import threading

sys.path.insert(0, "/app")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.responses import RedirectResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

AFFILIATE_URL = os.getenv("AFFILIATE_URL", "https://t.me")


def _run_bot():
    try:
        from bot.main import main as bot_main
        logger.info("Admin Bot thread started")
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(bot_main())
    except Exception as e:
        logger.warning("Bot thread exited: %s", e)


def _run_scheduler():
    try:
        from app.scheduler import run_scheduler_forever
        logger.info("Scheduler thread started")
        run_scheduler_forever()
    except Exception as e:
        logger.error("Scheduler thread exited: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # DB 테이블 초기화
    try:
        from app.pg_broadcast import ensure_pg_table
        ensure_pg_table()
    except Exception as e:
        logger.warning("ensure_pg_table: %s", e)

    try:
        from app.pg_broadcast import ensure_loaded_message_table
        ensure_loaded_message_table()
    except Exception as e:
        logger.warning("ensure_loaded_message_table: %s", e)

    # Bot 스레드 시작
    try:
        bot_thread = threading.Thread(target=_run_bot, daemon=True)
        bot_thread.start()
    except Exception as e:
        logger.warning("Bot thread start failed: %s", e)

    # Scheduler 스레드 시작
    try:
        sched_thread = threading.Thread(target=_run_scheduler, daemon=True)
        sched_thread.start()
    except Exception as e:
        logger.warning("Scheduler thread start failed: %s", e)

    yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/track/{ref}")
def track(ref: str):
    try:
        from app.pg_broadcast import mark_clicked
        mark_clicked(ref)
    except Exception as e:
        logger.warning("mark_clicked failed for ref=%s: %s", ref, e)
    return RedirectResponse(url=AFFILIATE_URL, status_code=302)


@app.get("/debug/session-test")
async def debug_session_test():
    """각 SESSION_STRING으로 Pyrogram 연결을 시도하고 성공/실패 결과를 반환."""
    import asyncio

    api_id   = int(os.getenv("API_ID",   "0") or "0")
    api_hash = (os.getenv("API_HASH") or "").strip()

    if not api_id or not api_hash:
        return {"error": "API_ID 또는 API_HASH 환경변수가 설정되지 않았습니다."}

    # 세션 목록 수집 (SESSION_STRING_1 ~ SESSION_STRING_10, 없으면 SESSION_STRING)
    sessions: list[tuple[str, str]] = []
    for i in range(1, 11):
        key = f"SESSION_STRING_{i}"
        val = (os.getenv(key) or "").strip()
        if val:
            sessions.append((key, val))
    if not sessions:
        val = (os.getenv("SESSION_STRING") or "").strip()
        if val:
            sessions.append(("SESSION_STRING", val))

    if not sessions:
        return {"error": "SESSION_STRING 환경변수가 설정되지 않았습니다."}

    results: list[dict] = []

    for label, session_string in sessions:
        entry: dict = {"label": label, "session_length": len(session_string)}
        try:
            from pyrogram import Client as PyroClient

            async with PyroClient(
                name=f"test_{label}",
                api_id=api_id,
                api_hash=api_hash,
                session_string=session_string,
                in_memory=True,
            ) as client:
                me = await client.get_me()
                entry["status"]   = "ok"
                entry["user_id"]  = me.id
                entry["username"] = me.username or "(없음)"
                entry["name"]     = f"{me.first_name or ''} {me.last_name or ''}".strip()
        except Exception as exc:
            entry["status"] = "fail"
            entry["error"]  = f"{type(exc).__name__}: {exc}"
            logger.exception("session-test 실패 [%s]", label)

        results.append(entry)

    ok_count   = sum(1 for r in results if r["status"] == "ok")
    fail_count = len(results) - ok_count
    return {
        "api_id":     api_id,
        "api_hash":   api_hash[:6] + "..." if api_hash else "(없음)",
        "total":      len(results),
        "ok":         ok_count,
        "failed":     fail_count,
        "sessions":   results,
    }


@app.get("/debug/status")
async def debug_status():
    # 1. loaded_message 확인
    try:
        from app.pg_broadcast import get_loaded_message
        loaded = get_loaded_message()
        loaded_status = str(loaded) if loaded else "None (장전 없음)"
    except Exception as e:
        loaded_status = f"오류: {e}"

    # 2. SESSION_STRING 개수 확인
    sessions = []
    for i in range(1, 11):
        k = f"SESSION_STRING_{i}"
        if os.getenv(k):
            sessions.append(k)
    if not sessions and os.getenv("SESSION_STRING"):
        sessions.append("SESSION_STRING")

    # 3. DB 미발송 타겟 수 확인
    try:
        from app.pg_broadcast import count_unsent_with_username
        unsent = count_unsent_with_username()
    except Exception as e:
        unsent = f"오류: {e}"

    # 4. scripts 경로 확인
    script_path = os.path.join(
        os.path.dirname(__file__), "..", "scripts", "dm_campaign_runner.py"
    )
    script_exists = os.path.exists(os.path.abspath(script_path))

    # 5. DB 연결 확인
    try:
        from app.pg_broadcast import get_db_connection
        conn = get_db_connection()
        conn.close()
        db_status = "연결됨"
    except Exception as e:
        db_status = f"오류: {e}"

    return {
        "loaded_message": loaded_status,
        "sessions": sessions,
        "session_count": len(sessions),
        "unsent_targets": unsent,
        "script_exists": script_exists,
        "db_status": db_status,
        "python": sys.executable,
        "affiliate_url": AFFILIATE_URL[:30] + "..." if len(AFFILIATE_URL) > 30 else AFFILIATE_URL,
    }
