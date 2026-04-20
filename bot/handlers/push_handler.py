"""
즉시 발송 + 채널 포워딩 핸들러.
"""
from __future__ import annotations

import asyncio
import json

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.handlers import (
    ADMIN_ID,
    AFFILIATE_URL,
    CB_CONFIRM,
    home_keyboard,
    logger,
)


async def handle_push_confirm(
    data: str, query, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """발송 확인 콜백. 처리했으면 True 반환."""
    if data == CB_CONFIRM:
        await query.message.reply_text(
            "📤 발송 시작됨. 완료 시 알림 드립니다.", reply_markup=home_keyboard()
        )
        asyncio.create_task(_do_push(context.bot, query.from_user.id))
        return True
    return False


async def channel_post_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """채널 게시물 수신 → 구독자 전체 포워딩 (백그라운드 실행)."""
    msg = update.channel_post
    if not msg:
        return
    logger.info(
        "채널 게시물 수신 (chat_id=%s, message_id=%s) → 포워딩 시작",
        msg.chat_id, msg.message_id,
    )
    asyncio.create_task(
        _forward_channel_post(context.bot, msg.chat_id, msg.message_id)
    )


# ── 내부 함수 ─────────────────────────────────────────────────────────────────


async def _send_media(
    bot,
    chat_id: int,
    file_id: str,
    file_type: str,
    caption: str,
    reply_markup=None,
    entities=None,
) -> None:
    """미디어 타입별 발송 유틸."""
    cap = caption or None
    opts: dict = {"caption": cap, "reply_markup": reply_markup}
    if entities:
        opts["caption_entities"] = entities
    if file_type == "photo":
        await bot.send_photo(chat_id, file_id, **opts)
    elif file_type == "video":
        try:
            await bot.send_video(chat_id, file_id, **opts)
        except Exception:
            await bot.send_document(chat_id, file_id, **opts)
    else:
        await bot.send_document(chat_id, file_id, **opts)


async def _do_push(bot, admin_chat_id: int) -> None:
    """구독자 전체에게 campaign_posts의 다음 게시물을 Bot API로 발송."""
    try:
        from app.pg_broadcast import get_next_post
        post = get_next_post()
    except Exception as e:
        await bot.send_message(admin_chat_id, f"❌ 게시물 조회 실패: {e}")
        return

    if not post or not post.get("file_id"):
        await bot.send_message(
            admin_chat_id,
            "❌ 발송할 게시물이 없습니다. ➕ 게시물 추가 후 다시 시도하세요.",
        )
        return

    file_id = post["file_id"]
    file_type = post["file_type"]
    post_cap = post["caption"] or ""
    post_id = post["id"]
    entities_json = post.get("caption_entities")

    try:
        from app.pg_broadcast import get_subscribe_users
        users = get_subscribe_users()
    except Exception as e:
        await bot.send_message(admin_chat_id, f"❌ 구독자 조회 실패: {e}")
        return

    if not users:
        await bot.send_message(admin_chat_id, "구독자가 없습니다.")
        return

    try:
        from app.pg_broadcast import get_campaign_config
        cfg = get_campaign_config()
    except Exception:
        cfg = {}

    effective_affiliate_url = (cfg.get("affiliate_url") or "").strip() or AFFILIATE_URL
    _db_caption_tmpl = (cfg.get("caption_template") or "").strip()
    btn_text = (cfg.get("button_text") or "🎰 VIP 카지노 입장").strip()

    base_caption = _db_caption_tmpl or post_cap

    dm_keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(btn_text, url=effective_affiliate_url)
    ]]) if effective_affiliate_url else None

    # caption_template이 있으면 entities 무효 (텍스트가 달라지므로)
    post_entities: list | None = None
    if not _db_caption_tmpl and entities_json:
        try:
            from telegram import MessageEntity
            post_entities = [
                MessageEntity.de_json(e, bot) for e in json.loads(entities_json)
            ]
        except Exception:
            post_entities = None

    from app.userbot_sender import personalize_caption

    total = len(users)
    sent = skipped = failed = 0
    progress_step = max(total // 10, 1)

    for idx, (uid, username) in enumerate(users):
        try:
            user_caption = await personalize_caption(base_caption, username)
            use_entities = post_entities if user_caption == base_caption else None
            await _send_media(
                bot, uid, file_id, file_type, user_caption,
                reply_markup=dm_keyboard, entities=use_entities,
            )
            sent += 1
        except Exception as e:
            err = str(e).lower()
            if any(k in err for k in (
                "blocked", "deactivated", "not found", "forbidden", "user is deactivated"
            )):
                skipped += 1
            else:
                failed += 1
                logger.warning("push failed to %d: %s", uid, e)
        # 진행률 알림 (10% 단위)
        if (idx + 1) % progress_step == 0 and (idx + 1) < total:
            pct = int((idx + 1) / total * 100)
            try:
                await bot.send_message(
                    admin_chat_id, f"📤 발송 진행 중... {pct}% ({idx + 1}/{total})"
                )
            except Exception:
                pass
        await asyncio.sleep(0.05)

    await bot.send_message(
        admin_chat_id,
        f"✅ 즉시 발송 완료! (게시물 #{post_id})\n"
        f"• 성공: {sent}명\n"
        f"• 차단/탈퇴: {skipped}명\n"
        f"• 실패: {failed}명",
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
            if any(k in err for k in (
                "blocked", "deactivated", "not found", "forbidden", "user is deactivated"
            )):
                skipped += 1
            else:
                failed += 1
                logger.warning("channel forward failed to %d: %s", uid, e)
        await asyncio.sleep(0.05)

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
