"""
Subscribe Bot: /start 환영 메시지 + 구독자 DB 저장 + /admin 관리 메뉴.

환경변수:
  SUBSCRIBE_BOT_TOKEN  — 이 봇의 토큰 (필수)
  AFFILIATE_URL        — 환영 메시지 인라인 버튼 URL
  ADMIN_ID             — 관리자 Telegram user_id
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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

# 기존 admin bot의 SQLite loaded_message 공유 (같은 프로세스 내)
from bot.handlers.callbacks import (
    get_loaded_message_full,
    set_loaded_message,
)

logger = logging.getLogger("subscribe_bot")

SUBSCRIBE_BOT_TOKEN = (os.getenv("SUBSCRIBE_BOT_TOKEN") or "").strip()
AFFILIATE_URL = (os.getenv("AFFILIATE_URL") or "https://t.me").strip()
ADMIN_ID_RAW = (os.getenv("ADMIN_ID") or "").strip()
ADMIN_ID = int(ADMIN_ID_RAW) if ADMIN_ID_RAW.isdigit() else None

# ── 콜백 데이터 (sub_ 접두사로 admin bot 콜백과 구분) ──────────────────────
CB_HOME       = "sub_home"
CB_LOAD       = "sub_load"
CB_SEND       = "sub_send"
CB_STATUS     = "sub_status"
CB_CONFIRM    = "sub_confirm_send"
CB_CANCEL     = "sub_confirm_cancel"


def _is_admin(user_id: int | None) -> bool:
    return ADMIN_ID is not None and user_id is not None and user_id == ADMIN_ID


def _admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 미디어 장전",     callback_data=CB_LOAD)],
        [InlineKeyboardButton("📤 즉시 전체 발송",  callback_data=CB_SEND)],
        [InlineKeyboardButton("📊 구독자 현황",     callback_data=CB_STATUS)],
    ])


def _home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🏠 메인 메뉴", callback_data=CB_HOME)]]
    )


# ── /start ──────────────────────────────────────────────────────────────────

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not update.message:
        return

    # 구독자 DB 저장
    try:
        from app.pg_broadcast import save_broadcast_batch
        username = (user.username or "").strip()
        save_broadcast_batch([(user.id, username, "subscribe_bot")])
        logger.info("subscribe_bot: saved user %d (@%s)", user.id, username)
    except Exception as e:
        logger.warning("subscribe_bot: save user failed: %s", e)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🎰 지금 바로 입장하기", url=AFFILIATE_URL)
    ]])
    await update.message.reply_text(
        "🎉 <b>환영합니다!</b>\n\n"
        "최신 이벤트와 특별 혜택 정보를 가장 먼저 받아보세요.\n\n"
        "아래 버튼을 눌러 지금 바로 시작하세요! 👇",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


# ── /admin ───────────────────────────────────────────────────────────────────

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("권한이 없습니다.")
        return
    await update.message.reply_text(
        "🛠 <b>구독봇 관리자 메뉴</b>",
        reply_markup=_admin_keyboard(),
        parse_mode="HTML",
    )


# ── 미디어 장전 핸들러 ────────────────────────────────────────────────────────

async def admin_load_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """관리자가 미디어를 보내면 loaded_message에 장전."""
    if not update.message or not update.effective_user:
        return
    if not _is_admin(update.effective_user.id):
        return

    msg = update.message
    caption = msg.caption or ""
    file_id = ""
    file_type = ""

    if msg.photo:
        file_id = msg.photo[-1].file_id
        file_type = "photo"
    elif msg.video:
        file_id = msg.video.file_id
        file_type = "video"
    elif msg.document and msg.document.mime_type and msg.document.mime_type.startswith("video/"):
        file_id = msg.document.file_id
        file_type = "document"
    else:
        return

    set_loaded_message(
        msg.chat_id, msg.message_id,
        file_id=file_id, file_type=file_type, caption=caption,
    )
    await msg.reply_text(
        f"✅ 장전 완료 ({file_type})\n"
        f"캡션: {caption[:80] + '...' if len(caption) > 80 else caption or '(없음)'}\n\n"
        "/admin → [📤 즉시 전체 발송]"
    )


# ── 콜백 핸들러 ──────────────────────────────────────────────────────────────

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data
    admin = _is_admin(query.from_user.id if query.from_user else None)

    if data == CB_HOME:
        if not admin:
            return
        await query.message.reply_text(
            "🛠 <b>구독봇 관리자 메뉴</b>",
            reply_markup=_admin_keyboard(),
            parse_mode="HTML",
        )
        return

    if data == CB_LOAD:
        if not admin:
            return
        loaded = get_loaded_message_full()
        if loaded:
            _, _, _, ftype, cap = loaded
            text = (
                f"✅ 현재 장전: {ftype}\n"
                f"캡션: {cap[:80] + '...' if len(cap) > 80 else cap or '(없음)'}\n\n"
                "새 미디어를 이 채팅에 보내면 교체됩니다."
            )
        else:
            text = "❌ 장전된 미디어 없음. 미디어(이미지/영상+캡션)를 보내주세요."
        await query.message.reply_text(text, reply_markup=_home_keyboard())
        return

    if data == CB_SEND:
        if not admin:
            return
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ 확인", callback_data=CB_CONFIRM),
             InlineKeyboardButton("❌ 취소", callback_data=CB_CANCEL)],
            [InlineKeyboardButton("🏠 메인 메뉴", callback_data=CB_HOME)],
        ])
        await query.message.reply_text("⚠️ 전체 구독자에게 즉시 발송할까요?", reply_markup=keyboard)
        return

    if data == CB_STATUS:
        if not admin:
            return
        try:
            from app.pg_broadcast import count_subscribe_users
            count = count_subscribe_users()
        except Exception as e:
            count = f"오류: {e}"
        loaded = get_loaded_message_full()
        loaded_info = (
            f"{loaded[3]} / {(loaded[4] or '')[:40]}" if loaded else "없음"
        )
        await query.message.reply_text(
            f"📊 <b>구독자 현황</b>\n\n"
            f"• 총 구독자: {count}명\n"
            f"• 장전 미디어: {loaded_info}",
            reply_markup=_home_keyboard(),
            parse_mode="HTML",
        )
        return

    if data == CB_CONFIRM:
        if not admin:
            return
        await query.message.reply_text("📤 발송 시작됨. 완료 시 알림 드립니다.", reply_markup=_home_keyboard())
        asyncio.create_task(_do_push(context.bot, query.from_user.id))
        return

    if data == CB_CANCEL:
        if not admin:
            return
        await query.message.reply_text("취소했습니다.", reply_markup=_home_keyboard())
        return


# ── 즉시 발송 (관리자 버튼) ───────────────────────────────────────────────────

async def _do_push(bot, admin_chat_id: int) -> None:
    """구독자 전체에게 loaded_message를 Bot API로 발송."""
    loaded = get_loaded_message_full()
    if not loaded:
        await bot.send_message(admin_chat_id, "❌ 장전된 메시지가 없습니다.")
        return
    _, _, file_id, file_type, caption = loaded
    if not file_id:
        await bot.send_message(admin_chat_id, "❌ 파일 ID 없음. 재장전 필요.")
        return

    try:
        from app.pg_broadcast import get_subscribe_user_ids
        user_ids = get_subscribe_user_ids()
    except Exception as e:
        await bot.send_message(admin_chat_id, f"❌ 구독자 조회 실패: {e}")
        return

    if not user_ids:
        await bot.send_message(admin_chat_id, "구독자가 없습니다.")
        return

    sent = skipped = failed = 0
    for uid in user_ids:
        try:
            await _send_media(bot, uid, file_id, file_type, caption)
            sent += 1
        except Exception as e:
            err = str(e).lower()
            if any(k in err for k in ("blocked", "deactivated", "not found", "forbidden", "user is deactivated")):
                skipped += 1
            else:
                failed += 1
                logger.warning("push failed to %d: %s", uid, e)
        await asyncio.sleep(0.05)  # ~20 msg/sec

    await bot.send_message(
        admin_chat_id,
        f"✅ 즉시 발송 완료!\n• 성공: {sent}명\n• 차단/탈퇴: {skipped}명\n• 실패: {failed}명",
    )


async def _send_media(bot, chat_id: int, file_id: str, file_type: str, caption: str) -> None:
    cap = caption or None
    if file_type == "photo":
        await bot.send_photo(chat_id, file_id, caption=cap)
    elif file_type == "video":
        try:
            await bot.send_video(chat_id, file_id, caption=cap)
        except Exception:
            await bot.send_document(chat_id, file_id, caption=cap)
    else:
        await bot.send_document(chat_id, file_id, caption=cap)


# ── 봇 빌드 / 실행 ────────────────────────────────────────────────────────────

def build_application() -> Application:
    if not SUBSCRIBE_BOT_TOKEN:
        raise RuntimeError("SUBSCRIBE_BOT_TOKEN이 설정되지 않았습니다.")
    app = Application.builder().token(SUBSCRIBE_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(
        MessageHandler(
            filters.PHOTO | filters.VIDEO | filters.Document.ALL,
            admin_load_handler,
        )
    )
    return app


async def run_bot() -> None:
    application = build_application()
    logger.info("--- Subscribe Bot Polling 시작 ---")
    async with application:
        await application.initialize()
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
