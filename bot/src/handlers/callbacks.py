from __future__ import annotations

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

# Ensure src/ is on sys.path so that 'utils.*' can be imported
ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from utils.sns_client import send_user_entry_event  # type: ignore

logger = logging.getLogger("handlers")
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

CONFIG_PATH = ROOT_DIR / "config" / "content.json"
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
        id INTEGER PRIMARY KEY CHECK (id = 1),
        chat_id INTEGER NOT NULL,
        message_id INTEGER NOT NULL,
        loaded_at TEXT NOT NULL
    )
    """
)
DB.commit()


def get_loaded_message() -> tuple[int, int] | None:
    """Return (chat_id, message_id) of the currently loaded message, or None."""
    cur = DB.execute(
        "SELECT chat_id, message_id FROM loaded_message WHERE id = 1"
    )
    row = cur.fetchone()
    return (row[0], row[1]) if row else None


def set_loaded_message(chat_id: int, message_id: int) -> None:
    """Store the single loaded message (replaces any previous)."""
    now = datetime.utcnow().isoformat()
    DB.execute(
        "INSERT OR REPLACE INTO loaded_message (id, chat_id, message_id, loaded_at) VALUES (1, ?, ?, ?)",
        (chat_id, message_id, now),
    )
    DB.commit()


def get_all_user_ids() -> list[int]:
    """Return broadcast target user IDs.
    Uses PostgreSQL broadcast_targets (is_sent=FALSE) when DATABASE_URL is set;
    otherwise falls back to local SQLite users table (all users)."""
    db_url = (os.getenv("DATABASE_URL") or "").strip()
    if db_url:
        from app.pg_broadcast import get_unsent_user_ids
        ids = get_unsent_user_ids()
        if ids:
            return ids
        # If PostgreSQL is empty, fall back to SQLite so local testing still works
    cur = DB.execute("SELECT user_id FROM users ORDER BY user_id")
    return [row[0] for row in cur.fetchall()]


def save_user(user_id: int, username: str | None, language: str) -> None:
    now = datetime.utcnow().isoformat()
    cur = DB.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()

    if row:
        cur.execute(
            """
            UPDATE users
            SET username = ?, language = ?, last_seen = ?
            WHERE user_id = ?
            """,
            (username, language, now, user_id),
        )
    else:
        cur.execute(
            """
            INSERT INTO users (user_id, username, language, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, username, language, now, now),
        )

    DB.commit()

    # Also upsert into shared PostgreSQL broadcast_targets if DATABASE_URL is set
    if (os.getenv("DATABASE_URL") or "").strip():
        try:
            from app.pg_broadcast import upsert_user as pg_upsert
            pg_upsert(user_id, username or "", source="bot")
        except Exception as e:
            logger.warning("pg upsert_user(%s) failed: %s", user_id, e)


def log_event(logger: logging.Logger, event: str, **fields) -> None:
    payload = {"event": event, **fields}
    try:
        logger.info(json.dumps(payload, ensure_ascii=False))
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
                    MessageEntity(
                        type="custom_emoji",
                        offset=offset,
                        length=length,
                        custom_emoji_id=emoji_id,
                    )
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
    pack = get_lang_pack(lang)
    return [pack["menu_labels"][k] for k in MENU_ORDER]


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
    keyboard = [
        [labels[0], labels[1]],
        [labels[2], labels[3]],
        [labels[4], labels[5]],
    ]
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

    # 추천인 코드는 항상 본문 하단에 코드 블록으로 표시 (다국어 라벨 사용)
    promo_code_line = f"{promo_label}: {PROMO_CODE}"

    return f"{header}\n\n{title}\n\n{message}\n\n{footer}\n\n{promo}\n\n{promo_code_line}"


def _build_menu_path(key: str, kind: str) -> str:
    """
    kind: 'register' or 'lobby'
    명시된 키는 고정 경로를 사용하고, 나머지는 content.json을 fallback으로 사용.
    """
    register_paths = {
        "promotion": "/v3/aggressive-casino",
        "event": "/v3/aggressive-casino",
        "slot": "/v3/aggressive-casino",
        "baccarat": "/v3/aggressive-casino",
        "sports": "/v3/aggressive-casino",
    }
    lobby_paths = {
        "promotion": "/promotions",
        "event": "/freemoney",
        "slot": "/casino",
        "baccarat": "/casino/live-games",
        "sports": "/betting",
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

    parsed = urlparse(raw)
    return parsed.path or "/"


def _build_tracking_url(key: str, kind: str, user_id: int) -> str:
    """
    BASE_URL 과 PARTNER_ID 가 설정되어 있으면:
      {BASE_URL}{path}?p={PARTNER_ID}&sub1={user_id}
    그렇지 않으면 content.json 의 기존 URL을 그대로 사용.
    """
    menu_cfg = CONTENT["menus"].get(key, {})

    if BASE_URL and PARTNER_ID:
        path = _build_menu_path(key, kind)
        base = BASE_URL.rstrip("/")
        query = urlencode({"p": PARTNER_ID, "sub1": str(user_id)})
        return f"{base}{path}?{query}"

    if kind == "register":
        return menu_cfg.get("register_url", "")
    return menu_cfg.get("lobby_url", "")


def build_buttons(lang: str, key: str, user_id: int) -> InlineKeyboardMarkup:
    pack = get_lang_pack(lang)

    if key == "support":
        rows = [
            [
                InlineKeyboardButton(
                    pack["support_button"],
                    url=CONTENT["menus"]["support"]["support_url"],
                )
            ],
        ]
    else:
        register_url = _build_tracking_url(key, kind="register", user_id=user_id)
        lobby_url = _build_tracking_url(key, kind="lobby", user_id=user_id)

        rows = [
            [
                InlineKeyboardButton(
                    pack["register_button"],
                    url=register_url,
                ),
                InlineKeyboardButton(
                    pack["lobby_button"],
                    url=lobby_url,
                ),
            ],
        ]

    if CHANNEL_URL:
        rows.append(
            [
                InlineKeyboardButton(
                    "📢 공식 채널 입장하기",
                    url=CHANNEL_URL,
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                pack["close_button"],
                callback_data="close",
            )
        ]
    )

    return InlineKeyboardMarkup(rows)


async def delete_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=update.message.message_id,
        )
    except Exception as exc:
        logger.warning("delete_user_message failed: %s", exc)


