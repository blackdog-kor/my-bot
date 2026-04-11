"""
Admin Bot 핸들러: /admin, 장전, 발송, 알림 (통합 구조).
경로: ROOT_DIR = repo root, CONFIG/DATA/DB = bot/config, data/, bot/src(utils).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode, urlparse

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MessageEntity,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import ContextTypes

# 통합 구조: repo root = parents[2] (bot/handlers/callbacks.py)
ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "bot" / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
# Railway: bot.src 경로로 임포트 (실제 경로 bot/src/)
try:
    from bot.src.utils.sns_client import send_user_entry_event  # type: ignore
except Exception:
    from utils.sns_client import send_user_entry_event  # type: ignore

logger = logging.getLogger("handlers")
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

CONFIG_PATH = ROOT_DIR / "bot" / "config" / "content.json"
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "users.db"

BASE_URL = (os.getenv("BASE_URL") or "").rstrip("/")
PARTNER_ID = os.getenv("PARTNER_ID") or ""
PROMO_CODE = os.getenv("PROMO_CODE") or "1wiNcLub777"
CHANNEL_URL = os.getenv("CHANNEL_URL") or ""
ADMIN_ID_RAW = os.getenv("ADMIN_ID") or ""
ADMIN_ID = int(ADMIN_ID_RAW) if ADMIN_ID_RAW.isdigit() else None

LANGUAGE_OPTIONS = [["English", "한국어"], ["中文", "Português"]]
MENU_ORDER = ["promotion", "event", "slot", "baccarat", "sports", "support"]

CUSTOM_EMOJIS = {
    "{soccer}": ("⚽", "5440877421114987091"),
    "{blue}": ("🔵", "5440406435001305559"),
    "{clap}": ("👏", "5440902980465364270"),
    "{zap}": ("⚡", "5440858085172223133"),
    "{mega}": ("📢", "5440660319108108143"),
    "{heart}": ("❤️", "5440501491217500831"),
    "{plus}": ("➕", "5438192641353226956"),
    "{fire}": ("🔥", "5440826568702204527"),
    "{money}": ("💸", "5440688970834940485"),
}


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_content() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


ensure_dirs()
CONTENT = load_content()

DB = sqlite3.connect(DB_PATH, check_same_thread=False)
DB.execute(
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        language TEXT,
        first_seen TEXT,
        last_seen TEXT
    )
    """
)
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


def get_all_user_ids() -> list[int]:
    db_url = (os.getenv("DATABASE_URL") or "").strip()
    if db_url:
        from app.pg_broadcast import get_unsent_user_ids
        ids = get_unsent_user_ids()
        if ids:
            return ids
    cur = DB.execute("SELECT user_id FROM users ORDER BY user_id")
    return [row[0] for row in cur.fetchall()]


def save_user(user_id: int, username: str | None, language: str) -> None:
    now = datetime.utcnow().isoformat()
    cur = DB.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if row:
        cur.execute(
            "UPDATE users SET username = ?, language = ?, last_seen = ? WHERE user_id = ?",
            (username, language, now, user_id),
        )
    else:
        cur.execute(
            "INSERT INTO users (user_id, username, language, first_seen, last_seen) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, language, now, now),
        )
    DB.commit()
    if (os.getenv("DATABASE_URL") or "").strip():
        try:
            from app.pg_broadcast import upsert_user as pg_upsert
            pg_upsert(user_id, username or "", source="bot")
        except Exception as e:
            logger.warning("pg upsert_user(%s) failed: %s", user_id, e)


def log_event(logger: logging.Logger, event: str, **fields) -> None:
    try:
        logger.info(json.dumps({"event": event, **fields}, ensure_ascii=False))
    except Exception:
        logger.info("event=%s %s", event, fields)


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def render_custom_emoji_text(template: str) -> tuple[str, list[MessageEntity]]:
    result = ""
    entities: list[MessageEntity] = []
    i = 0
    tokens = sorted(CUSTOM_EMOJIS.keys(), key=len, reverse=True)
    while i < len(template):
        matched = False
        for token in tokens:
            if template.startswith(token, i):
                char, emoji_id = CUSTOM_EMOJIS[token]
                offset = utf16_len(result)
                result += char
                length = utf16_len(char)
                entities.append(
                    MessageEntity(type="custom_emoji", offset=offset, length=length, custom_emoji_id=emoji_id)
                )
                i += len(token)
                matched = True
                break
        if not matched:
            result += template[i]
            i += 1
    return result, entities


def get_lang_pack(lang: str) -> dict:
    return CONTENT["languages"][lang]


