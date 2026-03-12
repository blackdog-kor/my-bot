"""
Channel-only auto-posting (user DM is handled by automation using channel posts).
Layout: (1) Header message with bold ( viP cAsiNo cLub ) link + line breaks.
(2) Image + caption: 4–5 line bullet body, then Referral code + code with spacing, then inline button.
"""
from __future__ import annotations

import logging
import os
import random
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

_BOT_ROOT = Path(__file__).resolve().parents[2]
CASINO_IMAGES_DIR = _BOT_ROOT / "assets" / "casino_images"
PROMPT_PATH = _BOT_ROOT / "prompts" / "promo_summary.txt"
CONTENT_JSON_PATH = _BOT_ROOT / "config" / "content.json"

# Same Unicode emojis as bot (callbacks.CUSTOM_EMOJIS) — use in caption instead of generic emojis.
BOT_EMOJI_MAP = {
    "{fire}": "🔥",
    "{soccer}": "⚽",
    "{plus}": "➕",
    "{money}": "💸",
    "{zap}": "⚡",
    "{clap}": "👏",
    "{mega}": "📢",
    "{heart}": "❤️",
    "{blue}": "🔵",
}

# Fallback body if content.json missing (same as config content.json English common_header_template)
_FALLBACK_HEADER_BODY = (
    "🔥 1wiN viP cAsiNo cLub 🔥\n\n"
    "⚽ Sports: Express Bonuses\n"
    "➕ Fiat Deposits: +500% Bonus\n"
    "➕ Crypto Deposits: +600% Bonus\n"
    "💸 Casino: Up to 30% Weekly Cashback\n"
    "⚡ Withdrawals: Lightning-fast / No KYC\n\n"
    "👏 Private VIP entry with faster access, stronger bonuses and a cleaner playing route for premium members."
)


def _bot_start_link(start_param: str = "promo") -> str:
    username = (os.getenv("BOT_USERNAME") or "").strip().lstrip("@")
    if username:
        return f"https://t.me/{username}?start={start_param}"
    return "https://t.me/"


def _get_bot_header_body() -> str:
    """Load English common_header_template from config/content.json and replace {token} with same Unicode emojis as bot."""
    if not CONTENT_JSON_PATH.is_file():
        return _FALLBACK_HEADER_BODY
    try:
        import json
        data = json.loads(CONTENT_JSON_PATH.read_text(encoding="utf-8"))
        pack = (data.get("languages") or {}).get("English") or {}
        template = (pack.get("common_header_template") or "").strip()
        if not template:
            return _FALLBACK_HEADER_BODY
        for token, emoji in BOT_EMOJI_MAP.items():
            template = template.replace(token, emoji)
        return template
    except Exception as e:
        logger.warning("Failed to load content.json for header body: %s", e)
        return _FALLBACK_HEADER_BODY


