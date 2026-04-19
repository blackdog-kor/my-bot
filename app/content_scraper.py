"""
Content Scraper: Telegram 채널에서 카지노 관련 인기 콘텐츠를 스크래핑.

소스 채널들에서 높은 조회수/반응을 받은 게시물을 수집하여
channel_content 테이블에 저장한다.

사용 기술: Telethon (읽기 전용, 발송 X)
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    MessageMediaDocument,
    MessageMediaPhoto,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.logging_config import get_logger

logger = get_logger("content_scraper")

# ── Constants ────────────────────────────────────────────────────────────────

# 기본 소스 채널 (카지노/슬롯/잭팟 관련 인기 채널)
DEFAULT_SOURCE_CHANNELS: list[str] = [
    "casino_wins_daily",
    "slotbigwins",
    "casino_online_stream",
    "gamblingworld",
    "casinobonuses",
]

# 최소 조회수 기준 (이 이상이면 인기 콘텐츠로 분류)
MIN_VIEWS_THRESHOLD: int = 500

# 스크래핑 기간 (최근 N일)
SCRAPE_DAYS_BACK: int = 2

# 한 채널당 최대 수집 메시지 수
MAX_MESSAGES_PER_CHANNEL: int = 30


def _get_source_channels() -> list[str]:
    """설정 또는 기본값에서 소스 채널 목록 반환."""
    raw = settings.content_scrape_sources.strip()
    if raw:
        return [ch.strip().lstrip("@") for ch in raw.split(",") if ch.strip()]
    return DEFAULT_SOURCE_CHANNELS


async def scrape_channel_content(
    client: TelegramClient,
    channel_username: str,
    min_views: int = MIN_VIEWS_THRESHOLD,
    days_back: int = SCRAPE_DAYS_BACK,
    max_messages: int = MAX_MESSAGES_PER_CHANNEL,
) -> list[dict[str, Any]]:
    """단일 채널에서 인기 콘텐츠 수집.

    Returns:
        List of dicts with keys:
        - text: str (캡션/텍스트)
        - media_type: str ("photo" | "video" | "document" | "text")
        - views: int
        - source_channel: str
        - message_id: int
        - date: datetime
    """
    results: list[dict[str, Any]] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

    try:
        entity = await client.get_entity(channel_username)
    except Exception as e:
        logger.warning(
            "채널 접근 실패: %s — %s", channel_username, e
        )
        return results

    count = 0
    async for msg in client.iter_messages(entity, limit=200):
        if msg.date and msg.date < cutoff:
            break
        if count >= max_messages:
            break

        # 조회수 필터
        views = getattr(msg, "views", 0) or 0
        if views < min_views:
            continue

        # 미디어 타입 분류
        media_type = "text"
        if msg.media:
            if isinstance(msg.media, MessageMediaPhoto):
                media_type = "photo"
            elif isinstance(msg.media, MessageMediaDocument):
                mime = ""
                if msg.media.document and msg.media.document.mime_type:
                    mime = msg.media.document.mime_type
                if "video" in mime:
                    media_type = "video"
                else:
                    media_type = "document"

        text = msg.text or msg.message or ""
        if not text and media_type == "text":
            continue  # 텍스트도 미디어도 없으면 skip

        results.append({
            "text": text,
            "media_type": media_type,
            "views": views,
            "source_channel": channel_username,
            "message_id": msg.id,
            "date": msg.date,
            "has_media": msg.media is not None,
        })
        count += 1

    logger.info(
        "채널 %s에서 %d개 인기 콘텐츠 수집 (min_views=%d)",
        channel_username, len(results), min_views,
    )
    return results


async def scrape_all_sources() -> list[dict[str, Any]]:
    """모든 소스 채널에서 콘텐츠 수집. Telethon 세션 사용."""
    session_str = os.getenv("SESSION_STRING_TELETHON", "").strip()
    if not session_str:
        logger.error("SESSION_STRING_TELETHON이 설정되지 않았습니다.")
        return []

    api_id = settings.api_id
    api_hash = settings.api_hash
    if not api_id or not api_hash:
        logger.error("API_ID / API_HASH 누락")
        return []

    client = TelegramClient(
        StringSession(session_str),
        api_id,
        api_hash,
    )

    all_content: list[dict[str, Any]] = []

    try:
        await client.start()
        me = await client.get_me()
        logger.info("Telethon 연결 성공: %s (id=%d)", me.username, me.id)

        channels = _get_source_channels()
        for ch in channels:
            try:
                items = await scrape_channel_content(client, ch)
                all_content.extend(items)
            except Exception as e:
                logger.warning("채널 %s 스크래핑 실패: %s", ch, e)
            # 채널 간 딜레이 (안티 탐지)
            await asyncio.sleep(2.0)

    except Exception as e:
        logger.exception("콘텐츠 스크래핑 전체 실패: %s", e)
    finally:
        await client.disconnect()

    # 조회수 내림차순 정렬
    all_content.sort(key=lambda x: x["views"], reverse=True)
    logger.info("총 %d개 콘텐츠 수집 완료", len(all_content))
    return all_content


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    results = asyncio.run(scrape_all_sources())
    for r in results[:10]:
        print(f"[{r['views']}뷰] [{r['media_type']}] {r['source_channel']}: {r['text'][:80]}")
