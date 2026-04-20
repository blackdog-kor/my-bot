"""
Group Topic Setup: 포럼 토픽 초기 생성 스크립트.

- GROUP_ID 그룹에 기본 카테고리(토픽) 일괄 생성
- 스케줄러 또는 수동 실행 가능
- 이미 존재하는 토픽은 스킵

사용법:
  python scripts/group_topic_setup.py
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
)
from app.logging_config import get_logger

logger = get_logger("group_topic_setup")


async def main() -> None:
    """토픽 테이블 확인 후 포럼 토픽 생성."""
    logger.info("=== 포럼 토픽 초기 설정 시작 ===")

    if not settings.subscribe_bot_token:
        logger.error("SUBSCRIBE_BOT_TOKEN 미설정 — 종료")
        return

    if not settings.group_id:
        logger.error("GROUP_ID 미설정 — 종료")
        return

    # DB 테이블 확인
    ensure_forum_topics_table()

    # 현재 상태 확인
    existing = list_topics()
    logger.info("기존 등록 토픽: %d개", len(existing))

    # 토픽 생성
    created = await create_forum_topics()

    if created:
        logger.info("=== 토픽 생성 완료: %d개 ===", len(created))
        for t in created:
            logger.info("  ✅ %s (thread_id=%d, type=%s)", t["name"], t["thread_id"], t["content_type"])
    else:
        logger.info("=== 추가 생성할 토픽 없음 (모두 존재) ===")

    # 최종 목록 출력
    all_topics = list_topics()
    logger.info("=== 전체 등록 토픽 (%d개) ===", len(all_topics))
    for t in all_topics:
        status = "✅" if t["is_active"] else "⏸"
        logger.info("  %s %s [%s] thread_id=%d", status, t["name"], t["content_type"], t["thread_id"])


if __name__ == "__main__":
    asyncio.run(main())
