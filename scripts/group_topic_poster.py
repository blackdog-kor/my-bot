"""
Group Topic Poster: 스케줄러에서 호출하여 토픽에 자동 게시.

- campaign_posts 콘텐츠를 분류하여 적절한 토픽에 게시
- 토픽 미생성 시 자동으로 생성 먼저 수행
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.group_topic_manager import (
    auto_post_campaign_to_topics,
    create_forum_topics,
    ensure_forum_topics_table,
    list_topics,
)
from app.logging_config import get_logger

logger = get_logger("group_topic_poster")


async def main() -> None:
    """토픽 존재 확인 후 자동 게시."""
    logger.info("=== 그룹 토픽 자동 게시 시작 ===")

    if not settings.subscribe_bot_token:
        logger.error("SUBSCRIBE_BOT_TOKEN 미설정 — 종료")
        return

    if not settings.group_id:
        logger.error("GROUP_ID 미설정 — 토픽 게시 스킵")
        return

    # DB 테이블 확인
    ensure_forum_topics_table()

    # 토픽이 없으면 먼저 생성
    topics = list_topics()
    if not topics:
        logger.info("토픽 미존재 — 자동 생성 시도")
        created = await create_forum_topics()
        if not created:
            logger.error("토픽 생성 실패 — 종료")
            return
        logger.info("토픽 %d개 생성 완료", len(created))

    # 자동 게시
    posted = await auto_post_campaign_to_topics()
    logger.info("=== 그룹 토픽 게시 완료: %d건 ===", posted)


if __name__ == "__main__":
    asyncio.run(main())