def get_main_menu_labels(lang: str) -> list[str]:
    return [get_lang_pack(lang)["menu_labels"][k] for k in MENU_ORDER]


def language_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        LANGUAGE_OPTIONS,
        resize_keyboard=True,
        one_time_keyboard=False,
        is_persistent=True,
        input_field_placeholder="Select language",
    )


def menu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    labels = get_main_menu_labels(lang)
    keyboard = [[labels[0], labels[1]], [labels[2], labels[3]], [labels[4], labels[5]]]
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=False,
        is_persistent=True,
        input_field_placeholder="Select menu",
    )


def get_menu_key_from_label(lang: str, label: str) -> str | None:
    pack = get_lang_pack(lang)
    for key in MENU_ORDER:
        if pack["menu_labels"][key] == label:
            return key
    return None


def build_post_template(lang: str, key: str) -> str:
    pack = get_lang_pack(lang)
    if key == "support":
        title = pack["menu_texts"]["support"]["title"]
        message = pack["menu_texts"]["support"]["message"]
        footer = pack["support_footer_template"]
        return f"{title}\n\n{message}\n\n{footer}"
    header = pack["common_header_template"]
    title = pack["menu_texts"][key]["title"]
    message = pack["menu_texts"][key]["message"]
    footer = pack["post_footer_template"]
    promo = pack["promo_footer_template"]
    promo_label = pack.get("promo_code_label", "Referral code")
    promo_code_line = f"{promo_label}: {PROMO_CODE}"
    return f"{header}\n\n{title}\n\n{message}\n\n{footer}\n\n{promo}\n\n{promo_code_line}"


def _build_menu_path(key: str, kind: str) -> str:
    register_paths = {
        "promotion": "/v3/aggressive-casino", "event": "/v3/aggressive-casino",
        "slot": "/v3/aggressive-casino", "baccarat": "/v3/aggressive-casino", "sports": "/v3/aggressive-casino",
    }
    lobby_paths = {
        "promotion": "/promotions", "event": "/freemoney", "slot": "/casino",
        "baccarat": "/casino/live-games", "sports": "/betting",
    }
    if kind == "register":
        path = register_paths.get(key)
        if path:
            return path
        raw = CONTENT["menus"][key].get("register_url", "")
    else:
        path = lobby_paths.get(key)
        if path:
            return path
        raw = CONTENT["menus"][key].get("lobby_url", "")
    if not raw:
        return "/"
    return urlparse(raw).path or "/"


def _build_tracking_url(key: str, kind: str, user_id: int) -> str:
    menu_cfg = CONTENT["menus"].get(key, {})
    if BASE_URL and PARTNER_ID:
        path = _build_menu_path(key, kind)
        query = urlencode({"p": PARTNER_ID, "sub1": str(user_id)})
        return f"{BASE_URL.rstrip('/')}{path}?{query}"
    if kind == "register":
        return menu_cfg.get("register_url", "")
    return menu_cfg.get("lobby_url", "")


def build_buttons(lang: str, key: str, user_id: int) -> InlineKeyboardMarkup:
    pack = get_lang_pack(lang)
    if key == "support":
        rows = [[InlineKeyboardButton(pack["support_button"], url=CONTENT["menus"]["support"]["support_url"])]]
    else:
        register_url = _build_tracking_url(key, "register", user_id)
        lobby_url = _build_tracking_url(key, "lobby", user_id)
        rows = [
            [
                InlineKeyboardButton(pack["register_button"], url=register_url),
                InlineKeyboardButton(pack["lobby_button"], url=lobby_url),
            ],
        ]
    if CHANNEL_URL:
        rows.append([InlineKeyboardButton("📢 공식 채널 입장하기", url=CHANNEL_URL)])
    rows.append([InlineKeyboardButton(pack["close_button"], callback_data="close")])
    return InlineKeyboardMarkup(rows)


async def delete_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except Exception as exc:
        logger.warning("delete_user_message failed: %s", exc)


async def delete_message_safely(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int | None) -> None:
    if not message_id:
        return
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as exc:
        logger.warning("delete_message_safely failed: %s", exc)


async def send_language_prompt(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    old_prompt_id = context.user_data.get("language_prompt_id")
    if old_prompt_id:
        await delete_message_safely(context, chat_id, old_prompt_id)
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text="당신의 언어는 무엇입니까?\nWhat is your language?\n您的语言是什么？\nQual é o seu idioma?",
        reply_markup=language_keyboard(),
    )
    context.user_data["language_prompt_id"] = msg.message_id


