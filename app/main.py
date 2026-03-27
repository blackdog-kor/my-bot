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
