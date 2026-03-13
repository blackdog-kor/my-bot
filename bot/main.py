"""
Admin Bot 진입점 (통합 구조).
Application 인스턴스는 프로세스당 1개만 생성하고 main()/run_bot() 이 공유.
채널 발송(1시간 간격)은 app/scheduler.py 로 이전.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

# Railway 배포 환경 모듈 경로 (bot.src 등)
sys.path.insert(0, "/app")

# 통합 구조: repo root = parent of bot/
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "bot" / ".env")

from bot.handlers.callbacks import (
    admin_command,
    admin_load_message_handler,
    callback,
    start,
    text_handler,
    test_post_command,
)

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHANNEL_ID = (os.getenv("CHANNEL_ID") or "").strip()

if (os.getenv("DATABASE_URL") or "").strip():
    try:
        from app.pg_broadcast import ensure_pg_table
        ensure_pg_table()
    except Exception as e:
        print(f"[PG] ensure_pg_table: {e}", flush=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Application 단일 인스턴스 (프로세스당 1개)
# ---------------------------------------------------------------------------
_application: Application | None = None


def build_application() -> Application:
    """Application 인스턴스를 1회만 생성하고 반환. main()과 run_bot()이 공유."""
    global _application
    if _application is not None:
        return _application
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN이 설정되지 않았습니다.")
    _application = Application.builder().token(BOT_TOKEN).build()
    _application.add_handler(CommandHandler("start", start))
    _application.add_handler(CommandHandler("admin", admin_command))
    _application.add_handler(CommandHandler("test_post", test_post_command))
    _application.add_handler(CallbackQueryHandler(callback))
    _application.add_handler(
        MessageHandler(
            filters.PHOTO | filters.VIDEO | filters.Document.ALL,
            admin_load_message_handler,
        )
    )
    _application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    return _application


async def run_bot() -> None:
    """폴링 실행 (main() 또는 app/main.py 스레드에서 호출). 단일 Application 사용."""
    application = build_application()
    print("--- Admin Bot Polling 시작 ---", flush=True)
    async with application:
        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        await asyncio.Event().wait()


def main() -> None:
    """직접 실행 시 (python -m bot.main): asyncio.run(run_bot()) 1곳만 호출."""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN이 설정되지 않았습니다.")
        return
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
