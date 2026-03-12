"""
봇 전용: 채널 자동 포스팅만 담당 (유저 DM은 automation에서 채널 게시물 활용).
- 최상단: ( viP cAsiNo cLub ) + 봇 링크 (HTML)
- 메인 이미지: bot/assets/casino_images/ 랜덤 선택
- 본문: EVENT_PAGE_URL + PROMO_PAGE_URL 스크래핑 → Gemini 3줄 요약 + 이모지
- 프로모 코드: <code> 클릭 복사, 하단 버튼 (vip 카지노 입장)
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

PROMO_SUMMARY_PROMPT = """다음은 카지노/베팅 프로모션 페이지에서 가져온 텍스트입니다.
이 내용을 3줄 이내로 핵심만 요약해 주세요.
요약문에는 가독성을 위해 이모지(🎰 💎 🔥 ✨ 🎁 등)를 적절히 1~2개 넣어 주세요.
한국어로만 출력하고, 다른 설명은 하지 마세요.

---
{raw_content}
---
"""


def _bot_start_link(start_param: str = "promo") -> str:
    username = os.getenv("BOT_USERNAME", "").strip()
    if username:
        return f"https://t.me/{username}?start={start_param}"
    return "https://t.me/"


def _summarize_promo_with_gemini(raw_content: str) -> str:
    """Gemini로 3줄 이내 요약 + 이모지 (레일 환경변수 GEMINI_API_KEY 활용)."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return "🎰 VIP 이벤트가 기다립니다. 지금 참여하세요!"
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        model = os.getenv("LLM_MODEL", "gemini-2.5-flash")
        text = (raw_content or "")[:8000]
        prompt = PROMO_SUMMARY_PROMPT.format(raw_content=text)
        response = client.models.generate_content(model=model, contents=prompt)
        return (response.text or "🎰 VIP 이벤트가 기다립니다.").strip()
    except Exception as e:
        logger.warning("Gemini 요약 실패: %s", e)
        return "🎰 VIP 이벤트가 기다립니다. 지금 참여하세요!"


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


def build_premium_caption(promo_summary: str, promo_code: str, bot_link: str) -> str:
    """HTML 캡션: ( viP cAsiNo cLub ) + 봇 링크, 본문, <code>프로모코드</code>."""
    def esc(s: str) -> str:
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    top = f'( viP cAsiNo cLub ) — <a href="{esc(bot_link)}">봇 접속</a>'
    body = (promo_summary or "🎰 VIP 이벤트가 기다립니다.").strip()
    code_line = f'<code>{esc(promo_code or "PROMO")}</code>'
    return f"{top}\n\n{body}\n\n{code_line}"


def build_premium_keyboard(game_page_url: str) -> InlineKeyboardMarkup:
    """하단 인라인 버튼: (vip 카지노 입장) → 게임 페이지."""
    url = (game_page_url or "").strip() or "https://t.me/"
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("(vip 카지노 입장)", url=url)]]
    )


async def post_premium_to_channel(bot) -> bool:
    """
    채널(CHANNEL_ID)에 프리미엄 게시물 1건 전송.
    EVENT_PAGE_URL + PROMO_PAGE_URL 스크래핑 → Gemini 요약 → 랜덤 이미지 + 캡션 + 버튼.
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

        raw_content = get_event_and_promo_content()
        logger.info("스크래핑 완료, 본문 길이: %s", len(raw_content or ""))

        summary = _summarize_promo_with_gemini(raw_content)
        caption_html = build_premium_caption(summary, promo_code, bot_link)
        image_path = get_random_casino_image_path()
        logger.info("이미지 경로: %s", image_path or "(없음, 텍스트만 전송)")

        keyboard = build_premium_keyboard(game_page_url)
        caption = (caption_html[:1024] if len(caption_html) > 1024 else caption_html)

        # 채널 ID는 -100으로 시작하는 문자열 그대로 전달
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