async def send_menu_anchor(context: ContextTypes.DEFAULT_TYPE, chat_id: int, lang: str) -> None:
    old_anchor_id = context.user_data.get("menu_anchor_id")
    if old_anchor_id:
        await delete_message_safely(context, chat_id, old_anchor_id)
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=get_lang_pack(lang)["main_caption"],
        reply_markup=menu_keyboard(lang),
    )
    context.user_data["menu_anchor_id"] = msg.message_id


async def upsert_text_post(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    lang: str,
    template_text: str,
    reply_markup: InlineKeyboardMarkup,
) -> None:
    content_post_id = context.user_data.get("content_post_id")
    text, entities = render_custom_emoji_text(template_text)
    pack = get_lang_pack(lang)
    promo_label = pack.get("promo_code_label", "Referral code")
    promo_prefix = f"{promo_label}: "
    idx = text.rfind(promo_prefix)
    if idx != -1:
        code_start = idx + len(promo_prefix)
        promo_text = PROMO_CODE
        if text[code_start : code_start + len(promo_text)] == promo_text:
            offset = utf16_len(text[:code_start])
            length = utf16_len(promo_text)
            entities.append(MessageEntity(type="code", offset=offset, length=length))
    if content_post_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=content_post_id,
                text=text, entities=entities, reply_markup=reply_markup,
            )
            return
        except Exception as exc:
            logger.warning("edit_message_text failed: %s", exc)
    msg = await context.bot.send_message(
        chat_id=chat_id, text=text, entities=entities, reply_markup=reply_markup,
    )
    context.user_data["content_post_id"] = msg.message_id


async def close_content_post(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    content_post_id = context.user_data.get("content_post_id")
    await delete_message_safely(context, chat_id, content_post_id)
    context.user_data["content_post_id"] = None


async def show_menu_post(context: ContextTypes.DEFAULT_TYPE, chat_id: int, lang: str, key: str) -> None:
    text = build_post_template(lang, key)
    buttons = build_buttons(lang, key, user_id=chat_id)
    await upsert_text_post(context=context, chat_id=chat_id, lang=lang, template_text=text, reply_markup=buttons)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_event(logger, "start_command_received", user_id=update.effective_user.id if update.effective_user else None)
    chat_id = update.effective_chat.id
    old_content = context.user_data.get("content_post_id")
    old_anchor = context.user_data.get("menu_anchor_id")
    old_prompt = context.user_data.get("language_prompt_id")
    context.user_data.clear()
    await delete_user_message(update, context)
    await delete_message_safely(context, chat_id, old_content)
    await delete_message_safely(context, chat_id, old_anchor)
    await delete_message_safely(context, chat_id, old_prompt)
    await send_language_prompt(context, chat_id)
    if update.effective_user:
        try:
            await send_user_entry_event(telegram_user_id=update.effective_user.id, username=update.effective_user.username)
        except Exception as exc:
            log_event(logger, "sns_dispatch_error", user_id=update.effective_user.id, error=str(exc))


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    chat_id = update.effective_chat.id
    user_text = (update.message.text or "").strip()
    await delete_user_message(update, context)
    if "lang" not in context.user_data:
        if user_text in CONTENT["languages"]:
            context.user_data["lang"] = user_text
            save_user(
                user_id=update.effective_user.id,
                username=update.effective_user.username,
                language=user_text,
            )
            prompt_id = context.user_data.get("language_prompt_id")
            await delete_message_safely(context, chat_id, prompt_id)
            context.user_data["language_prompt_id"] = None
            await send_menu_anchor(context, chat_id, user_text)
        else:
            await send_language_prompt(context, chat_id)
        return
    lang = context.user_data["lang"]
    key = get_menu_key_from_label(lang, user_text)
    if not key:
        return
    await show_menu_post(context, chat_id, lang, key)


def _is_admin(user_id: int | None) -> bool:
    return ADMIN_ID is not None and user_id is not None and user_id == ADMIN_ID


CALLBACK_LAUNCH_LOADED = "launch_loaded"
CALLBACK_TEST_LOADED = "test_loaded"

# 관리자 인라인 메뉴용 콜백 키
CALLBACK_MENU_SEND = "menu_send"
CALLBACK_MENU_RETRY = "menu_retry"
CALLBACK_MENU_LOAD = "menu_load"
CALLBACK_MENU_HOME = "menu_home"
CALLBACK_CONFIRM_SEND = "confirm_send"
CALLBACK_CONFIRM_RETRY = "confirm_retry"
CALLBACK_CONFIRM_CANCEL = "confirm_cancel"


def _vip_casino_button_markup() -> InlineKeyboardMarkup:
    vip_url = os.getenv("VIP_URL", "https://1wwtgq.com/?p=mskf")
    return InlineKeyboardMarkup([[InlineKeyboardButton("VIP CASINO", url=vip_url)]])


async def _broadcast_loaded_message(bot, admin_chat_id: int) -> str:
    loaded = get_loaded_message_full()
    if not loaded:
        return "❌ 장전된 메시지가 없습니다. 먼저 영상/이미지+캡션 메시지를 봇에게 보내주세요."
    _, _, file_id, file_type, caption = loaded
    if not file_id:
        return "❌ 장전된 메시지에 파일 ID가 없습니다. 메시지를 다시 보내 재장전해 주세요."
    if not (os.getenv("API_ID") and os.getenv("API_HASH") and os.getenv("SESSION_STRING")):
        return "❌ UserBot 환경변수(API_ID, API_HASH, SESSION_STRING)가 설정되지 않았습니다."
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


def _admin_main_menu_keyboard() -> InlineKeyboardMarkup:
    """DM 관련 관리자 메뉴 인라인 키보드."""
    rows = [
        [
            InlineKeyboardButton("📤 DM 발송 실행", callback_data=CALLBACK_MENU_SEND),
            InlineKeyboardButton("🔄 재발송 실행", callback_data=CALLBACK_MENU_RETRY),
        ],
        [
            InlineKeyboardButton("🎬 미디어 장전", callback_data=CALLBACK_MENU_LOAD),
        ],
    ]
    return InlineKeyboardMarkup(rows)


def _home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🏠 메인 메뉴", callback_data=CALLBACK_MENU_HOME)]]
    )


