"""
Admin Bot 핸들러: /admin — 장전 / DM 발송 / DB 현황.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

logger = logging.getLogger("handlers")
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "users.db"

ADMIN_ID_RAW = os.getenv("ADMIN_ID") or ""
ADMIN_ID = int(ADMIN_ID_RAW) if ADMIN_ID_RAW.isdigit() else None


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


ensure_dirs()

DB = sqlite3.connect(DB_PATH, check_same_thread=False)
DB.execute(
    """
    CREATE TABLE IF NOT EXISTS loaded_message (
        id       INTEGER PRIMARY KEY CHECK (id = 1),
        chat_id  INTEGER NOT NULL,
        message_id INTEGER NOT NULL,
        file_id  TEXT    NOT NULL DEFAULT '',
        file_type TEXT   NOT NULL DEFAULT 'photo',
        caption  TEXT    NOT NULL DEFAULT '',
        loaded_at TEXT   NOT NULL
    )
    """
)
for _col_sql in [
    "ALTER TABLE loaded_message ADD COLUMN file_id   TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE loaded_message ADD COLUMN file_type TEXT NOT NULL DEFAULT 'photo'",
    "ALTER TABLE loaded_message ADD COLUMN caption   TEXT NOT NULL DEFAULT ''",
]:
    try:
        DB.execute(_col_sql)
    except Exception:
        pass
DB.commit()


def get_loaded_message() -> tuple[int, int] | None:
    cur = DB.execute("SELECT chat_id, message_id FROM loaded_message WHERE id = 1")
    row = cur.fetchone()
    return (row[0], row[1]) if row else None


def get_loaded_message_full() -> tuple[int, int, str, str, str] | None:
    cur = DB.execute(
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
    DB.execute(
        """INSERT OR REPLACE INTO loaded_message
           (id, chat_id, message_id, file_id, file_type, caption, loaded_at)
           VALUES (1, ?, ?, ?, ?, ?, ?)""",
        (chat_id, message_id, file_id, file_type, caption, now),
    )
    DB.commit()


def _is_admin(user_id: int | None) -> bool:
    return ADMIN_ID is not None and user_id is not None and user_id == ADMIN_ID


# 콜백 키
CALLBACK_MENU_SEND = "menu_send"
CALLBACK_MENU_LOAD = "menu_load"
CALLBACK_MENU_STATUS = "menu_status"
CALLBACK_MENU_HOME = "menu_home"
CALLBACK_CONFIRM_SEND = "confirm_send"
CALLBACK_CONFIRM_CANCEL = "confirm_cancel"
# 수동 실행 버튼
CALLBACK_RUN_GROUP_FINDER   = "run_group_finder"
CALLBACK_RUN_MEMBER_SCRAPER = "run_member_scraper"
CALLBACK_RUN_DM_CAMPAIGN    = "run_dm_campaign"


def _admin_main_menu_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🎬 미디어 장전", callback_data=CALLBACK_MENU_LOAD)],
        [InlineKeyboardButton("📤 DM 발송 실행", callback_data=CALLBACK_MENU_SEND)],
        [InlineKeyboardButton("📊 DB 현황", callback_data=CALLBACK_MENU_STATUS)],
        [InlineKeyboardButton("─── 수동 실행 ───", callback_data=CALLBACK_MENU_HOME)],
        [InlineKeyboardButton("🔍 그룹 발굴 실행", callback_data=CALLBACK_RUN_GROUP_FINDER)],
        [InlineKeyboardButton("👥 멤버 수집 실행", callback_data=CALLBACK_RUN_MEMBER_SCRAPER)],
        [InlineKeyboardButton("🚀 DM 캠페인 실행", callback_data=CALLBACK_RUN_DM_CAMPAIGN)],
    ]
    return InlineKeyboardMarkup(rows)


def _home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🏠 메인 메뉴", callback_data=CALLBACK_MENU_HOME)]]
    )


async def _run_script_background(script_name: str) -> None:
    """scripts/{script_name} 를 백그라운드에서 실행."""
    root_dir = str(ROOT_DIR)
    script_path = ROOT_DIR / "scripts" / script_name
    if not script_path.is_file():
        logger.warning("Script not found: %s", script_path)
        return
    try:
        await asyncio.create_subprocess_exec(
            sys.executable,
            str(script_path),
            cwd=root_dir,
            env={**os.environ},
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except Exception as e:
        logger.warning("Failed to start script %s: %s", script_name, e)


async def _run_script_watched(
    script_name: str, label: str, bot, admin_chat_id: int
) -> None:
    """
    스크립트를 실행하고 완료를 기다림.
    - 성공: 스크립트가 자체적으로 완료 알림 전송 (이중 알림 방지)
    - 실패(exit != 0): 에러 내용을 관리자에게 DM 전송
    """
    script_path = ROOT_DIR / "scripts" / script_name
    if not script_path.is_file():
        await bot.send_message(admin_chat_id, f"❌ {label}\n스크립트 없음: {script_name}")
        return
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(script_path),
            cwd=str(ROOT_DIR),
            env={**os.environ, "PYTHONPATH": str(ROOT_DIR)},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            err_text = (stdout or b"").decode(errors="replace")[-1500:]
            try:
                await bot.send_message(
                    admin_chat_id,
                    f"❌ {label} 실패 (exit {proc.returncode})\n\n{err_text}",
                )
            except Exception:
                pass
        # 정상 종료 시 스크립트 내부에서 완료 알림을 직접 전송
    except Exception as e:
        logger.exception("_run_script_watched error for %s", script_name)
        try:
            await bot.send_message(
                admin_chat_id,
                f"❌ {label} 실행 중 예외\n{type(e).__name__}: {e}",
            )
        except Exception:
            pass


async def _broadcast_loaded_message(bot, admin_chat_id: int) -> str:
    loaded = get_loaded_message_full()
    if not loaded:
        return "❌ 장전된 메시지가 없습니다. 먼저 영상/이미지+캡션 메시지를 봇에게 보내주세요."
    _, _, file_id, file_type, caption = loaded
    if not file_id:
        return "❌ 장전된 메시지에 파일 ID가 없습니다. 메시지를 다시 보내 재장전해 주세요."

    has_session = any(
        (os.getenv(f"SESSION_STRING_{i}") or "").strip()
        for i in range(1, 11)
    ) or (os.getenv("SESSION_STRING") or "").strip()
    if not (os.getenv("API_ID") and os.getenv("API_HASH") and has_session):
        return "❌ UserBot 환경변수(API_ID, API_HASH, SESSION_STRING_1~10)가 설정되지 않았습니다."
    if not (os.getenv("DATABASE_URL") or "").strip():
        return "❌ DATABASE_URL이 설정되지 않았습니다."

    async def _notify(msg: str) -> None:
        try:
            await bot.send_message(admin_chat_id, msg)
        except Exception:
            pass

    try:
        from app.userbot_sender import broadcast_via_userbot
        result = await broadcast_via_userbot(
            bot_token=os.getenv("BOT_TOKEN", ""),
            file_id=file_id,
            file_type=file_type,
            caption=caption,
            notify_callback=_notify,
        )
        return (
            f"✅ UserBot 발송 완료!\n"
            f"• 전체 대상: {result['total']}명\n"
            f"• 성공: {result['sent']}명\n"
            f"• 차단/탈퇴 (건너뜀): {result['skipped']}명\n"
            f"• 실패: {result['failed']}명"
        )
    except Exception as e:
        logger.exception("UserBot broadcast failed: %s", e)
        return f"❌ UserBot 발송 실패:\n{e}"


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("권한이 없습니다.")
        return
    await update.message.reply_text(
        "🛠 <b>관리자 메뉴</b>",
        reply_markup=_admin_main_menu_keyboard(),
        parse_mode="HTML",
    )


async def admin_load_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if not _is_admin(update.effective_user.id):
        return
    msg = update.message
    chat_id = msg.chat_id
    message_id = msg.message_id
    caption = msg.caption or ""

    file_id = ""
    file_type = ""
    if msg.photo:
        file_id = msg.photo[-1].file_id
        file_type = "photo"
        set_loaded_message(chat_id, message_id, file_id=file_id, file_type=file_type, caption=caption)
    elif msg.video:
        file_id = msg.video.file_id
        file_type = "video"
        set_loaded_message(chat_id, message_id, file_id=file_id, file_type=file_type, caption=caption)
    elif msg.document and msg.document.mime_type and msg.document.mime_type.startswith("video/"):
        file_id = msg.document.file_id
        file_type = "document"
        set_loaded_message(chat_id, message_id, file_id=file_id, file_type=file_type, caption=caption)
    else:
        if msg.document:
            await update.message.reply_text("⚠️ 동영상 또는 이미지를 보내주시면 장전됩니다.")
        return

    # UserBot Saved Messages 업로드 (pg loaded_message 저장용)
    userbot_message_id: int | None = None
    try:
        import io
        import httpx
        from pyrogram import Client

        telegram_file = await context.bot.get_file(file_id)
        async with httpx.AsyncClient(timeout=120) as http:
            resp = await http.get(telegram_file.file_path)
            resp.raise_for_status()
            file_bytes = resp.content

        api_id = int(os.environ.get("API_ID", "0") or "0")
        api_hash = (os.environ.get("API_HASH") or "").strip()
        session_string_1 = (os.environ.get("SESSION_STRING_1") or os.environ.get("SESSION_STRING") or "").strip()

        if api_id and api_hash and session_string_1:
            async with Client(
                "loader",
                api_id=api_id,
                api_hash=api_hash,
                session_string=session_string_1,
                in_memory=True,
            ) as ub:
                bio = io.BytesIO(file_bytes)
                bio.seek(0)
                if file_type == "video":
                    bio.name = "media.mp4"
                    try:
                        sent_msg = await ub.send_video(
                            "me", bio, caption=caption,
                            duration=0, width=0, height=0, supports_streaming=True,
                        )
                    except Exception:
                        logger.warning("loader: send_video 실패 → send_document 재시도")
                        bio = io.BytesIO(file_bytes)
                        bio.seek(0)
                        bio.name = "media.mp4"
                        sent_msg = await ub.send_document("me", bio, caption=caption)
                elif file_type == "photo":
                    bio.name = "media.jpg"
                    try:
                        sent_msg = await ub.send_photo("me", bio, caption=caption)
                    except Exception:
                        logger.warning("loader: send_photo 실패 → send_document 재시도")
                        bio = io.BytesIO(file_bytes)
                        bio.seek(0)
                        bio.name = "media.jpg"
                        sent_msg = await ub.send_document("me", bio, caption=caption)
                else:
                    bio.name = "media.mp4"
                    sent_msg = await ub.send_document("me", bio, caption=caption)
                userbot_message_id = sent_msg.id

            if userbot_message_id is not None and (os.getenv("DATABASE_URL") or "").strip():
                try:
                    from app.pg_broadcast import save_loaded_message as pg_save_loaded_message
                    pg_save_loaded_message(
                        userbot_message_id=userbot_message_id,
                        file_type=file_type,
                        caption=caption,
                    )
                except Exception as e:
                    logger.warning("pg save_loaded_message failed: %s", e)
        else:
            logger.warning("API_ID/API_HASH/SESSION_STRING_1 not set — skipping UserBot upload")
    except Exception:
        logger.exception("UserBot loader failed while loading media")

    if file_type == "photo":
        await update.message.reply_text(
            "✅ 장전 완료 (이미지)\n"
            + (f"캡션: {caption[:80]}..." if len(caption) > 80 else f"캡션: {caption or '(없음)'}")
            + "\n\n/admin → [📤 DM 발송 실행]",
        )
    elif file_type == "video":
        await update.message.reply_text("✅ 장전 완료 (영상)\n/admin → [📤 DM 발송 실행]")
    else:
        await update.message.reply_text("✅ 장전 완료 (동영상 파일)\n/admin → [📤 DM 발송 실행]")


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data
    admin = _is_admin(query.from_user.id if query.from_user else None)

    if data == CALLBACK_MENU_HOME:
        if not admin:
            await query.message.reply_text("권한이 없습니다.")
            return
        await query.message.reply_text(
            "🛠 <b>관리자 메뉴</b>",
            reply_markup=_admin_main_menu_keyboard(),
            parse_mode="HTML",
        )
        return

    if data == CALLBACK_MENU_LOAD:
        if not admin:
            await query.message.reply_text("권한이 없습니다.")
            return
        loaded = get_loaded_message_full()
        if loaded:
            _, _, _, ftype, cap = loaded
            msg = (
                "✅ 현재 장전된 미디어가 있습니다.\n"
                f"• 타입: {ftype}\n"
                f"• 캡션: {cap[:80] + '...' if len(cap) > 80 else cap or '(없음)'}\n\n"
                "새로운 미디어를 이 채팅에 보내면 장전 내용이 교체됩니다."
            )
        else:
            msg = (
                "❌ 장전된 미디어가 없습니다.\n"
                "이 채팅에 영상/이미지(+캡션)를 보내면 자동으로 장전됩니다."
            )
        await query.message.reply_text(msg, reply_markup=_home_keyboard())
        return

    if data == CALLBACK_MENU_SEND:
        if not admin:
            await query.message.reply_text("권한이 없습니다.")
            return
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ 확인", callback_data=CALLBACK_CONFIRM_SEND),
                InlineKeyboardButton("❌ 취소", callback_data=CALLBACK_CONFIRM_CANCEL),
            ],
            [InlineKeyboardButton("🏠 메인 메뉴", callback_data=CALLBACK_MENU_HOME)],
        ])
        await query.message.reply_text("⚠️ DM 발송을 즉시 실행할까요?", reply_markup=keyboard)
        return

    if data == CALLBACK_MENU_STATUS:
        if not admin:
            await query.message.reply_text("권한이 없습니다.")
            return
        try:
            from app.pg_broadcast import count_unsent_with_username, count_total
            unsent = count_unsent_with_username()
            total = count_total()
            sent = total - unsent if isinstance(total, int) and isinstance(unsent, int) else "?"
        except Exception as e:
            total = sent = unsent = f"오류: {e}"
        loaded = get_loaded_message_full()
        loaded_info = (
            f"• 타입: {loaded[3]}, 캡션: {(loaded[4] or '')[:40]}"
            if loaded
            else "없음"
        )
        sessions = sum(
            1 for i in range(1, 11) if (os.getenv(f"SESSION_STRING_{i}") or "").strip()
        )
        if not sessions and (os.getenv("SESSION_STRING") or "").strip():
            sessions = 1
        await query.message.reply_text(
            f"📊 <b>DB 현황</b>\n\n"
            f"• 전체 타겟: {total}명\n"
            f"• 발송 완료: {sent}명\n"
            f"• 미발송(대기): {unsent}명\n"
            f"• 세션 수: {sessions}개\n"
            f"• 장전 미디어: {loaded_info}",
            reply_markup=_home_keyboard(),
            parse_mode="HTML",
        )
        return

    if data == CALLBACK_CONFIRM_SEND:
        if not admin:
            await query.message.reply_text("권한이 없습니다.")
            return
        await query.message.reply_text(
            "📤 DM 발송 시작됨. 완료 시 알림 드립니다.", reply_markup=_home_keyboard()
        )
        await _run_script_background("dm_campaign_runner.py")
        return

    if data == CALLBACK_CONFIRM_CANCEL:
        if not admin:
            await query.message.reply_text("권한이 없습니다.")
            return
        await query.message.reply_text("작업을 취소했습니다.", reply_markup=_home_keyboard())
        return

    if data == CALLBACK_RUN_GROUP_FINDER:
        if not admin:
            await query.message.reply_text("권한이 없습니다.")
            return
        await query.message.reply_text(
            "🔍 그룹 발굴 실행 시작됨\n완료 시 결과 알림 드립니다.",
            reply_markup=_home_keyboard(),
        )
        asyncio.create_task(
            _run_script_watched(
                "group_finder.py", "그룹 발굴",
                context.bot, query.from_user.id,
            )
        )
        return

    if data == CALLBACK_RUN_MEMBER_SCRAPER:
        if not admin:
            await query.message.reply_text("권한이 없습니다.")
            return
        await query.message.reply_text(
            "👥 멤버 수집 실행 시작됨\n완료 시 결과 알림 드립니다.",
            reply_markup=_home_keyboard(),
        )
        asyncio.create_task(
            _run_script_watched(
                "member_scraper.py", "멤버 수집",
                context.bot, query.from_user.id,
            )
        )
        return

    if data == CALLBACK_RUN_DM_CAMPAIGN:
        if not admin:
            await query.message.reply_text("권한이 없습니다.")
            return
        await query.message.reply_text(
            "🚀 DM 캠페인 실행 시작됨\n완료 시 결과 알림 드립니다.",
            reply_markup=_home_keyboard(),
        )
        asyncio.create_task(
            _run_script_watched(
                "dm_campaign_runner.py", "DM 캠페인",
                context.bot, query.from_user.id,
            )
        )
        return
