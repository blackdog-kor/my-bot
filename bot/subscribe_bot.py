"""
Subscribe Bot: /start 환영 메시지 + 구독자 DB 저장 + /admin 관리 메뉴.

환경변수:
  SUBSCRIBE_BOT_TOKEN  — 이 봇의 토큰 (필수)
  AFFILIATE_URL        — 환영 메시지 인라인 버튼 URL (campaign_config 폴백)
  ADMIN_ID             — 관리자 Telegram user_id
"""
from __future__ import annotations

import asyncio
import json
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

logger = logging.getLogger("subscribe_bot")

SUBSCRIBE_BOT_TOKEN = (os.getenv("SUBSCRIBE_BOT_TOKEN") or "").strip()
AFFILIATE_URL       = (os.getenv("AFFILIATE_URL") or "https://t.me").strip()
ADMIN_ID_RAW        = (os.getenv("ADMIN_ID") or "").strip()
ADMIN_ID            = int(ADMIN_ID_RAW) if ADMIN_ID_RAW.isdigit() else None
CHANNEL_ID_RAW      = (os.getenv("CHANNEL_ID") or "").strip()
CHANNEL_ID          = int(CHANNEL_ID_RAW) if CHANNEL_ID_RAW.lstrip("-").isdigit() else 0

# ── 콜백 데이터 (sub_ 접두사로 admin bot 콜백과 구분) ──────────────────────
CB_HOME         = "sub_home"
CB_SEND         = "sub_send"
CB_STATUS       = "sub_status"
CB_CONFIRM      = "sub_confirm_send"
CB_CANCEL       = "sub_confirm_cancel"
CB_POSTS_LIST   = "sub_posts_list"
CB_POST_ADD     = "sub_post_add"
CB_POST_DELETE  = "sub_post_delete"
# 설정 관리
CB_CONFIG          = "sub_config"
CB_CONFIG_URL      = "sub_cfg_url"
CB_CONFIG_CAPTION  = "sub_cfg_cap"
CB_CONFIG_VIEW     = "sub_cfg_view"
CB_CONFIG_BOT_LINK = "sub_cfg_bot_link"
CB_CONFIG_BTN_TEXT = "sub_cfg_btn_text"

# context.user_data 키: 텍스트 입력 대기 중인 필드명
_AWAITING_KEY = "sub_awaiting"

# 입력 대기 필드 → 표시 이름 매핑
_FIELD_LABELS: dict[str, str] = {
    "affiliate_url":      "어필리에이트 링크",
    "caption_template":   "캡션 템플릿",
    "subscribe_bot_link": "봇 링크",
    "button_text":        "DM 버튼 텍스트",
}


def _is_admin(user_id: int | None) -> bool:
    return ADMIN_ID is not None and user_id is not None and user_id == ADMIN_ID


# ── 키보드 헬퍼 ──────────────────────────────────────────────────────────────

def _admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 게시물 목록",     callback_data=CB_POSTS_LIST)],
        [InlineKeyboardButton("➕ 게시물 추가",     callback_data=CB_POST_ADD)],
        [InlineKeyboardButton("🗑 게시물 삭제",     callback_data=CB_POST_DELETE)],
        [InlineKeyboardButton("📤 즉시 전체 발송", callback_data=CB_SEND)],
        [InlineKeyboardButton("📊 구독자 현황",    callback_data=CB_STATUS)],
        [InlineKeyboardButton("⚙️ 캠페인 설정",   callback_data=CB_CONFIG)],
    ])


def _config_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 링크 변경",       callback_data=CB_CONFIG_URL)],
        [InlineKeyboardButton("📝 캡션 수정",        callback_data=CB_CONFIG_CAPTION)],
        [InlineKeyboardButton("🤖 봇 링크 변경",        callback_data=CB_CONFIG_BOT_LINK)],
        [InlineKeyboardButton("🔘 DM 버튼 텍스트 변경", callback_data=CB_CONFIG_BTN_TEXT)],
        [InlineKeyboardButton("👁 현재 설정 확인",      callback_data=CB_CONFIG_VIEW)],
        [InlineKeyboardButton("🏠 메인 메뉴",        callback_data=CB_HOME)],
    ])


def _home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🏠 메인 메뉴", callback_data=CB_HOME)]]
    )