async def _run_script_background(script_name: str) -> None:
    """scripts/{script_name} 를 백그라운드에서 실행."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    script_path = os.path.join(root_dir, "scripts", script_name)
    if not os.path.isfile(script_path):
        logger.warning("Script not found: %s", script_path)
        return
    try:
        await asyncio.create_subprocess_exec(
            sys.executable,
            script_path,
            cwd=root_dir,
            env={**os.environ},
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except Exception as e:
        logger.warning("Failed to start script %s: %s", script_name, e)


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("권한이 없습니다.")
        return
    await update.message.reply_text(
        "🛠 <b>관리자 메뉴</b>\n\n"
        "DM 발송 / 재발송 / 미디어 장전을 이 메뉴에서 관리할 수 있습니다.",
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

    # 1) Telegram Bot 쪽 SQLite loaded_message 에는 기존과 동일하게 Bot API file_id 를 저장
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

    # 2) Bot API file_id 로 원본 파일을 다운로드한 뒤, SESSION_STRING_1 UserBot 의 Saved Messages 에 업로드
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
                if file_type == "video":
                    bio.name = "media.mp4"
                elif file_type == "photo":
                    bio.name = "media.jpg"
                else:
                    bio.name = "media.file"
                if file_type == "photo":
                    sent_msg = await ub.send_photo("me", bio, caption=caption)
                elif file_type == "video":
                    sent_msg = await ub.send_video("me", bio, caption=caption)
                else:
                    sent_msg = await ub.send_document("me", bio, caption=caption)
                userbot_message_id = sent_msg.id

            # 3) PostgreSQL loaded_message 테이블에는 UserBot Saved Messages 의 message_id 를 저장
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
            logger.warning(
                "API_ID/API_HASH/SESSION_STRING_1 not fully set — skipping UserBot upload for loaded_message"
            )
    except Exception as e:
        logger.warning("UserBot loader failed while loading media: %s", e)

    # 사용자 피드백
    if file_type == "photo":
        await update.message.reply_text(
            "✅ 장전 완료 (이미지)\n"
            + (
                f"캡션: {caption[:80]}..."
                if len(caption) > 80
                else f"캡션: {caption or '(없음)'}"
            )
            + "\n\n/admin → [🚀 장전된 메시지 발사]",
        )
    elif file_type == "video":
        await update.message.reply_text("✅ 장전 완료 (영상)\n/admin → [🚀 장전된 메시지 발사]")
    else:
        await update.message.reply_text("✅ 장전 완료 (동영상 파일)\n/admin → [🚀 장전된 메시지 발사]")


async def test_post_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("권한이 없습니다.")
        return
    from app.services.premium_formatter import send_premium_post_to_chat
    sent = await send_premium_post_to_chat(context.bot, update.effective_user.id)
    await update.message.reply_text("테스트 발송 완료. DM을 확인하세요." if sent else "테스트 발송 실패. 로그 확인.")


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data

    # 관리자 메인 메뉴 / DM 관련 콜백
    if data == CALLBACK_MENU_HOME:
        if not _is_admin(query.from_user.id if query.from_user else None):
            await query.message.reply_text("권한이 없습니다.")
            return
        await query.message.reply_text(
            "🏠 메인 메뉴",
            reply_markup=_admin_main_menu_keyboard(),
        )
        return

    if data == CALLBACK_MENU_SEND:
        if not _is_admin(query.from_user.id if query.from_user else None):
            await query.message.reply_text("권한이 없습니다.")
            return
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ 확인", callback_data=CALLBACK_CONFIRM_SEND),
                    InlineKeyboardButton("❌ 취소", callback_data=CALLBACK_CONFIRM_CANCEL),
                ],
                [InlineKeyboardButton("🏠 메인 메뉴", callback_data=CALLBACK_MENU_HOME)],
            ]
        )
        await query.message.reply_text(
            "⚠️ DM 발송을 즉시 실행할까요?", reply_markup=keyboard
        )
        return

    if data == CALLBACK_MENU_RETRY:
        if not _is_admin(query.from_user.id if query.from_user else None):
            await query.message.reply_text("권한이 없습니다.")
            return
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ 확인", callback_data=CALLBACK_CONFIRM_RETRY),
                    InlineKeyboardButton("❌ 취소", callback_data=CALLBACK_CONFIRM_CANCEL),
                ],
                [InlineKeyboardButton("🏠 메인 메뉴", callback_data=CALLBACK_MENU_HOME)],
            ]
        )
        await query.message.reply_text(
            "⚠️ 재발송을 즉시 실행할까요?", reply_markup=keyboard
        )
        return

    if data == CALLBACK_MENU_LOAD:
        if not _is_admin(query.from_user.id if query.from_user else None):
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

    if data == CALLBACK_CONFIRM_SEND:
        if not _is_admin(query.from_user.id if query.from_user else None):
            await query.message.reply_text("권한이 없습니다.")
            return
        await query.message.reply_text(
            "📤 DM 발송 시작됨. 완료 시 알림 드립니다.", reply_markup=_home_keyboard()
        )
        await _run_script_background("dm_campaign_runner.py")
        return

    if data == CALLBACK_CONFIRM_RETRY:
        if not _is_admin(query.from_user.id if query.from_user else None):
            await query.message.reply_text("권한이 없습니다.")
            return
        await query.message.reply_text(
            "🔄 재발송 시작됨.", reply_markup=_home_keyboard()
        )
        await _run_script_background("retry_sender.py")
        return

    if data == CALLBACK_CONFIRM_CANCEL:
        if not _is_admin(query.from_user.id if query.from_user else None):
            await query.message.reply_text("권한이 없습니다.")
            return
        await query.message.reply_text("작업을 취소했습니다.", reply_markup=_home_keyboard())
        return

    # 기존 장전/테스트 콜백
    if data == CALLBACK_TEST_LOADED:
        if not _is_admin(query.from_user.id if query.from_user else None):
            await query.message.reply_text("권한이 없습니다.")
            return
        loaded = get_loaded_message()
        if not loaded:
            await query.message.reply_text("❌ 장전된 메시지가 없습니다. 영상/이미지를 먼저 보내주세요.")
            return
        from_chat_id, message_id = loaded
        admin_chat_id = query.message.chat_id
        try:
            await context.bot.copy_message(
                chat_id=admin_chat_id,
                from_chat_id=from_chat_id,
                message_id=message_id,
                reply_markup=_vip_casino_button_markup(),
            )
            await query.message.reply_text("✅ 테스트 발송 완료. 위 메시지를 확인한 뒤 발사하세요.")
        except Exception as e:
            logger.exception("Test copy_message failed: %s", e)
            await query.message.reply_text(f"❌ 테스트 발송 실패: {e}")
        return

    if data == CALLBACK_LAUNCH_LOADED:
        if not _is_admin(query.from_user.id if query.from_user else None):
            await query.message.reply_text("권한이 없습니다.")
            return
        await query.message.reply_text("📤 발사 시작... 유저 목록을 불러오는 중입니다.")
        summary = await _broadcast_loaded_message(context.bot, query.message.chat_id)
        await query.message.reply_text(summary)
        return

    if data == "close":
        await close_content_post(context, query.message.chat_id)
