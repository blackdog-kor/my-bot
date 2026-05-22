"""
Group Topic Poster: content classification and posting to forum topics.

Handles: classify_content, post_to_topic, auto_post_campaign_to_topics,
post_channel_content_to_topics.
Topic creation/management lives in group_topic_manager.py.
"""
from __future__ import annotations

import asyncio
import io

import httpx
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from app.config import settings
from app.group_topic_db import get_topic_by_content_type, list_topics
from app.logging_config import get_logger

logger = get_logger("group_topic_poster")

_SPORTS_SPECIFIC = [
    "프리뷰", "프리미어리그", "라리가", "세리에", "분데스리가",
    "챔피언스리그", "fixture", "premier league", "la liga",
    "serie a", "bundesliga", "스포츠 분석", "경기 일정",
    "match preview", "match review", "standings",
]
_SPORTS_GENERIC = ["스포츠", "경기", "축구", "football", "soccer", "베팅", "배당", "순위"]


def classify_content(caption: str, file_type: str = "") -> str:
    """Classify content into a forum topic content_type by keyword matching."""
    text = (caption or "").lower()

    if any(kw in text for kw in ["공지", "규칙", "안내", "notice", "rule", "변경"]):
        return "announcement"
    if any(kw in text for kw in _SPORTS_SPECIFIC):
        return "sports"
    if sum(1 for kw in _SPORTS_GENERIC if kw in text) >= 2:
        return "sports"
    if any(kw in text for kw in ["보너스코드", "bonus code", "프로모코드", "promo code", "쿠폰"]):
        return "bonus_code"
    if any(kw in text for kw in ["입금", "출금", "인증", "deposit", "withdraw"]):
        return "verification"
    if any(kw in text for kw in ["당첨", "대박", "수익", "win", "jackpot", "후기"]):
        return "winning"
    if any(kw in text for kw in ["질문", "문의", "어떻게", "방법", "가입", "?", "question"]):
        return "question"
    return "promotion"


async def post_to_topic(
    content_type: str,
    text: str,
    file_id: str | None = None,
    file_type: str = "text",
    bot_token: str | None = None,
    group_id: str | None = None,
    affiliate_url: str | None = None,
    button_text: str = "🎰 지금 플레이하기",
    image_url: str | None = None,
) -> bool:
    """Post content to the matching forum topic.

    image_url takes priority: downloads and sends as photo with caption.
    """
    token = bot_token or settings.subscribe_bot_token
    gid = group_id or settings.group_id

    if not token or not gid:
        logger.error("BOT_TOKEN 또는 GROUP_ID 미설정 — 토픽 게시 불가")
        return False

    topic = get_topic_by_content_type(content_type)
    if not topic:
        logger.warning("토픽을 찾을 수 없음: content_type=%s", content_type)
        return False

    thread_id = topic["thread_id"]
    bot = Bot(token=token)
    url = affiliate_url or settings.affiliate_url or settings.vip_url
    keyboard = None
    if url and content_type in ("promotion", "announcement", "bonus_code", "sports"):
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(text=button_text, url=url)]])

    try:
        if image_url:
            try:
                async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                    img_resp = await client.get(image_url)
                if img_resp.status_code == 200:
                    bio = io.BytesIO(img_resp.content)
                    bio.name = "sports.jpg"
                    await bot.send_photo(
                        chat_id=int(gid), photo=bio, caption=text[:1024] or None,
                        message_thread_id=thread_id, reply_markup=keyboard, parse_mode="HTML",
                    )
                    logger.info("토픽 이미지 게시 성공: [%s] thread_id=%d", content_type, thread_id)
                    return True
            except Exception as img_err:
                logger.warning("이미지 다운로드 실패, 텍스트 폴백: %s", img_err)

        if file_type == "photo" and file_id:
            await bot.send_photo(
                chat_id=int(gid), photo=file_id, caption=text[:1024] or None,
                message_thread_id=thread_id, reply_markup=keyboard, parse_mode="HTML",
            )
        elif file_type == "video" and file_id:
            try:
                await bot.send_video(
                    chat_id=int(gid), video=file_id, caption=text[:1024] or None,
                    message_thread_id=thread_id, reply_markup=keyboard, parse_mode="HTML",
                )
            except Exception as vid_err:
                logger.warning("send_video 실패, document 폴백: %s", vid_err)
                await bot.send_document(
                    chat_id=int(gid), document=file_id, caption=text[:1024] or None,
                    message_thread_id=thread_id, reply_markup=keyboard, parse_mode="HTML",
                )
        else:
            await bot.send_message(
                chat_id=int(gid), text=text, message_thread_id=thread_id,
                reply_markup=keyboard, parse_mode="HTML", disable_web_page_preview=False,
            )

        logger.info("토픽 게시 성공: [%s] thread_id=%d", content_type, thread_id)
        return True

    except Exception as e:
        logger.exception("토픽 게시 실패 [%s]: %s", content_type, e)
        return False