def _posts_delete_keyboard(posts: list[dict]) -> InlineKeyboardMarkup:
    """게시물별 삭제 버튼 키보드."""
    rows = []
    for p in posts[:10]:
        cap_preview = (p["caption"] or "")[:20] or "(캡션없음)"
        label = f"🗑 #{p['id']} [{p['file_type']}] {cap_preview}"
        rows.append([InlineKeyboardButton(label, callback_data=f"sub_del_{p['id']}")])
    rows.append([InlineKeyboardButton("🏠 메인 메뉴", callback_data=CB_HOME)])
    return InlineKeyboardMarkup(rows)


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

    # campaign_config 로드
    try:
        from app.pg_broadcast import get_campaign_config
        cfg = get_campaign_config()
    except Exception as _e:
        logger.warning("subscribe_bot: get_campaign_config 실패: %s", _e)
        cfg = {}

    button_url   = (cfg.get("affiliate_url") or "").strip() or AFFILIATE_URL
    caption_tmpl = (cfg.get("caption_template") or "").strip()
    btn_text     = (cfg.get("button_text") or "🎰 VIP 카지노 입장").strip()

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
        file_id      = post["file_id"]
        file_type    = post["file_type"]
        post_cap     = post["caption"] or ""
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


# ── 미디어 핸들러 (게시물 추가) ──────────────────────────────────────────────

async def admin_media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """관리자가 미디어를 보내면 campaign_posts에 추가 (게시물 추가 대기 중일 때만)."""
    if not update.message or not update.effective_user:
        return
    if not _is_admin(update.effective_user.id):
        return

    awaiting: str | None = context.user_data.get(_AWAITING_KEY)
    if awaiting != "post_add":
        return  # 게시물 추가 대기 중이 아니면 무시

    msg       = update.message
    caption   = msg.caption or ""
    file_id   = ""
    file_type = ""

    if msg.photo:
        file_id   = msg.photo[-1].file_id
        file_type = "photo"
    elif msg.video:
        file_id   = msg.video.file_id
        file_type = "video"
    elif msg.document and msg.document.mime_type and msg.document.mime_type.startswith("video/"):
        file_id   = msg.document.file_id
        file_type = "document"
    else:
        await msg.reply_text("⚠️ 지원하지 않는 미디어 형식입니다. 이미지 또는 영상을 보내주세요.")
        return

    context.user_data.pop(_AWAITING_KEY, None)

    entities_json: str | None = None
    if msg.caption_entities:
        try:
            entities_json = json.dumps([e.to_dict() for e in msg.caption_entities])
        except Exception:
            entities_json = None

    try:
        from app.pg_broadcast import add_post, list_posts
        posts     = list_posts()
        max_order = max((p["send_order"] for p in posts), default=-1)
        post_id   = add_post(
            file_id, file_type, caption,
            send_order=max_order + 1,
            caption_entities=entities_json,
        )
    except Exception as e:
        await msg.reply_text(f"❌ 게시물 저장 실패: {e}", reply_markup=_home_keyboard())
        return

    if post_id:
        cap_preview = caption[:80] + "..." if len(caption) > 80 else caption or "(없음)"
        await msg.reply_text(
            f"✅ 게시물 추가 완료!\n"
            f"ID: #{post_id} | 타입: {file_type}\n"
            f"캡션: {cap_preview}",
            reply_markup=_home_keyboard(),
        )
    else:
        await msg.reply_text("❌ 게시물 저장 실패. 다시 시도해주세요.", reply_markup=_home_keyboard())


# ── 텍스트 입력 핸들러 (설정 값 수신) ────────────────────────────────────────

