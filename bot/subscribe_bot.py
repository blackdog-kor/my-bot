"""
Subscribe Bot: /start 환영 메시지 + 구독자 DB 저장 + /admin 관리 메뉴.

환경변수:
  SUBSCRIBE_BOT_TOKEN  — 이 봇의 토큰 (필수)
  AFFILIATE_URL        — 환영 메시지 인라인 버튼 URL (campaign_config 폴백)
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

# loaded_message 헬퍼 (PG 우선, SQLite 폴백)
from bot.handlers.callbacks import (
    get_loaded_message_full,
    set_loaded_message,
)

logger = logging.getLogger("subscribe_bot")

SUBSCRIBE_BOT_TOKEN = (os.getenv("SUBSCRIBE_BOT_TOKEN") or "").strip()
AFFILIATE_URL       = (os.getenv("AFFILIATE_URL") or "https://t.me").strip()  # campaign_config 폴백 전용
ADMIN_ID_RAW        = (os.getenv("ADMIN_ID") or "").strip()
ADMIN_ID            = int(ADMIN_ID_RAW) if ADMIN_ID_RAW.isdigit() else None
CHANNEL_ID_RAW      = (os.getenv("CHANNEL_ID") or "").strip()
CHANNEL_ID          = int(CHANNEL_ID_RAW) if CHANNEL_ID_RAW.lstrip("-").isdigit() else 0

# ── 콜백 데이터 (sub_ 접두사로 admin bot 콜백과 구분) ──────────────────────
CB_HOME           = "sub_home"
CB_LOAD           = "sub_load"
CB_SEND           = "sub_send"
CB_STATUS         = "sub_status"
CB_CONFIRM        = "sub_confirm_send"
CB_CANCEL         = "sub_confirm_cancel"
# 설정 관리
CB_CONFIG         = "sub_config"
CB_CONFIG_URL     = "sub_cfg_url"
CB_CONFIG_PROMO   = "sub_cfg_promo"
CB_CONFIG_CAPTION = "sub_cfg_cap"
CB_CONFIG_VIEW    = "sub_cfg_view"

# context.user_data 키: 텍스트 입력 대기 중인 필드명
_AWAITING_KEY = "sub_awaiting"

# 입력 대기 필드 → 표시 이름 매핑
_FIELD_LABELS: dict[str, str] = {
    "affiliate_url":    "어필리에이트 링크",
    "promo_code":       "프로모코드",
    "caption_template": "캡션 템플릿",
}


def _is_admin(user_id: int | None) -> bool:
    return ADMIN_ID is not None and user_id is not None and user_id == ADMIN_ID


# ── 키보드 헬퍼 ──────────────────────────────────────────────────────────────

def _admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 미디어 장전",     callback_data=CB_LOAD)],
        [InlineKeyboardButton("📤 즉시 전체 발송",  callback_data=CB_SEND)],
        [InlineKeyboardButton("📊 구독자 현황",     callback_data=CB_STATUS)],
        [InlineKeyboardButton("⚙️ 캠페인 설정",    callback_data=CB_CONFIG)],
    ])


def _config_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 링크 변경",        callback_data=CB_CONFIG_URL)],
        [InlineKeyboardButton("🎟 프로모코드 변경",   callback_data=CB_CONFIG_PROMO)],
        [InlineKeyboardButton("📝 캡션 수정",         callback_data=CB_CONFIG_CAPTION)],
        [InlineKeyboardButton("👁 현재 설정 확인",    callback_data=CB_CONFIG_VIEW)],
        [InlineKeyboardButton("🏠 메인 메뉴",         callback_data=CB_HOME)],
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

    # campaign_config 로드 (DB 우선, 실패 시 환경변수 폴백)
    try:
        from app.pg_broadcast import get_campaign_config
        cfg = get_campaign_config()
    except Exception as _e:
        logger.warning("subscribe_bot: get_campaign_config 실패: %s", _e)
        cfg = {}

    button_url  = (cfg.get("affiliate_url") or "").strip() or AFFILIATE_URL
    promo_code  = (cfg.get("promo_code") or "").strip()
    caption_tmpl = (cfg.get("caption_template") or "").strip()

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🎰 Join VIP Now", url=button_url)
    ]])

    # loaded_message에서 미디어 읽기
    loaded = get_loaded_message_full()
    if loaded:
        _, _, file_id, file_type, loaded_caption = loaded
        if file_id:
            # 캡션 조합: DB 템플릿 우선, 없으면 장전 캡션
            base_caption = caption_tmpl or loaded_caption
            if promo_code and "{promo_code}" in base_caption:
                base_caption = base_caption.replace("{promo_code}", promo_code)

            try:
                if file_type == "photo":
                    await update.message.reply_photo(
                        file_id, caption=base_caption or None,
                        reply_markup=keyboard, parse_mode="HTML",
                    )
                elif file_type == "video":
                    try:
                        await update.message.reply_video(
                            file_id, caption=base_caption or None,
                            reply_markup=keyboard, parse_mode="HTML",
                        )
                    except Exception:
                        await update.message.reply_document(
                            file_id, caption=base_caption or None,
                            reply_markup=keyboard, parse_mode="HTML",
                        )
                else:
                    await update.message.reply_document(
                        file_id, caption=base_caption or None,
                        reply_markup=keyboard, parse_mode="HTML",
                    )
                return
            except Exception as e:
                logger.warning("subscribe_bot: 미디어 전송 실패, 텍스트 폴백: %s", e)

    # 미디어 없거나 전송 실패 시 텍스트 폴백
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


# ── 텍스트 입력 핸들러 (설정 값 수신) ────────────────────────────────────────

async def text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """관리자가 설정 값을 텍스트로 입력하면 DB에 저장한다."""
    if not update.message or not update.effective_user:
        return
    if not _is_admin(update.effective_user.id):
        return

    awaiting: str | None = context.user_data.get(_AWAITING_KEY)
    if not awaiting:
        return  # 대기 상태 아님 — 무시

    value = (update.message.text or "").strip()
    context.user_data.pop(_AWAITING_KEY, None)

    if not value:
        await update.message.reply_text(
            "⚠️ 빈 값은 저장할 수 없습니다. 다시 시도하려면 버튼을 눌러주세요.",
            reply_markup=_config_keyboard(),
        )
        return

    try:
        from app.pg_broadcast import update_campaign_config
        ok = update_campaign_config(awaiting, value)
    except Exception as e:
        await update.message.reply_text(
            f"❌ DB 저장 실패: {e}",
            reply_markup=_config_keyboard(),
        )
        return

    label = _FIELD_LABELS.get(awaiting, awaiting)
    preview = value[:100] + "..." if len(value) > 100 else value
    if ok:
        await update.message.reply_text(
            f"✅ <b>{label}</b> 업데이트 완료!\n\n<code>{preview}</code>",
            reply_markup=_config_keyboard(),
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            f"❌ {label} 업데이트 실패.",
            reply_markup=_config_keyboard(),
        )


# ── 콜백 핸들러 ──────────────────────────────────────────────────────────────

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data
    admin = _is_admin(query.from_user.id if query.from_user else None)

    # ── 메인 메뉴 ──────────────────────────────────────────────────────────
    if data == CB_HOME:
        if not admin:
            return
        context.user_data.pop(_AWAITING_KEY, None)
        await query.message.reply_text(
            "🛠 <b>구독봇 관리자 메뉴</b>",
            reply_markup=_admin_keyboard(),
            parse_mode="HTML",
        )
        return

    # ── 미디어 장전 확인 ───────────────────────────────────────────────────
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

    # ── 발송 확인 ─────────────────────────────────────────────────────────
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

    # ── 구독자 현황 ────────────────────────────────────────────────────────
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

    # ── 발송 실행 ──────────────────────────────────────────────────────────
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

    # ── 캠페인 설정 메뉴 ──────────────────────────────────────────────────
    if data == CB_CONFIG:
        if not admin:
            return
        await query.message.reply_text(
            "⚙️ <b>캠페인 설정</b>\n\n변경할 항목을 선택하세요.",
            reply_markup=_config_keyboard(),
            parse_mode="HTML",
        )
        return

    if data == CB_CONFIG_URL:
        if not admin:
            return
        context.user_data[_AWAITING_KEY] = "affiliate_url"
        await query.message.reply_text(
            "🔗 새 <b>어필리에이트 링크</b>를 입력해주세요.\n\n"
            "예: <code>https://example.com/?ref=abc</code>",
            parse_mode="HTML",
        )
        return

    if data == CB_CONFIG_PROMO:
        if not admin:
            return
        context.user_data[_AWAITING_KEY] = "promo_code"
        await query.message.reply_text(
            "🎟 새 <b>프로모코드</b>를 입력해주세요.\n\n"
            "캡션 템플릿에서 <code>{promo_code}</code>로 자동 치환됩니다.",
            parse_mode="HTML",
        )
        return

    if data == CB_CONFIG_CAPTION:
        if not admin:
            return
        context.user_data[_AWAITING_KEY] = "caption_template"
        await query.message.reply_text(
            "📝 새 <b>캡션 템플릿</b>을 입력해주세요.\n\n"
            "• <code>{promo_code}</code> 자리표시자 사용 가능\n"
            "• 비워두면 장전된 미디어의 캡션이 사용됩니다.",
            parse_mode="HTML",
        )
        return

    if data == CB_CONFIG_VIEW:
        if not admin:
            return
        try:
            from app.pg_broadcast import get_campaign_config
            cfg = get_campaign_config()
            url  = cfg.get("affiliate_url")  or "(미설정 — 환경변수 폴백)"
            promo = cfg.get("promo_code")    or "(미설정)"
            tmpl  = cfg.get("caption_template") or "(미설정 — 장전 캡션 사용)"
            updated = cfg.get("updated_at")
            updated_str = str(updated)[:19] if updated else "없음"
        except Exception as e:
            url = promo = tmpl = f"오류: {e}"
            updated_str = "-"

        url_preview  = url[:60]   + "..." if len(str(url))  > 60  else url
        tmpl_preview = tmpl[:100] + "..." if len(str(tmpl)) > 100 else tmpl

        await query.message.reply_text(
            f"👁 <b>현재 캠페인 설정</b>\n\n"
            f"🔗 링크: <code>{url_preview}</code>\n"
            f"🎟 프로모코드: <code>{promo}</code>\n"
            f"📝 캡션: <code>{tmpl_preview}</code>\n\n"
            f"🕐 마지막 수정: {updated_str}",
            reply_markup=_config_keyboard(),
            parse_mode="HTML",
        )
        return


# ── 즉시 발송 (관리자 버튼) ───────────────────────────────────────────────────

async def _do_push(bot, admin_chat_id: int) -> None:
    """구독자 전체에게 loaded_message를 Bot API로 발송."""
    loaded = get_loaded_message_full()
    if not loaded:
        await bot.send_message(admin_chat_id, "❌ 장전된 메시지가 없습니다.")
        return
    _, _, file_id, file_type, loaded_caption = loaded
    if not file_id:
        await bot.send_message(admin_chat_id, "❌ 파일 ID 없음. 재장전 필요.")
        return

    # 구독자 목록 조회 (실패 시 발송 자체가 불가 → 중단)
    try:
        from app.pg_broadcast import get_subscribe_users
        users = get_subscribe_users()
    except Exception as e:
        await bot.send_message(admin_chat_id, f"❌ 구독자 조회 실패: {e}")
        return

    if not users:
        await bot.send_message(admin_chat_id, "구독자가 없습니다.")
        return

    # campaign_config 조회 (실패 시 환경변수 폴백 — 발송은 계속)
    try:
        from app.pg_broadcast import get_campaign_config
        cfg = get_campaign_config()
    except Exception:
        cfg = {}

    # affiliate_url: DB 우선, 환경변수 폴백
    effective_affiliate_url = (cfg.get("affiliate_url") or "").strip() or AFFILIATE_URL
    _db_caption_tmpl        = (cfg.get("caption_template") or "").strip()
    _db_promo_code          = (cfg.get("promo_code") or "").strip()

    base_caption = _db_caption_tmpl or loaded_caption
    if _db_promo_code and "{promo_code}" in base_caption:
        base_caption = base_caption.replace("{promo_code}", _db_promo_code)

    from app.userbot_sender import personalize_caption

    sent = skipped = failed = 0
    for uid, username in users:
        try:
            user_caption = await personalize_caption(base_caption, username)
            await _send_media(bot, uid, file_id, file_type, user_caption)
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


async def _forward_channel_post(bot, from_chat_id: int, message_id: int) -> None:
    """채널 게시물을 구독자 전체에 copy_message로 전송 (인라인 버튼 포함)."""
    try:
        from app.pg_broadcast import get_subscribe_users, get_campaign_config
        users = get_subscribe_users()
        cfg = get_campaign_config()
    except Exception as e:
        logger.warning("channel forward: 구독자/설정 조회 실패: %s", e)
        return

    if not users:
        return

    button_url = (cfg.get("affiliate_url") or "").strip() or AFFILIATE_URL
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🎰 Join VIP Now", url=button_url)
    ]])

    sent = skipped = failed = 0
    for uid, _ in users:
        try:
            await bot.copy_message(
                chat_id=uid,
                from_chat_id=from_chat_id,
                message_id=message_id,
                reply_markup=keyboard,
            )
            sent += 1
        except Exception as e:
            err = str(e).lower()
            if any(k in err for k in ("blocked", "deactivated", "not found", "forbidden", "user is deactivated")):
                skipped += 1
            else:
                failed += 1
                logger.warning("channel forward failed to %d: %s", uid, e)
        await asyncio.sleep(0.05)  # ~20 msg/sec

    summary = (
        f"📢 채널 포워딩 완료\n"
        f"• 성공: {sent}명\n"
        f"• 차단/탈퇴: {skipped}명\n"
        f"• 실패: {failed}명"
    )
    logger.info(summary)
    if ADMIN_ID:
        try:
            await bot.send_message(ADMIN_ID, summary)
        except Exception:
            pass


async def channel_post_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """채널 게시물 수신 → 구독자 전체 포워딩 (백그라운드 실행)."""
    msg = update.channel_post
    if not msg:
        return
    logger.info("채널 게시물 수신 (chat_id=%s, message_id=%s) → 포워딩 시작", msg.chat_id, msg.message_id)
    asyncio.create_task(
        _forward_channel_post(context.bot, msg.chat_id, msg.message_id)
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
            filters.TEXT & ~filters.COMMAND,
            text_input_handler,
        )
    )
    app.add_handler(
        MessageHandler(
            filters.PHOTO | filters.VIDEO | filters.Document.ALL,
            admin_load_handler,
        )
    )
    # 채널 게시물 자동 포워딩 (CHANNEL_ID 설정된 경우에만)
    if CHANNEL_ID:
        app.add_handler(
            MessageHandler(
                filters.UpdateType.CHANNEL_POSTS & filters.Chat(CHANNEL_ID),
                channel_post_handler,
            )
        )
        logger.info("채널 포워딩 핸들러 등록: CHANNEL_ID=%s", CHANNEL_ID)
    else:
        logger.info("CHANNEL_ID 미설정 — 채널 포워딩 비활성화")
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
