import asyncio
import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from telegram import Bot
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from src.handlers.callbacks import admin_command, callback, start, text_handler


load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = (os.getenv("CHANNEL_ID") or "").strip()

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
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN이 설정되지 않았습니다. .env 파일을 확인해주세요.")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CallbackQueryHandler(callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    if CHANNEL_ID:
        logger.info("CHANNEL_ID 설정됨: 기동 시 채널에 게시물 1건 전송 후 1시간 간격 발송")
        _run_channel_post_once()
        scheduler = BackgroundScheduler()
        scheduler.add_job(_run_channel_post_once, "interval", hours=1, id="channel_hourly")
        scheduler.start()
    else:
        logger.warning("CHANNEL_ID 미설정 — 채널 자동 발송 비활성화. Railway bot 서비스 Variables에 CHANNEL_ID(-100...) 추가 후 재배포하세요.")

    print("--- 텔레그램 봇이 Polling 모드로 시작되었습니다! ---")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()