async def text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """관리자가 설정 값을 텍스트로 입력하면 DB에 저장한다."""
    if not update.message or not update.effective_user:
        return
    if not _is_admin(update.effective_user.id):
        return

    awaiting: str | None = context.user_data.get(_AWAITING_KEY)
    if not awaiting or awaiting == "post_add":
        return  # 설정 대기 상태 아님 — 무시

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

    label   = _FIELD_LABELS.get(awaiting, awaiting)
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
    data  = query.data or ""
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

    # ── 게시물 목록 ────────────────────────────────────────────────────────
    if data == CB_POSTS_LIST:
        if not admin:
            return
        try:
            from app.pg_broadcast import list_posts
            posts = list_posts()
        except Exception as e:
            await query.message.reply_text(f"❌ 조회 실패: {e}", reply_markup=_home_keyboard())
            return
        if not posts:
            await query.message.reply_text("📭 등록된 게시물이 없습니다.", reply_markup=_home_keyboard())
            return
        lines = ["📋 <b>게시물 목록</b>\n"]
        for p in posts:
            status = "✅" if p["is_active"] else "⏸"
            cap    = (p["caption"] or "")[:40] or "(캡션없음)"
            lines.append(
                f"{status} <b>#{p['id']}</b> [{p['file_type']}] 순서:{p['send_order']}\n"
                f"   └ {cap}"
            )
        await query.message.reply_text(
            "\n".join(lines), reply_markup=_home_keyboard(), parse_mode="HTML",
        )
        return

    # ── 게시물 추가 ────────────────────────────────────────────────────────
    if data == CB_POST_ADD:
        if not admin:
            return
        context.user_data[_AWAITING_KEY] = "post_add"
        await query.message.reply_text(
            "➕ <b>게시물 추가</b>\n\n"
            "이미지 또는 영상을 전송하면 자동으로 저장됩니다.\n"
            "캡션도 함께 입력할 수 있습니다.",
            parse_mode="HTML",
        )
        return

    # ── 게시물 삭제 목록 ───────────────────────────────────────────────────
    if data == CB_POST_DELETE:
        if not admin:
            return
        try:
            from app.pg_broadcast import list_posts
            posts = list_posts()
        except Exception as e:
            await query.message.reply_text(f"❌ 조회 실패: {e}", reply_markup=_home_keyboard())
            return
        if not posts:
            await query.message.reply_text("📭 삭제할 게시물이 없습니다.", reply_markup=_home_keyboard())
            return
        await query.message.reply_text(
            "🗑 <b>삭제할 게시물을 선택하세요</b>",
            reply_markup=_posts_delete_keyboard(posts),
            parse_mode="HTML",
        )
        return

    # ── 게시물 삭제 실행 (sub_del_ID) ─────────────────────────────────────
    if data.startswith("sub_del_"):
        if not admin:
            return
        try:
            post_id = int(data.split("_")[-1])
        except ValueError:
            return
        try:
            from app.pg_broadcast import delete_post
            ok = delete_post(post_id)
        except Exception as e:
            await query.message.reply_text(f"❌ 삭제 실패: {e}", reply_markup=_home_keyboard())
            return
        if ok:
            await query.message.reply_text(
                f"✅ 게시물 #{post_id} 삭제 완료.", reply_markup=_home_keyboard()
            )
        else:
            await query.message.reply_text(
                f"❌ #{post_id} 삭제 실패 (이미 삭제됨?).", reply_markup=_home_keyboard()
            )
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

    if data == CB_CONFIG_CAPTION:
        if not admin:
            return
        context.user_data[_AWAITING_KEY] = "caption_template"
        await query.message.reply_text(
            "📝 새 <b>캡션 템플릿</b>을 입력해주세요.\n\n"
            "• 비워두면 게시물 원본 캡션이 사용됩니다.",
            parse_mode="HTML",
        )
        return

    if data == CB_CONFIG_VIEW:
        if not admin:
            return
        try:
            from app.pg_broadcast import get_campaign_config
            cfg      = get_campaign_config()
            url      = cfg.get("affiliate_url")     or "(미설정 — 환경변수 폴백)"
            tmpl     = cfg.get("caption_template")   or "(미설정 — 게시물 캡션 사용)"
            bot_link = cfg.get("subscribe_bot_link") or "(미설정)"
            btn_text = cfg.get("button_text")        or "🎰 VIP 카지노 입장"
            updated  = cfg.get("updated_at")
            updated_str = str(updated)[:19] if updated else "없음"
        except Exception as e:
            url = tmpl = bot_link = btn_text = f"오류: {e}"
            updated_str = "-"

        url_preview  = url[:60]   + "..." if len(str(url))  > 60  else url
        tmpl_preview = tmpl[:100] + "..." if len(str(tmpl)) > 100 else tmpl

        await query.message.reply_text(
            f"👁 <b>현재 캠페인 설정</b>\n\n"
            f"🔗 링크: <code>{url_preview}</code>\n"
            f"📝 캡션: <code>{tmpl_preview}</code>\n"
            f"🤖 봇 링크: <code>{bot_link}</code>\n"
            f"🔘 DM 버튼 텍스트: <code>{btn_text}</code>\n\n"
            f"🕐 마지막 수정: {updated_str}",
            reply_markup=_config_keyboard(),
            parse_mode="HTML",
        )
        return

    if data == CB_CONFIG_BOT_LINK:
        if not admin:
            return
        context.user_data[_AWAITING_KEY] = "subscribe_bot_link"
        await query.message.reply_text(
            "🤖 새 <b>봇 링크</b>를 입력해주세요.\n\n"
            "예: <code>t.me/blackdog_eve_casino_bot</code>",
            parse_mode="HTML",
        )
        return

    if data == CB_CONFIG_BTN_TEXT:
        if not admin:
            return
        context.user_data[_AWAITING_KEY] = "button_text"
        await query.message.reply_text(
            "🔘 DM 인라인 버튼에 표시될 <b>버튼 텍스트</b>를 입력해주세요.\n\n"
            "예: <code>🎰 VIP 카지노 입장</code>\n"
            "예: <code>💎 Join VIP Now</code>",
            parse_mode="HTML",
        )
        return


