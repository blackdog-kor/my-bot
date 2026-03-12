import asyncio
import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from telegram import Bot
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from src.handlers.callbacks import (
    admin_command,
    admin_load_message_handler,
    callback,
    start,
    text_handler,
    test_post_command,
)


load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Initialize PostgreSQL broadcast_targets table if DATABASE_URL is set
if (os.getenv("DATABASE_URL") or "").strip():
    try:
        from app.pg_broadcast import ensure_pg_table
        ensure_pg_table()
    except Exception as _pg_e:
        print(f"[PG] broadcast_targets init failed: {_pg_e}", flush=True)
CHANNEL_ID = (os.getenv("CHANNEL_ID") or "").strip()

# 레일 로그에서 반드시 보이도록 stdout에 즉시 출력 (버퍼 없음)
if CHANNEL_ID:
    print("[ENV] CHANNEL_ID=설정됨 (끝4자리:%s)" % (CHANNEL_ID[-4:] if len(CHANNEL_ID) >= 4 else "?"), flush=True)
else:
    print("[ENV] CHANNEL_ID=미설정 — 채널 발송 안 함. Railway bot 서비스 Variables에 CHANNEL_ID(-100...) 추가 후 재배포", flush=True)

_CHANNEL_ID_DBG = "설정됨(끝4자리:%s)" % CHANNEL_ID[-4:] if len(CHANNEL_ID) >= 4 else ("미설정(길이=%s)" % len(CHANNEL_ID))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def _run_channel_post_once() -> None:
    """스케줄러/기동 시 채널에 프리미엄 게시물 1건 전송 (별도 스레드에서 asyncio.run)."""
    if not BOT_TOKEN:
        return
    if not CHANNEL_ID:
        logger.warning("CHANNEL_ID 미설정 — 채널 전송 비활성화. 레일 변수에 CHANNEL_ID(-100...) 추가 후 재배포하세요.")
        return
    logger.info("채널 게시물 1건 전송 시도 중...")
    try:
        from app.services.premium_formatter import post_premium_to_channel
        bot = Bot(token=BOT_TOKEN)
        asyncio.run(post_premium_to_channel(bot))
    except Exception as e:
        logger.exception("채널 전송 실패: %s", e)


def main() -> None:
    logger.info("기동 시 env: CHANNEL_ID=%s", _CHANNEL_ID_DBG)
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN이 설정되지 않았습니다. .env 파일을 확인해주세요.")
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
        logger.info("CHANNEL_ID 설정됨: 기동 시 채널에 게시물 1건 전송 후 1시간 간격 발송")
        _run_channel_post_once()
        scheduler = BackgroundScheduler()
        scheduler.add_job(_run_channel_post_once, "interval", hours=1, id="channel_hourly")
        scheduler.start()
    else:
        logger.warning("CHANNEL_ID 미설정 — 채널 자동 발송 비활성화. Railway bot 서비스 Variables에 CHANNEL_ID(-100...) 추가 후 재배포하세요.")

    ch_status = "CHANNEL_ID=설정됨(끝4자리:%s)" % CHANNEL_ID[-4:] if (CHANNEL_ID and len(CHANNEL_ID) >= 4) else "CHANNEL_ID=미설정(채널발송안함)"
    print("--- 텔레그램 봇 Polling 시작 | %s ---" % ch_status, flush=True)
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()