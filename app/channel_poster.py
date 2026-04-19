"""
Channel Poster: 채널에 콘텐츠를 자동 게시.

- channel_content 테이블에서 미게시 콘텐츠를 순차 발송
- 인라인 버튼(어필리에이트 링크) 자동 첨부
- 게시 간격 관리 (스팸 방지)
- 게시 후 성과 추적 (조회수)
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.logging_config import get_logger

logger = get_logger("channel_poster")


async def post_to_channel(
    content: dict[str, Any],
    bot_token: str | None = None,
    channel_id: str | None = None,
) -> bool:
    """채널에 단일 콘텐츠 게시.

    Args:
        content: {text, media_type, affiliate_url?, button_text?}
        bot_token: 봇 토큰 (None이면 settings에서 로드)
        channel_id: 채널 ID (None이면 settings에서 로드)

    Returns:
        성공 여부
    """
    from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

    token = bot_token or settings.subscribe_bot_token
    ch_id = channel_id or settings.channel_id

    if not token:
        logger.error("BOT_TOKEN 미설정 — 채널 게시 불가")
        return False
    if not ch_id:
        logger.error("CHANNEL_ID 미설정 — 채널 게시 불가")
        return False

    bot = Bot(token=token)
    text = content.get("text", "")
    affiliate_url = content.get("affiliate_url") or settings.affiliate_url or settings.vip_url
    button_text = content.get("button_text", "🎰 지금 플레이하기")

    # 인라인 버튼 생성
    keyboard = None
    if affiliate_url:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(text=button_text, url=affiliate_url)]
        ])

    try:
        if content.get("media_type") == "photo" and content.get("file_id"):
            await bot.send_photo(
                chat_id=ch_id,
                photo=content["file_id"],
                caption=text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        elif content.get("media_type") == "video" and content.get("file_id"):
            await bot.send_video(
                chat_id=ch_id,
                video=content["file_id"],
                caption=text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        else:
            # 텍스트 전용 게시
            await bot.send_message(
                chat_id=ch_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML",
                disable_web_page_preview=False,
            )

        logger.info("채널 게시 성공: %s (%d chars)", ch_id, len(text))
        return True

    except Exception as e:
        logger.exception("채널 게시 실패: %s", e)
        return False


async def post_pending_content(max_posts: int = 1) -> int:
    """미게시 콘텐츠를 채널에 게시.

    Args:
        max_posts: 한 번에 게시할 최대 수

    Returns:
        실제 게시된 수
    """
    from app.pg_broadcast import get_pending_channel_content, mark_content_posted

    pending = get_pending_channel_content(limit=max_posts)
    if not pending:
        logger.info("게시 대기 콘텐츠 없음")
        return 0

    posted = 0
    for item in pending:
        content = {
            "text": item["rewritten_text"] or item["original_text"],
            "media_type": item.get("media_type", "text"),
            "file_id": item.get("file_id"),
            "affiliate_url": item.get("affiliate_url"),
            "button_text": item.get("button_text", "🎰 지금 플레이하기"),
        }

        success = await post_to_channel(content)
        if success:
            mark_content_posted(item["id"])
            posted += 1
            logger.info("콘텐츠 #%d 게시 완료", item["id"])
        else:
            logger.warning("콘텐츠 #%d 게시 실패", item["id"])

        # 게시 간 딜레이
        if posted < len(pending):
            await asyncio.sleep(5.0)

    return posted


async def check_and_post() -> int:
    """일일 게시 한도 확인 후 게시 실행."""
    from app.pg_broadcast import count_today_posted_content

    today_count = count_today_posted_content()
    max_daily = settings.content_max_daily_posts

    if today_count >= max_daily:
        logger.info(
            "오늘 게시 한도 도달: %d/%d", today_count, max_daily
        )
        return 0

    remaining = max_daily - today_count
    posted = await post_pending_content(max_posts=min(remaining, 2))
    return posted
