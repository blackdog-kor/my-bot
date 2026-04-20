"""
그룹 토픽 관리 핸들러 — 토픽 목록, 자동 생성, 즉시 게시.
"""
from __future__ import annotations

import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.handlers import (
    CB_HOME,
    CB_TOPICS_CREATE,
    CB_TOPICS_LIST,
    CB_TOPICS_POST,
    home_keyboard,
    is_admin,
    logger,
)


async def handle_topics_callbacks(
    data: str, query, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """토픽 관련 콜백 처리. 처리했으면 True 반환."""
    if data == CB_TOPICS_LIST:
        try:
            from app.group_topic_manager import list_topics
            topics = list_topics()
        except Exception as e:
            await query.message.reply_text(
                f"❌ 토픽 조회 실패: {e}", reply_markup=home_keyboard()
            )
            return True
        if not topics:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🆕 토픽 자동 생성", callback_data=CB_TOPICS_CREATE)],
                [InlineKeyboardButton("🏠 메인 메뉴", callback_data=CB_HOME)],
            ])
            await query.message.reply_text(
                "📌 등록된 토픽이 없습니다.\n\nGROUP_ID 설정 후 '토픽 자동 생성'을 눌러주세요.",
                reply_markup=keyboard,
            )
            return True
        lines = ["📌 <b>그룹 토픽 목록</b>\n"]
        for t in topics:
            status = "✅" if t["is_active"] else "⏸"
            auto = "🔄" if t.get("auto_post") else "⏹"
            lines.append(
                f"{status}{auto} <b>{t['name']}</b>\n"
                f"   └ type: {t['content_type']} | thread_id: {t['thread_id']}"
            )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🆕 토픽 추가 생성", callback_data=CB_TOPICS_CREATE)],
            [InlineKeyboardButton("📤 토픽에 즉시 게시", callback_data=CB_TOPICS_POST)],
            [InlineKeyboardButton("🏠 메인 메뉴", callback_data=CB_HOME)],
        ])
        await query.message.reply_text(
            "\n".join(lines), reply_markup=keyboard, parse_mode="HTML",
        )
        return True

    if data == CB_TOPICS_CREATE:
        await query.message.reply_text("🔄 토픽 생성 중... 잠시 기다려주세요.")
        task = asyncio.create_task(
            _do_create_topics(context.bot, query.from_user.id)
        )
        task.add_done_callback(
            lambda t: logger.exception("topic create error", exc_info=t.exception())
            if t.exception() else None
        )
        return True

    if data == CB_TOPICS_POST:
        await query.message.reply_text("📤 토픽에 게시 중...", reply_markup=home_keyboard())
        task = asyncio.create_task(
            _do_post_to_topic(context.bot, query.from_user.id)
        )
        task.add_done_callback(
            lambda t: logger.exception("topic post error", exc_info=t.exception())
            if t.exception() else None
        )
        return True

    return False


# ── 비동기 작업 ──────────────────────────────────────────────────────────────


async def _do_create_topics(bot, admin_chat_id: int) -> None:
    """포럼 토픽 일괄 생성 (백그라운드 실행)."""
    try:
        from app.group_topic_manager import create_forum_topics, ensure_forum_topics_table
        ensure_forum_topics_table()
        created = await create_forum_topics()
    except Exception as e:
        await bot.send_message(admin_chat_id, f"❌ 토픽 생성 실패: {e}")
        return

    if created:
        lines = [f"✅ 토픽 {len(created)}개 생성 완료!\n"]
        for t in created:
            lines.append(f"  • {t['name']} (thread_id={t['thread_id']})")
        await bot.send_message(admin_chat_id, "\n".join(lines))
    else:
        await bot.send_message(admin_chat_id, "ℹ️ 추가 생성할 토픽이 없습니다 (모두 존재).")


async def _do_post_to_topic(bot, admin_chat_id: int) -> None:
    """다음 게시물을 분류하여 적절한 토픽에 즉시 게시."""
    try:
        from app.group_topic_manager import auto_post_campaign_to_topics
        posted = await auto_post_campaign_to_topics()
    except Exception as e:
        await bot.send_message(admin_chat_id, f"❌ 토픽 게시 실패: {e}")
        return

    if posted > 0:
        await bot.send_message(admin_chat_id, f"✅ 토픽에 {posted}건 게시 완료!")
    else:
        await bot.send_message(admin_chat_id, "ℹ️ 게시할 콘텐츠가 없습니다.")
