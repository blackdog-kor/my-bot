"""
통합 서비스 진입점: FastAPI (트래킹 + 헬스) + Admin Bot + 스케줄러.

- GET /health → 헬스체크
- GET /track/{ref} → 클릭 기록 후 AFFILIATE_URL로 리다이렉트
- lifespan: 봇·스케줄러를 각각 스레드로 기동 (수집/발송 동시 실행 방지)
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

logger = logging.getLogger("uvicorn.error")

# repo root를 path에 추가 (bot, app import용)
ROOT = Path(__file__).resolve().parents[1]  # app/main.py -> repo root
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

AFFILIATE_URL = (os.getenv("AFFILIATE_URL") or "").strip() or "https://t.me"


def _run_bot() -> None:
    """Admin Bot 폴링 실행 (별도 스레드)."""
    try:
        from bot.main import main as bot_main
        bot_main()
    except Exception as e:
        logger.exception("Bot thread exited: %s", e)


def _run_scheduler() -> None:
    """스케줄러 루프 실행 (별도 스레드)."""
    try:
        from app.scheduler import run_scheduler_forever
        run_scheduler_forever()
    except Exception as e:
        logger.exception("Scheduler thread exited: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # PostgreSQL broadcast_targets 테이블 준비
    if (os.getenv("DATABASE_URL") or "").strip():
        try:
            from app.pg_broadcast import ensure_pg_table
            ensure_pg_table()
        except Exception as e:
            logger.warning("ensure_pg_table: %s", e)

    # Admin Bot (폴링) — 별도 스레드
    bot_thread = threading.Thread(target=_run_bot, daemon=True)
    bot_thread.start()
    logger.info("Admin Bot thread started")

    # 스케줄러 (수집 00:00, 발송 06:00, 재발송 12:00) — 별도 스레드
    sched_thread = threading.Thread(target=_run_scheduler, daemon=True)
    sched_thread.start()
    logger.info("Scheduler thread started")

    yield

    # shutdown 시 스레드는 daemon이므로 프로세스 종료 시 함께 종료됨


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/track/{ref}")
async def track_click(ref: str):
    """클릭 트래킹: mark_clicked 후 AFFILIATE_URL로 302 리다이렉트."""
    try:
        from app.pg_broadcast import mark_clicked
        mark_clicked(ref)
    except Exception as e:
        logger.warning("mark_clicked ref=%s: %s", ref, e)
    return RedirectResponse(url=AFFILIATE_URL, status_code=302)
