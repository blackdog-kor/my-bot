"""
Admin Bot 진입점 (통합 구조).
repo root를 sys.path에 넣고 bot.handlers.callbacks에서 핸들러 등록.
CHANNEL_ID 설정 시 기동 시 + 1시간 간격 채널 발송.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from telegram import Bot
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


def _run_channel_post_once() -> None:
    if not BOT_TOKEN or not CHANNEL_ID:
        return
    try:
        from app.services.premium_formatter import post_premium_to_channel
        bot = Bot(token=BOT_TOKEN)
        asyncio.run(post_premium_to_channel(bot))
    except Exception as e:
        logger.exception("채널 전송 실패: %s", e)


def main() -> None:
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN이 설정되지 않았습니다.")
        return

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("test_post", test_post_command))
    application.add_handler(CallbackQueryHandler(callback))
    application.add_handler(
        MessageHandler(
            filters.PHOTO | filters.VIDEO | filters.Document.ALL,
            admin_load_message_handler,
        )
    )
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    if CHANNEL_ID:
        _run_channel_post_once()
        scheduler = BackgroundScheduler()
        scheduler.add_job(_run_channel_post_once, "interval", hours=1, id="channel_hourly")
        scheduler.start()

    print("--- Admin Bot Polling 시작 ---", flush=True)

    async def run():
        async with application:
            await application.initialize()
            await application.start()
            await application.updater.start_polling(drop_pending_updates=True)
            await asyncio.Event().wait()

    asyncio.run(run())


async def run_bot() -> None:
    """Async entry point for app/main.py thread (별도 이벤트 루프에서 실행)."""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN이 설정되지 않았습니다.")
        return
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("test_post", test_post_command))
    application.add_handler(CallbackQueryHandler(callback))
    application.add_handler(
        MessageHandler(
            filters.PHOTO | filters.VIDEO | filters.Document.ALL,
            admin_load_message_handler,
        )
    )
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    if CHANNEL_ID:
        _run_channel_post_once()
        scheduler = BackgroundScheduler()
        scheduler.add_job(_run_channel_post_once, "interval", hours=1, id="channel_hourly")
        scheduler.start()
    async with application:
        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        await asyncio.Event().wait()


if __name__ == "__main__":
    main()
