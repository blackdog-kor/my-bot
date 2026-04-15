"""
Admin Bot 핸들러: /start, /admin — 캠페인 현황 조회.
"""
from __future__ import annotations

import logging
import os

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger("handlers")
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

ADMIN_ID_RAW = os.getenv("ADMIN_ID") or ""
ADMIN_ID = int(ADMIN_ID_RAW) if ADMIN_ID_RAW.isdigit() else None


def _is_admin(user_id: int | None) -> bool:
    return ADMIN_ID is not None and user_id is not None and user_id == ADMIN_ID


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        "안녕하세요!\n"
        "/admin — 캠페인 현황 조회 (관리자 전용)"
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("권한이 없습니다.")
        return

    try:
        from app.pg_broadcast import count_unsent_with_username, count_total
        unsent = count_unsent_with_username()
        total = count_total()
        sent = total - unsent if isinstance(total, int) and isinstance(unsent, int) else "?"
    except Exception as e:
        total = sent = unsent = f"오류: {e}"

    sessions = sum(
        1 for i in range(1, 11) if (os.getenv(f"SESSION_STRING_{i}") or "").strip()
    )
    if not sessions and (os.getenv("SESSION_STRING") or "").strip():
        sessions = 1

    await update.message.reply_text(
        "📊 <b>캠페인 현황</b>\n\n"
        f"• 전체 타겟: {total}명\n"
        f"• 발송 완료: {sent}명\n"
        f"• 미발송(대기): {unsent}명\n"
        f"• 활성 세션: {sessions}개",
        parse_mode="HTML",
    )
