"""
/start 커맨드 핸들러 — 환영 메시지 + 구독자 DB 저장.
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.handlers import AFFILIATE_URL, logger


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """신규 유저 환영 + campaign_posts 미디어 발송 + 구독자 DB 저장."""
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

    # campaign_config 로드
    try:
        from app.pg_broadcast import get_campaign_config
        cfg = get_campaign_config()
    except Exception as _e:
        logger.warning("subscribe_bot: get_campaign_config 실패: %s", _e)
        cfg = {}

    button_url = (cfg.get("affiliate_url") or "").strip() or AFFILIATE_URL
    caption_tmpl = (cfg.get("caption_template") or "").strip()
    btn_text = (cfg.get("button_text") or "🎰 VIP 카지노 입장").strip()

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(btn_text, url=button_url)
    ]])

    # campaign_posts에서 현재 게시물 읽기 (last_sent_at 갱신 없음)
    try:
        from app.pg_broadcast import get_current_post
        post = get_current_post()
    except Exception as e:
        logger.warning("subscribe_bot: get_current_post 실패: %s", e)
        post = None

    if post and post.get("file_id"):
        file_id = post["file_id"]
        file_type = post["file_type"]
        post_cap = post["caption"] or ""
        base_caption = caption_tmpl or post_cap
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
