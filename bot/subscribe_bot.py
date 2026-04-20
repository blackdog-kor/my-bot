"""
Subscribe Bot — 엔트리포인트.

모든 핸들러 로직은 bot/handlers/ 모듈에 분리되어 있습니다.
이 파일은 Application 빌드, 핸들러 등록, 실행만 담당합니다.

환경변수:
  SUBSCRIBE_BOT_TOKEN  — 이 봇의 토큰 (필수)
  AFFILIATE_URL        — 환영 메시지 인라인 버튼 URL (campaign_config 폴백)
  ADMIN_ID             — 관리자 Telegram user_id
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from bot.handlers import CHANNEL_ID, SUBSCRIBE_BOT_TOKEN, is_admin, logger
from bot.handlers.admin_menu import admin_command, admin_media_handler, handle_admin_callbacks
from bot.handlers.config_handler import handle_config_callbacks, text_input_handler
from bot.handlers.push_handler import channel_post_handler, handle_push_confirm
from bot.handlers.start_handler import start_command
from bot.handlers.topics_handler import handle_topics_callbacks


# ── 통합 콜백 라우터 ──────────────────────────────────────────────────────────


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """모든 콜백 쿼리를 각 핸들러 모듈로 라우팅."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data or ""

    if not is_admin(query.from_user.id if query.from_user else None):
        return

    # 각 핸들러에 순차 위임 (처리하면 True 반환)
    if await handle_admin_callbacks(data, query, context):
        return
    if await handle_config_callbacks(data, query, context):
        return
    if await handle_topics_callbacks(data, query, context):
        return
    if await handle_push_confirm(data, query, context):
        return


# ── set_my_commands — 텔레그램 UI 명령어 자동완성 ────────────────────────────


async def _set_commands(application: Application) -> None:
    """봇 시작 시 관리자 명령어 목록 등록."""
    commands = [
        BotCommand("start", "시작 / 환영 메시지"),
        BotCommand("admin", "관리자 메뉴"),
        BotCommand("agent", "AI 에이전트 작업 제출"),
        BotCommand("agentstatus", "에이전트 큐 상태"),
        BotCommand("settoken", "사이트 토큰 저장"),
        BotCommand("tokeninfo", "토큰 볼트 상태"),
        BotCommand("refreshtoken", "토큰 강제 갱신"),
        BotCommand("win1info", "1win 계정 정보"),
        BotCommand("win1stats", "1win 최근 통계"),
        BotCommand("win1report", "1win N일 리포트"),
    ]
    try:
        await application.bot.set_my_commands(commands)
        logger.info("Bot commands registered (%d)", len(commands))
    except Exception as e:
        logger.warning("set_my_commands failed: %s", e)


# ── 봇 빌드 / 실행 ────────────────────────────────────────────────────────────


def build_application() -> Application:
    """Application 인스턴스 생성 + 모든 핸들러 등록."""
    if not SUBSCRIBE_BOT_TOKEN:
        raise RuntimeError("SUBSCRIBE_BOT_TOKEN이 설정되지 않았습니다.")
    app = Application.builder().token(SUBSCRIBE_BOT_TOKEN).build()

    # 기본 커맨드
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("admin", admin_command))

    # 에이전트 커맨드
    try:
        from bot.handlers.agent_cmd import cmd_agent, cmd_agent_status
        app.add_handler(CommandHandler("agent", cmd_agent))
        app.add_handler(CommandHandler("agentstatus", cmd_agent_status))
    except Exception as _e:
        logger.warning("agent_cmd handlers not loaded: %s", _e)

    # 토큰 관리 커맨드
    try:
        from bot.handlers.token_cmd import cmd_settoken, cmd_tokeninfo, cmd_refreshtoken
        app.add_handler(CommandHandler("settoken", cmd_settoken))
        app.add_handler(CommandHandler("tokeninfo", cmd_tokeninfo))
        app.add_handler(CommandHandler("refreshtoken", cmd_refreshtoken))
    except Exception as _e:
        logger.warning("token_cmd handlers not loaded: %s", _e)

    # 1win 커맨드
    try:
        from bot.handlers.win1_cmd import (
            cmd_win1info, cmd_win1links, cmd_win1sources,
            cmd_win1promo, cmd_win1stats, cmd_win1report,
        )
        app.add_handler(CommandHandler("win1info", cmd_win1info))
        app.add_handler(CommandHandler("win1links", cmd_win1links))
        app.add_handler(CommandHandler("win1sources", cmd_win1sources))
        app.add_handler(CommandHandler("win1promo", cmd_win1promo))
        app.add_handler(CommandHandler("win1stats", cmd_win1stats))
        app.add_handler(CommandHandler("win1report", cmd_win1report))
    except Exception as _e:
        logger.warning("win1_cmd handlers not loaded: %s", _e)

    # 콜백 + 메시지 핸들러
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input_handler))
    app.add_handler(MessageHandler(
        filters.PHOTO | filters.VIDEO | filters.Document.ALL,
        admin_media_handler,
    ))

    # 채널 포워딩
    if CHANNEL_ID:
        app.add_handler(MessageHandler(
            filters.UpdateType.CHANNEL_POSTS & filters.Chat(CHANNEL_ID),
            channel_post_handler,
        ))
        logger.info("채널 포워딩 핸들러 등록: CHANNEL_ID=%s", CHANNEL_ID)
    else:
        logger.info("CHANNEL_ID 미설정 — 채널 포워딩 비활성화")

    return app


async def run_bot() -> None:
    """Subscribe Bot 시작."""
    application = build_application()
    logger.info("--- Subscribe Bot Polling 시작 ---")
    async with application:
        await application.initialize()
        await _set_commands(application)
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        await asyncio.Event().wait()


def main() -> None:
    if not SUBSCRIBE_BOT_TOKEN:
        logger.error("SUBSCRIBE_BOT_TOKEN이 설정되지 않았습니다.")
        return
    asyncio.run(run_bot())


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
    main()
