"""
Admin Bot 핸들러: /start, /admin — 캠페인 현황 조회.

subscribe_bot.py 와 subscribe_push.py 에서 공유하는
SQLite loaded_message 헬퍼(get_loaded_message_full, set_loaded_message)도 여기서 관리.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from telegram import ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes

logger = logging.getLogger("handlers")
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
DB_PATH  = DATA_DIR / "users.db"

ADMIN_ID_RAW = os.getenv("ADMIN_ID") or ""
ADMIN_ID = int(ADMIN_ID_RAW) if ADMIN_ID_RAW.isdigit() else None


def _ensure_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS loaded_message (
            id         INTEGER PRIMARY KEY CHECK (id = 1),
            chat_id    INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            file_id    TEXT    NOT NULL DEFAULT '',
            file_type  TEXT    NOT NULL DEFAULT 'photo',
            caption    TEXT    NOT NULL DEFAULT '',
            loaded_at  TEXT    NOT NULL
        )
        """
    )
    for _sql in [
        "ALTER TABLE loaded_message ADD COLUMN file_id   TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE loaded_message ADD COLUMN file_type TEXT NOT NULL DEFAULT 'photo'",
        "ALTER TABLE loaded_message ADD COLUMN caption   TEXT NOT NULL DEFAULT ''",
    ]:
        try:
            db.execute(_sql)
        except Exception:
            pass
    db.commit()
    return db


_DB = _ensure_db()


def get_loaded_message_full() -> tuple[int, int, str, str, str] | None:
    """(chat_id, message_id, file_id, file_type, caption) 반환. 없으면 None."""
    cur = _DB.execute(
        "SELECT chat_id, message_id, file_id, file_type, caption FROM loaded_message WHERE id = 1"
    )
    row = cur.fetchone()
    if not row:
        return None
    return (row[0], row[1], row[2] or "", row[3] or "photo", row[4] or "")


def set_loaded_message(
    chat_id: int,
    message_id: int,
    *,
    file_id: str = "",
    file_type: str = "photo",
    caption: str = "",
) -> None:
    now = datetime.utcnow().isoformat()
    _DB.execute(
        """INSERT OR REPLACE INTO loaded_message
           (id, chat_id, message_id, file_id, file_type, caption, loaded_at)
           VALUES (1, ?, ?, ?, ?, ?, ?)""",
        (chat_id, message_id, file_id, file_type, caption, now),
    )
    _DB.commit()


def _is_admin(user_id: int | None) -> bool:
    return ADMIN_ID is not None and user_id is not None and user_id == ADMIN_ID


# ── 커맨드 핸들러 ──────────────────────────────────────────────────────────────

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        "안녕하세요!\n"
        "/admin — 캠페인 현황 조회 (관리자 전용)",
        reply_markup=ReplyKeyboardRemove(),
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
        total  = count_total()
        sent   = total - unsent if isinstance(total, int) and isinstance(unsent, int) else "?"
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