async def delete_message_safely(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int | None,
) -> None:
    if not message_id:
        return
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as exc:
        logger.warning("delete_message_safely failed: %s", exc)


async def send_language_prompt(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
) -> None:
    old_prompt_id = context.user_data.get("language_prompt_id")
    if old_prompt_id:
        await delete_message_safely(context, chat_id, old_prompt_id)

    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "당신의 언어는 무엇입니까?\n"
            "What is your language?\n"
            "您的语言是什么？\n"
            "Qual é o seu idioma?"
        ),
        reply_markup=language_keyboard(),
    )
    context.user_data["language_prompt_id"] = msg.message_id


async def send_menu_anchor(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    lang: str,
) -> None:
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

    # Mark the referral code segment as a code block so it is easy to copy.
    pack = get_lang_pack(lang)
    promo_label = pack.get("promo_code_label", "Referral code")
    promo_prefix = f"{promo_label}: "
    idx = text.rfind(promo_prefix)
    if idx != -1:
        code_start = idx + len(promo_prefix)
        # The code text is the PROMO_CODE itself.
        promo_text = PROMO_CODE
        # Ensure the text actually ends with the promo code value.
        if text[code_start : code_start + len(promo_text)] == promo_text:
            offset = utf16_len(text[:code_start])
            length = utf16_len(promo_text)
            entities.append(
                MessageEntity(
                    type="code",
                    offset=offset,
                    length=length,
                )
            )

    if content_post_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=content_post_id,
                text=text,
                entities=entities,
                reply_markup=reply_markup,
            )
            return
        except Exception as exc:
            logger.warning("edit_message_text failed, sending new one: %s", exc)

    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        entities=entities,
        reply_markup=reply_markup,
    )
    context.user_data["content_post_id"] = msg.message_id


async def close_content_post(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
) -> None:
    content_post_id = context.user_data.get("content_post_id")
    await delete_message_safely(context, chat_id, content_post_id)
    context.user_data["content_post_id"] = None


