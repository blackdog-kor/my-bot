"""
캠페인 설정 핸들러 — 링크 변경, 버튼 텍스트, 설정 조회 + 텍스트 입력 처리.
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers import (
    AWAITING_KEY,
    CB_CONFIG,
    CB_CONFIG_BTN_TEXT,
    CB_CONFIG_URL,
    CB_CONFIG_VIEW,
    FIELD_LABELS,
    config_keyboard,
    is_admin,
    logger,
)


async def text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """관리자가 설정 값을 텍스트로 입력하면 DB에 저장한다."""
    if not update.message or not update.effective_user:
        return
    if not is_admin(update.effective_user.id):
        return

    awaiting: str | None = context.user_data.get(AWAITING_KEY)
    if not awaiting or awaiting == "post_add":
        return  # 설정 대기 상태 아님 — 무시

    value = (update.message.text or "").strip()
    context.user_data.pop(AWAITING_KEY, None)

    if not value:
        await update.message.reply_text(
            "⚠️ 빈 값은 저장할 수 없습니다. 다시 시도하려면 버튼을 눌러주세요.",
            reply_markup=config_keyboard(),
        )
        return

    try:
        from app.pg_broadcast import update_campaign_config
        ok = update_campaign_config(awaiting, value)
    except Exception as e:
        await update.message.reply_text(
            f"❌ DB 저장 실패: {e}",
            reply_markup=config_keyboard(),
        )
        return

    label = FIELD_LABELS.get(awaiting, awaiting)
    preview = value[:100] + "..." if len(value) > 100 else value
    if ok:
        await update.message.reply_text(
            f"✅ <b>{label}</b> 업데이트 완료!\n\n<code>{preview}</code>",
            reply_markup=config_keyboard(),
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            f"❌ {label} 업데이트 실패.",
            reply_markup=config_keyboard(),
        )


async def handle_config_callbacks(
    data: str, query, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """캠페인 설정 관련 콜백 처리. 처리했으면 True 반환."""
    # ── 캠페인 설정 메뉴
    if data == CB_CONFIG:
        await query.message.reply_text(
            "⚙️ <b>캠페인 설정</b>\n\n변경할 항목을 선택하세요.",
            reply_markup=config_keyboard(),
            parse_mode="HTML",
        )
        return True

    if data == CB_CONFIG_URL:
        context.user_data[AWAITING_KEY] = "affiliate_url"
        await query.message.reply_text(
            "🔗 새 <b>어필리에이트 링크</b>를 입력해주세요.\n\n"
            "예: <code>https://example.com/?ref=abc</code>",
            parse_mode="HTML",
        )
        return True

    if data == CB_CONFIG_VIEW:
        try:
            from app.pg_broadcast import get_campaign_config
            cfg = get_campaign_config()
            url = cfg.get("affiliate_url") or "(미설정 — 환경변수 폴백)"
            btn_text = cfg.get("button_text") or "🎰 VIP 카지노 입장"
            updated = cfg.get("updated_at")
            updated_str = str(updated)[:19] if updated else "없음"
        except Exception as e:
            url = btn_text = f"오류: {e}"
            updated_str = "-"

        url_preview = url[:60] + "..." if len(str(url)) > 60 else url

        await query.message.reply_text(
            f"👁 <b>현재 캠페인 설정</b>\n\n"
            f"🔗 링크: <code>{url_preview}</code>\n"
            f"🔘 DM 버튼 텍스트: <code>{btn_text}</code>\n\n"
            f"🕐 마지막 수정: {updated_str}",
            reply_markup=config_keyboard(),
            parse_mode="HTML",
        )
        return True

    if data == CB_CONFIG_BTN_TEXT:
        context.user_data[AWAITING_KEY] = "button_text"
        await query.message.reply_text(
            "🔘 DM 인라인 버튼에 표시될 <b>버튼 텍스트</b>를 입력해주세요.\n\n"
            "예: <code>🎰 VIP 카지노 입장</code>\n"
            "예: <code>💎 Join VIP Now</code>",
            parse_mode="HTML",
        )
        return True

    return False