async def auto_post_campaign_to_topics(
    bot_token: str | None = None,
    group_id: str | None = None,
) -> int:
    """Post next campaign_posts entry to the appropriate forum topic."""
    from app.pg_broadcast import get_campaign_config, get_next_post

    post = get_next_post()
    if not post or not post.get("file_id"):
        logger.info("토픽 게시 대상 없음")
        return 0

    cfg = get_campaign_config()
    affiliate_url = (cfg.get("affiliate_url") or "").strip() or settings.affiliate_url
    btn_text = (cfg.get("button_text") or "🎰 VIP 카지노 입장").strip()
    caption = post["caption"] or ""
    content_type = classify_content(caption, post["file_type"])

    success = await post_to_topic(
        content_type=content_type, text=caption,
        file_id=post["file_id"], file_type=post["file_type"],
        bot_token=bot_token, group_id=group_id,
        affiliate_url=affiliate_url, button_text=btn_text,
    )
    return 1 if success else 0


async def post_channel_content_to_topics(
    limit: int = 3,
    bot_token: str | None = None,
    group_id: str | None = None,
) -> int:
    """Post channel_content (already channel-posted) to forum topics.

    Flow: channel_content → classify → post_to_topic → mark group_posted
    """
    from app.group_topic_manager import create_forum_topics
    from app.pg_broadcast import get_campaign_config, get_pending_group_content, mark_group_posted

    gid = group_id or settings.group_id
    if not gid:
        logger.info("GROUP_ID 미설정 — 그룹 토픽 게시 스킵")
        return 0

    if not list_topics():
        logger.info("포럼 토픽 미존재 — 자동 생성 시도")
        created = await create_forum_topics(bot_token=bot_token, group_id=gid)
        if not created:
            logger.error("토픽 생성 실패 — 그룹 게시 중단")
            return 0

    cfg = get_campaign_config()
    affiliate_url = (cfg.get("affiliate_url") or "").strip() or settings.affiliate_url
    btn_text = (cfg.get("button_text") or "🎰 VIP 카지노 입장").strip()

    items = get_pending_group_content(limit=limit)
    if not items:
        logger.info("그룹 토픽 게시 대상 없음")
        return 0

    posted = 0
    for item in items:
        text = item.get("rewritten_text") or item.get("original_text") or ""
        if not text.strip():
            mark_group_posted(item["id"])
            continue

        if (item.get("source_channel") or "").startswith("sports"):
            content_type = "sports"
        else:
            content_type = classify_content(text)

        if not get_topic_by_content_type(content_type):
            content_type = "promotion"

        success = await post_to_topic(
            content_type=content_type, text=text,
            file_id=item.get("file_id"), file_type=item.get("media_type", "text"),
            bot_token=bot_token, group_id=gid,
            affiliate_url=item.get("affiliate_url") or affiliate_url,
            button_text=item.get("button_text") or btn_text,
            image_url=item.get("image_url"),
        )
        if success:
            mark_group_posted(item["id"])
            posted += 1
        await asyncio.sleep(1.0)

    logger.info("그룹 토픽 자동 게시 완료: %d건", posted)
    return posted