# ── 즉시 발송 (관리자 버튼) ───────────────────────────────────────────────────

async def _do_push(bot, admin_chat_id: int) -> None:
    """구독자 전체에게 campaign_posts의 다음 게시물을 Bot API로 발송."""
    try:
        from app.pg_broadcast import get_next_post
        post = get_next_post()
    except Exception as e:
        await bot.send_message(admin_chat_id, f"❌ 게시물 조회 실패: {e}")
        return

    if not post or not post.get("file_id"):
        await bot.send_message(admin_chat_id, "❌ 발송할 게시물이 없습니다. ➕ 게시물 추가 후 다시 시도하세요.")
        return

    file_id          = post["file_id"]
    file_type        = post["file_type"]
    post_cap         = post["caption"] or ""
    post_id          = post["id"]
    entities_json    = post.get("caption_entities")

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
    _db_caption_tmpl        = (cfg.get("caption_template") or "").strip()
    btn_text                = (cfg.get("button_text") or "🎰 VIP 카지노 입장").strip()

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

    sent = skipped = failed = 0
    for uid, username in users:
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
            if any(k in err for k in ("blocked", "deactivated", "not found", "forbidden", "user is deactivated")):
                skipped += 1
            else:
                failed += 1
                logger.warning("push failed to %d: %s", uid, e)
        await asyncio.sleep(0.05)

    await bot.send_message(
        admin_chat_id,
        f"✅ 즉시 발송 완료! (게시물 #{post_id})\n"
        f"• 성공: {sent}명\n"
        f"• 차단/탈퇴: {skipped}명\n"
        f"• 실패: {failed}명",
    )


# ── 채널 포워딩 ───────────────────────────────────────────────────────────────

async def _forward_channel_post(bot, from_chat_id: int, message_id: int) -> None:
    """채널 게시물을 구독자 전체에 copy_message로 전송 (인라인 버튼 포함)."""
    try:
        from app.pg_broadcast import get_subscribe_users, get_campaign_config
        users = get_subscribe_users()
        cfg   = get_campaign_config()
    except Exception as e:
        logger.warning("channel forward: 구독자/설정 조회 실패: %s", e)
        return

    if not users:
        return

    button_url = (cfg.get("affiliate_url") or "").strip() or AFFILIATE_URL
    keyboard   = InlineKeyboardMarkup([[
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


async def channel_post_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """채널 게시물 수신 → 구독자 전체 포워딩 (백그라운드 실행)."""
    msg = update.channel_post
    if not msg:
        return
    logger.info("채널 게시물 수신 (chat_id=%s, message_id=%s) → 포워딩 시작", msg.chat_id, msg.message_id)
    asyncio.create_task(
        _forward_channel_post(context.bot, msg.chat_id, msg.message_id)
    )


async def _send_media(
    bot,
    chat_id: int,
    file_id: str,
    file_type: str,
    caption: str,
    reply_markup=None,
    entities=None,
) -> None:
    cap  = caption or None
    opts = {"caption": cap, "reply_markup": reply_markup}
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
            admin_media_handler,
        )
    )
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
