import logging
import os
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from src.handlers.callbacks import start, handle_callback, handle_text

# 1. 환경 변수 로드 (.env 파일 읽기)
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# 로그 설정 (봇이 잘 돌아가는지 터미널에 표시)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN이 설정되지 않았습니다. .env 파일을 확인해주세요.")
        return

    # 2. 텔레그램 봇 어플리케이션 생성
    # Webhook 방식이 아닌 Polling 방식으로 깔끔하게 빌드합니다.
    application = Application.builder().token(BOT_TOKEN).build()

    # 3. 핸들러 등록 (사용자님이 에이전트와 정리한 로직)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # 4. 봇 실행 시작 (Polling)
    # drop_pending_updates=True는 봇이 꺼져있을 때 온 메시지를 무시하고 새로 시작하게 합니다.
    print("--- 텔레그램 봇이 Polling 모드로 시작되었습니다! ---")
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()