async def show_menu_post(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    lang: str,
    key: str,
) -> None:
    text = build_post_template(lang, key)
    # In private chats, chat_id == user_id, which is enough for referral tracking.
    buttons = build_buttons(lang, key, user_id=chat_id)

    await upsert_text_post(
        context=context,
        chat_id=chat_id,
        lang=lang,
        template_text=text,
        reply_markup=buttons,
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_event(
        logger,
        "start_command_received",
        user_id=update.effective_user.id if update.effective_user else None,
    )

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
            await send_user_entry_event(
                telegram_user_id=update.effective_user.id,
                username=update.effective_user.username,
            )
        except Exception as exc:
            log_event(
                logger,
                "sns_dispatch_error",
                user_id=update.effective_user.id,
                error=str(exc),
            )


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


BROADCAST_CHUNK_SIZE = 500
BROADCAST_SLEEP_SEC = 1.2
CALLBACK_LAUNCH_LOADED = "launch_loaded"
CALLBACK_TEST_LOADED = "test_loaded"


def _vip_casino_button_markup() -> InlineKeyboardMarkup:
    """VIP CASINO button — URL is hardcoded, no env var used."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("VIP CASINO", url="https://1wwtgq.com/?p=mskf")]]
    )


async def _broadcast_loaded_message(bot, admin_chat_id: int) -> str:
    """
    Copy the loaded message to all users in chunks. Return summary message.
    Uses copy_message + reply_markup (VIP CASINO). 500 per chunk, 1.2s sleep.
    """
    loaded = get_loaded_message()
    if not loaded:
        return "❌ 장전된 메시지가 없습니다. 먼저 영상/이미지+캡션 메시지를 봇에게 보내주세요."
    from_chat_id, message_id = loaded
    user_ids = get_all_user_ids()
    if not user_ids:
        return "❌ 발송할 유저가 없습니다. (users 테이블 비어 있음)"
    reply_markup = _vip_casino_button_markup()
    use_pg = bool((os.getenv("DATABASE_URL") or "").strip())
    total = len(user_ids)
    sent = 0
    failed = 0
    import asyncio as _asyncio
    for i in range(0, total, BROADCAST_CHUNK_SIZE):
        chunk = user_ids[i : i + BROADCAST_CHUNK_SIZE]
        chunk_sent: list[int] = []
        for uid in chunk:
            try:
                await bot.copy_message(
                    chat_id=uid,
                    from_chat_id=from_chat_id,
                    message_id=message_id,
                    reply_markup=reply_markup,
                )
                sent += 1
                chunk_sent.append(uid)
            except Exception as e:
                failed += 1
                logger.warning("copy_message to %s failed: %s", uid, e)
        # Mark sent in PostgreSQL for is_sent pipeline
        if use_pg and chunk_sent:
            try:
                from app.pg_broadcast import mark_sent
                mark_sent(chunk_sent)
            except Exception as e:
                logger.warning("mark_sent failed for chunk: %s", e)
        # Notify admin after each chunk
        try:
            await bot.send_message(
                admin_chat_id,
                f"📤 청크 발송 완료 {min(i + BROADCAST_CHUNK_SIZE, total)}/{total} (성공 {sent}, 실패 {failed})",
            )
        except Exception:
            pass
        if i + BROADCAST_CHUNK_SIZE < total:
            await _asyncio.sleep(BROADCAST_SLEEP_SEC)
    return f"✅ 발사 완료. 총 {total}명 중 성공 {sent}, 실패 {failed}"


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """관리자 전용: 장전/발사 안내 + [🚀 장전된 메시지 발사] 버튼."""
    if not update.message or not update.effective_user:
        return
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("권한이 없습니다.")
        return
    loaded = get_loaded_message()
    status = "✅ 장전됨 (발사 가능)" if loaded else "⚠️ 장전된 메시지 없음"
    text = (
        "📌 <b>원터치 복사 발송 (Copy Message)</b>\n\n"
        "1️⃣ <b>장전</b>: 이 채팅에 영상 또는 이미지(캡션 가능) 메시지를 보내면 자동으로 장전됩니다.\n"
        "2️⃣ <b>발사</b>: 아래 버튼을 누르면 저장된 메시지를 전체 유저에게 그대로 복사 발송합니다.\n"
        "   • VIP CASINO 버튼이 자동으로 붙습니다.\n"
        "   • 500명 단위 청크, 1.2초 간격으로 발송됩니다.\n\n"
        f"현재 상태: {status}\n\n"
        "미리보기: /test_post"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🧪 장전된 메시지 테스트 (나에게만)", callback_data=CALLBACK_TEST_LOADED)],
        [InlineKeyboardButton("🚀 장전된 메시지 발사", callback_data=CALLBACK_LAUNCH_LOADED)],
    ])
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")


async def admin_load_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin only: when admin sends photo or video (with optional caption), save as 'loaded' message for broadcast."""
    if not update.message or not update.effective_user:
        return
    if not _is_admin(update.effective_user.id):
        return
    msg = update.message
    chat_id = msg.chat_id
    message_id = msg.message_id
    if msg.photo:
        set_loaded_message(chat_id, message_id)
        await update.message.reply_text(
            "✅ 장전 완료 (이미지). 이 메시지가 발사 시 그대로 복사됩니다. /admin 에서 [🚀 장전된 메시지 발사] 를 눌러 발송하세요.",
        )
        return
    if msg.video:
        set_loaded_message(chat_id, message_id)
        await update.message.reply_text(
            "✅ 장전 완료 (영상). 이 메시지가 발사 시 그대로 복사됩니다. /admin 에서 [🚀 장전된 메시지 발사] 를 눌러 발송하세요.",
        )
        return
    if msg.document and msg.document.mime_type and msg.document.mime_type.startswith("video/"):
        set_loaded_message(chat_id, message_id)
        await update.message.reply_text(
            "✅ 장전 완료 (동영상 문서). 이 메시지가 발사 시 그대로 복사됩니다. /admin 에서 [🚀 장전된 메시지 발사] 를 눌러 발송하세요.",
        )
        return
    if msg.document:
        await update.message.reply_text(
            "⚠️ 동영상 또는 이미지를 보내주시면 장전됩니다. (문서는 동영상 파일만 가능)",
        )
        return


async def test_post_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin only: send current premium post format to admin DM for preview."""
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

    if query.data == CALLBACK_TEST_LOADED:
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

    if query.data == CALLBACK_LAUNCH_LOADED:
        if not _is_admin(query.from_user.id if query.from_user else None):
            await query.message.reply_text("권한이 없습니다.")
            return
        await query.message.reply_text("📤 발사 시작... 유저 목록을 불러오는 중입니다.")
        summary = await _broadcast_loaded_message(context.bot, query.message.chat_id)
        await query.message.reply_text(summary)
        return

    if query.data == "close":
        await close_content_post(context, query.message.chat_id)
