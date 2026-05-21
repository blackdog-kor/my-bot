"""
Group Topic Poster: channel_content를 분류하여 그룹 포럼 토픽에 자동 게시.

완전 자동화 흐름:
1. channel_content (채널 게시 완료, 그룹 미게시) 조회
2. 콘텐츠 분류 (카지노/스포츠/보너스 등)
3. 해당 토픽에 게시 + group_posted=True 마킹
4. 토픽 미존재 시 자동 생성 후 게시
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.group_topic_manager import (
    create_forum_topics,
    ensure_forum_topics_table,
    list_topics,
    post_channel_content_to_topics,
)
from app.logging_config import get_logger

logger = get_logger("group_topic_poster")


async def main() -> None:
    """그룹 토픽 자동 게시 (channel_content 기반)."""
    logger.info("=== 그룹 토픽 자동 게시 시작 ===")

    if not settings.subscribe_bot_token:
        logger.error("SUBSCRIBE_BOT_TOKEN 미설정 — 종료")
        return

    if not settings.group_id:
        logger.error("GROUP_ID 미설정 — 그룹 토픽 게시 스킵")
        return

    ensure_forum_topics_table()

    # 토픽 없으면 자동 생성
    topics = list_topics()
    if not topics:
        logger.info("토픽 미존재 — 자동 생성 시도")
        created = await create_forum_topics()
        if not created:
            logger.error("토픽 생성 실패 — 종료")
            return
        logger.info("토픽 %d개 생성 완료", len(created))

    # channel_content → 그룹 토픽 분류 게시
    posted = await post_channel_content_to_topics(limit=3)
    logger.info("=== 그룹 토픽 게시 완료: %d건 ===", posted)


if __name__ == "__main__":
    asyncio.run(main())
