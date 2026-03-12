"""
Channel-only auto-posting (user DM is handled by automation using channel posts).
Layout (like reference: link above image, then image + caption + button):
- First message (above image): single line = viP cAsiNo club as bot hyperlink (BOT_USERNAME), no emoji.
- Second message: image + caption (body 3 lines + promo code) + inline button in English.
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

BOT_EMOJI_PREFIX = "🎰 "

PROMO_SUMMARY_PROMPT = """You are summarizing a casino/betting promo or event page for a short channel post.
Rules:
- Output exactly 2 or 3 short lines in English. No bullet list, no extra intro.
- Put 1 or 2 emojis from this set at the very start: 🎰 💎 🔥 ✨ 🎁
- Focus on: main offer, key bonus/event, and one clear CTA (e.g. join now, claim bonus).
- No hashtags, no "click here", no repetition. Output only the summary.

Content:
---
{raw_content}
---
"""


def _bot_start_link(start_param: str = "promo") -> str:
    username = (os.getenv("BOT_USERNAME") or "").strip().lstrip("@")
    if username:
        return f"https://t.me/{username}?start={start_param}"
    return "https://t.me/"


def _summarize_promo_with_gemini(raw_content: str) -> str:
    """Summarize promo/event content in English with emoji at start (GEMINI_API_KEY)."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    fallback = BOT_EMOJI_PREFIX + "VIP events await. Join now!"
    if not api_key:
        return fallback
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        model = os.getenv("LLM_MODEL", "gemini-2.5-flash")
        text = (raw_content or "")[:8000]
        prompt = PROMO_SUMMARY_PROMPT.format(raw_content=text)
        response = client.models.generate_content(model=model, contents=prompt)
        out = (response.text or "").strip()
        if not out:
            return fallback
        # Ensure body starts with a bot emoji if Gemini omitted it
        if out[0] not in "🎰💎🔥✨🎁":
            out = BOT_EMOJI_PREFIX + out
        return out
    except Exception as e:
        logger.warning("Gemini summary failed: %s", e)
        return fallback


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
    """Single line for the message above the image: viP cAsiNo club as clickable link (BOT_USERNAME)."""
    return f'<a href="{_html_esc(bot_link)}">viP cAsiNo club</a>'


def build_premium_caption(promo_summary: str, promo_code: str) -> str:
    """Caption under the image only: body (2–3 lines) + blank line + promo code line. No link line."""
    body = (promo_summary or (BOT_EMOJI_PREFIX + "VIP events await. Join now!")).strip()
    code_val = (promo_code or "PROMO").strip()
    code_line = f"promo code <code>{_html_esc(code_val)}</code>"
    return f"{body}\n\n{code_line}"


def build_premium_keyboard(game_page_url: str) -> InlineKeyboardMarkup:
    """Inline button below post: English label -> game page."""
    url = (game_page_url or "").strip() or "https://t.me/"
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Enter VIP Casino", url=url)]]
    )


async def post_premium_to_channel(bot) -> bool:
    """
    Send one premium post to channel (CHANNEL_ID).
    Scrapes EVENT_PAGE_URL + PROMO_PAGE_URL → Gemini summary → random image + caption + button.
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

        raw_content = get_event_and_promo_content()
        logger.info("스크래핑 완료, 본문 길이: %s", len(raw_content or ""))

        summary = _summarize_promo_with_gemini(raw_content)
        caption_html = build_premium_caption(summary, promo_code)
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
