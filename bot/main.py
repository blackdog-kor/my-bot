"""
Admin Bot 진입점.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler

sys.path.insert(0, "/app")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "bot" / ".env")

from bot.handlers.callbacks import admin_command, start_command

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()

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

_application: Application | None = None


def build_application() -> Application:
    global _application
    if _application is not None:
        return _application
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN이 설정되지 않았습니다.")
    _application = Application.builder().token(BOT_TOKEN).build()
    _application.add_handler(CommandHandler("start", start_command))
    _application.add_handler(CommandHandler("admin", admin_command))
    return _application


async def run_bot() -> None:
    application = build_application()
    print("--- Admin Bot Polling 시작 ---", flush=True)
    async with application:
        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        await asyncio.Event().wait()


def main() -> None:
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN이 설정되지 않았습니다.")
        return
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
