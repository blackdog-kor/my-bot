"""
/admin 커맨드 + 게시물 CRUD + 구독자 현황 콜백 핸들러.
"""
from __future__ import annotations

import json

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.handlers import (
    AWAITING_KEY,
    CB_CANCEL,
    CB_CONFIRM,
    CB_HOME,
    CB_POST_ADD,
    CB_POST_DELETE,
    CB_POSTS_LIST,
    CB_SEND,
    CB_STATUS,
    admin_keyboard,
    home_keyboard,
    is_admin,
    logger,
    posts_delete_keyboard,
)


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """관리자 메뉴 표시."""
    if not update.message or not update.effective_user:
        return
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("권한이 없습니다.")
        return
    await update.message.reply_text(
        "🛠 <b>구독봇 관리자 메뉴</b>",
        reply_markup=admin_keyboard(),
        parse_mode="HTML",
    )


async def admin_media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """관리자가 미디어를 보내면 campaign_posts에 추가 (게시물 추가 대기 중일 때만)."""
    if not update.message or not update.effective_user:
        return
    if not is_admin(update.effective_user.id):
        return

    awaiting: str | None = context.user_data.get(AWAITING_KEY)
    if awaiting != "post_add":
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
        await msg.reply_text("⚠️ 지원하지 않는 미디어 형식입니다. 이미지 또는 영상을 보내주세요.")
        return

    context.user_data.pop(AWAITING_KEY, None)

    entities_json: str | None = None
    if msg.caption_entities:
        try:
            entities_json = json.dumps([e.to_dict() for e in msg.caption_entities])
        except Exception:
            entities_json = None

    try:
        from app.pg_broadcast import add_post, list_posts
        posts = list_posts()
        max_order = max((p["send_order"] for p in posts), default=-1)
        post_id = add_post(
            file_id, file_type, caption,
            send_order=max_order + 1,
            caption_entities=entities_json,
        )
    except Exception as e:
        await msg.reply_text(f"❌ 게시물 저장 실패: {e}", reply_markup=home_keyboard())
        return

    if post_id:
        cap_preview = caption[:80] + "..." if len(caption) > 80 else caption or "(없음)"
        await msg.reply_text(
            f"✅ 게시물 추가 완료!\n"
            f"ID: #{post_id} | 타입: {file_type}\n"
            f"캡션: {cap_preview}",
            reply_markup=home_keyboard(),
        )
    else:
        await msg.reply_text("❌ 게시물 저장 실패. 다시 시도해주세요.", reply_markup=home_keyboard())


async def handle_admin_callbacks(
    data: str, query, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """관리자 메뉴/게시물/발송 관련 콜백 처리. 처리했으면 True 반환."""
    # ── 메인 메뉴
    if data == CB_HOME:
        context.user_data.pop(AWAITING_KEY, None)
        await query.message.reply_text(
            "🛠 <b>구독봇 관리자 메뉴</b>",
            reply_markup=admin_keyboard(),
            parse_mode="HTML",
        )
        return True

    # ── 게시물 목록
    if data == CB_POSTS_LIST:
        try:
            from app.pg_broadcast import list_posts
            posts = list_posts()
        except Exception as e:
            await query.message.reply_text(f"❌ 조회 실패: {e}", reply_markup=home_keyboard())
            return True
        if not posts:
            await query.message.reply_text("📭 등록된 게시물이 없습니다.", reply_markup=home_keyboard())
            return True
        lines = ["📋 <b>게시물 목록</b>\n"]
        for p in posts:
            status = "✅" if p["is_active"] else "⏸"
            cap = (p["caption"] or "")[:40] or "(캡션없음)"
            lines.append(
                f"{status} <b>#{p['id']}</b> [{p['file_type']}] 순서:{p['send_order']}\n"
                f"   └ {cap}"
            )
        await query.message.reply_text(
            "\n".join(lines), reply_markup=home_keyboard(), parse_mode="HTML",
        )
        return True

    # ── 게시물 추가
    if data == CB_POST_ADD:
        context.user_data[AWAITING_KEY] = "post_add"
        await query.message.reply_text(
            "➕ <b>게시물 추가</b>\n\n"
            "이미지 또는 영상을 전송하면 자동으로 저장됩니다.\n"
            "캡션도 함께 입력할 수 있습니다.",
            parse_mode="HTML",
        )
        return True

    # ── 게시물 삭제 목록
    if data == CB_POST_DELETE:
        try:
            from app.pg_broadcast import list_posts
            posts = list_posts()
        except Exception as e:
            await query.message.reply_text(f"❌ 조회 실패: {e}", reply_markup=home_keyboard())
            return True
        if not posts:
            await query.message.reply_text("📭 삭제할 게시물이 없습니다.", reply_markup=home_keyboard())
            return True
        await query.message.reply_text(
            "🗑 <b>삭제할 게시물을 선택하세요</b>",
            reply_markup=posts_delete_keyboard(posts),
            parse_mode="HTML",
        )
        return True

    # ── 게시물 삭제 실행 (sub_del_ID)
    if data.startswith("sub_del_"):
        try:
            post_id = int(data.split("_")[-1])
        except ValueError:
            return True
        try:
            from app.pg_broadcast import delete_post
            ok = delete_post(post_id)
        except Exception as e:
            await query.message.reply_text(f"❌ 삭제 실패: {e}", reply_markup=home_keyboard())
            return True
        if ok:
            await query.message.reply_text(
                f"✅ 게시물 #{post_id} 삭제 완료.", reply_markup=home_keyboard()
            )
        else:
            await query.message.reply_text(
                f"❌ #{post_id} 삭제 실패 (이미 삭제됨?).", reply_markup=home_keyboard()
            )
        return True

    # ── 발송 확인
    if data == CB_SEND:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ 확인", callback_data=CB_CONFIRM),
             InlineKeyboardButton("❌ 취소", callback_data=CB_CANCEL)],
            [InlineKeyboardButton("🏠 메인 메뉴", callback_data=CB_HOME)],
        ])
        await query.message.reply_text("⚠️ 전체 구독자에게 즉시 발송할까요?", reply_markup=keyboard)
        return True

    # ── 구독자 현황
    if data == CB_STATUS:
        try:
            from app.pg_broadcast import count_subscribe_users, list_posts
            count = count_subscribe_users()
            posts = list_posts()
        except Exception as e:
            count = f"오류: {e}"
            posts = []
        active_count = sum(1 for p in posts if p.get("is_active"))
        await query.message.reply_text(
            f"📊 <b>구독자 현황</b>\n\n"
            f"• 총 구독자: {count}명\n"
            f"• 활성 게시물: {active_count}개 / 전체 {len(posts)}개",
            reply_markup=home_keyboard(),
            parse_mode="HTML",
        )
        return True

    # ── 발송 취소
    if data == CB_CANCEL:
        await query.message.reply_text("취소했습니다.", reply_markup=home_keyboard())
        return True

    return False