def get_promo_page_content(url: str) -> str:
    """프로모/이벤트 페이지 URL에서 텍스트 컨텐츠를 긁어옵니다."""
    if not url or not url.startswith("http"):
        return ""
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            for tag in soup(["script", "style"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            return (text or "")[:12000]
    except Exception as e:
        logger.warning("프로모 페이지 스크래핑 실패: %s", e)
        return ""


def get_event_and_promo_content() -> str:
    """EVENT_PAGE_URL, PROMO_PAGE_URL 두 곳에서 게시물 내용을 스크래핑해 합칩니다."""
    event_url = (os.getenv("EVENT_PAGE_URL") or "").strip()
    promo_url = (os.getenv("PROMO_PAGE_URL") or "").strip()
    parts = []
    if event_url:
        text = get_promo_page_content(event_url)
        if text:
            parts.append(f"[이벤트 페이지]\n{text}")
    if promo_url:
        text = get_promo_page_content(promo_url)
        if text:
            parts.append(f"[프로모 페이지]\n{text}")
    return "\n\n---\n\n".join(parts) if parts else ""


def get_random_casino_image_path() -> str | None:
    """bot/assets/casino_images/ 내 이미지 중 random.choice로 하나 반환."""
    if not CASINO_IMAGES_DIR.is_dir():
        return None
    allowed = (".jpg", ".jpeg", ".png", ".gif", ".webp")
    files = [f for f in CASINO_IMAGES_DIR.iterdir() if f.suffix.lower() in allowed]
    if not files:
        return None
    return str(random.choice(files))


def _html_esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_header_message(bot_link: str) -> str:
    """Message above the image: bold ( viP cAsiNo cLub ) as link, with clear line breaks so it is a standalone header."""
    link = f'<a href="{_html_esc(bot_link)}">( viP cAsiNo cLub )</a>'
    return f"\n\n<b>{link}</b>\n\n"


def build_premium_caption(promo_code: str) -> str:
    """Caption under image: same as existing bot (common_header with 🔥⚽➕💸⚡👏), last line 💎 VIP Promotions + copyable code."""
    body = _get_bot_header_body()
    code_val = (promo_code or "PROMO").strip()
    # Last line: VIP Promotions with code — <code> makes it copyable on tap/select in Telegram
    return f"{body}\n\n💎 VIP Promotions  <code>{_html_esc(code_val)}</code>"


def build_premium_keyboard(game_page_url: str) -> InlineKeyboardMarkup:
    """Inline button below post: 'Play now' -> game page (match reference)."""
    url = (game_page_url or "").strip() or "https://t.me/"
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Play now", url=url)]]
    )


async def post_premium_to_channel(bot) -> bool:
    """
    Send one premium post to channel (CHANNEL_ID).
    Uses same caption as existing bot (config content.json common_header + 💎 VIP Promotions + copyable code), random image + button.
    """
    channel_id = (os.getenv("CHANNEL_ID") or "").strip()
    if not channel_id:
        logger.warning("CHANNEL_ID 미설정, 채널 전송 스킵")
        return False

    try:
        logger.info("채널 전송 시작 (CHANNEL_ID 끝 4자리: %s)", channel_id[-4:] if len(channel_id) >= 4 else "?")
        game_page_url = (os.getenv("GAME_PAGE_URL") or "").strip()
        promo_code = (os.getenv("PROMO_CODE") or "PROMO").strip()
        bot_link = _bot_start_link("promo")
        if not (os.getenv("BOT_USERNAME") or "").strip():
            logger.warning("BOT_USERNAME not set — bot link above image may not open the correct bot. Set it in Railway Variables.")

        caption_html = build_premium_caption(promo_code)
        image_path = get_random_casino_image_path()
        logger.info("이미지 경로: %s", image_path or "(없음, 텍스트만 전송)")

        keyboard = build_premium_keyboard(game_page_url)
        caption = (caption_html[:1024] if len(caption_html) > 1024 else caption_html)

        # 1) Message above image: bot link only (viP cAsiNo club -> BOT_USERNAME)
        header_html = build_header_message(bot_link)
        await bot.send_message(
            chat_id=channel_id,
            text=header_html,
            parse_mode="HTML",
        )

        # 2) Image + caption (body + promo code) + inline button
        if image_path and os.path.isfile(image_path):
            with open(image_path, "rb") as f:
                await bot.send_photo(
                    chat_id=channel_id,
                    photo=f,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )
        else:
            await bot.send_message(
                chat_id=channel_id,
                text=caption,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        logger.info("채널 전송 완료: CHANNEL_ID 끝 4자리 %s", channel_id[-4:] if len(channel_id) >= 4 else "?")
        return True
    except Exception as e:
        logger.exception("채널 전송 실패 (상세): %s", e)
        return False


async def send_premium_post_to_chat(bot, chat_id: int) -> bool:
    """
    Compose the same premium post (header + image + caption + button) and send to the given chat_id.
    Used for /test_post so admin can preview in DM.
    """
    try:
        game_page_url = (os.getenv("GAME_PAGE_URL") or "").strip()
        promo_code = (os.getenv("PROMO_CODE") or "PROMO").strip()
        bot_link = _bot_start_link("promo")
        caption_html = build_premium_caption(promo_code)
        image_path = get_random_casino_image_path()
        keyboard = build_premium_keyboard(game_page_url)
        caption = (caption_html[:1024] if len(caption_html) > 1024 else caption_html)

        header_html = build_header_message(bot_link)
        await bot.send_message(chat_id=chat_id, text=header_html, parse_mode="HTML")

        if image_path and os.path.isfile(image_path):
            with open(image_path, "rb") as f:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=f,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )
        else:
            await bot.send_message(
                chat_id=chat_id,
                text=caption,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        return True
    except Exception as e:
        logger.exception("Test post to chat %s failed: %s", chat_id, e)
        return False
