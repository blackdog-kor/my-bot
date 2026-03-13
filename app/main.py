"""
통합 서비스 진입점: FastAPI (트래킹 + 헬스) + 선택적 Bot/스케줄러.
임포트 실패 시 로그만 남기고 서버는 항상 정상 기동.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

# Railway 배포 환경 모듈 경로 (app.pg_broadcast, app.scheduler 등)
sys.path.insert(0, "/app")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

logger = logging.getLogger("uvicorn.error")

# repo root를 path에 추가 (선택적 app/bot 모듈용)
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

AFFILIATE_URL = (os.getenv("AFFILIATE_URL") or "").strip() or "https://t.me"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 3. 앱 시작 시 ensure_pg_table() (실패 시 로그만)
    if (os.getenv("DATABASE_URL") or "").strip():
        try:
            from app.pg_broadcast import ensure_pg_table
            ensure_pg_table()
            logger.info("ensure_pg_table OK")
        except Exception as e:
            logger.warning("ensure_pg_table: %s", e)

    # 4. bot.main / app.scheduler 스레드 (별도 이벤트 루프에서 bot 실행)
    def _run_bot() -> None:
        try:
            import asyncio
            from bot.main import run_bot as bot_main
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(bot_main())
        except Exception as e:
            logger.exception("Bot thread exited: %s", e)

    def _run_scheduler() -> None:
        try:
            from app.scheduler import run_scheduler_forever
            run_scheduler_forever()
        except Exception as e:
            logger.exception("Scheduler thread exited: %s", e)

    try:
        t = threading.Thread(target=_run_bot, daemon=True)
        t.start()
        logger.info("Admin Bot thread started")
    except Exception as e:
        logger.warning("Bot thread not started: %s", e)

    try:
        t = threading.Thread(target=_run_scheduler, daemon=True)
        t.start()
        logger.info("Scheduler thread started")
    except Exception as e:
        logger.warning("Scheduler thread not started: %s", e)

    yield


# ---------------------------------------------------------------------------
# 1. FastAPI 기본 구조 + /health + /track/{ref}
# 2. /track/{ref} 에 mark_clicked 연결 (실패 시 로그만, 리다이렉트는 항상)
# ---------------------------------------------------------------------------

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
        logger.warning("mark_clicked ref=%s: %s", ref, e)
    return RedirectResponse(url=AFFILIATE_URL, status_code=302)
