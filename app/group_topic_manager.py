"""
Group Topic Manager: forum topic creation and management.

Posting logic (classify_content, post_to_topic, etc.) lives in group_topic_poster.py.
This module re-exports everything so existing imports continue to work.
"""
from __future__ import annotations

import asyncio
from typing import Any

from telegram import Bot

from app.config import settings
from app.group_topic_db import (
    ensure_forum_topics_table,
    get_topic_by_content_type,
    list_topics,
    save_topic,
)
from app.group_topic_poster import (
    auto_post_campaign_to_topics,
    classify_content,
    post_channel_content_to_topics,
    post_to_topic,
)
from app.logging_config import get_logger

logger = get_logger("group_topic_manager")

__all__ = [
    "ensure_forum_topics_table",
    "list_topics",
    "save_topic",
    "get_topic_by_content_type",
    "create_forum_topics",
    "classify_content",
    "post_to_topic",
    "auto_post_campaign_to_topics",
    "post_channel_content_to_topics",
    "DEFAULT_TOPICS",
]

DEFAULT_TOPICS: list[dict[str, Any]] = [
    {"name": "📢 공지사항",    "icon_color": 0x6FB9F0, "content_type": "announcement",  "description": "운영 공지, 규칙, 이벤트 안내"},
    {"name": "🎰 오늘의 추천", "icon_color": 0xFFD67E, "content_type": "promotion",     "description": "일일 카지노 추천/프로모션"},
    {"name": "💰 입출금 인증", "icon_color": 0xCB86DB, "content_type": "verification",  "description": "회원 입출금 인증 스크린샷"},
    {"name": "🏆 당첨 후기",   "icon_color": 0x8EEE98, "content_type": "winning",       "description": "대박/수익 인증"},
    {"name": "❓ 질문/문의",   "icon_color": 0xFF93B2, "content_type": "question",      "description": "가입 방법, 보너스 문의"},
    {"name": "🎁 보너스 코드", "icon_color": 0xFB6F5F, "content_type": "bonus_code",    "description": "한정 프로모션 코드 공유 (24시간 자동삭제)"},
    {"name": "💬 자유게시판",  "icon_color": 0xFFD67E, "content_type": "general",       "description": "일반 대화"},
    {"name": "⚽ 스포츠 분석", "icon_color": 0x8EEE98, "content_type": "sports",        "description": "경기 일정, 프리뷰, 결과 분석, 순위 업데이트"},
]


async def create_forum_topics(
    bot_token: str | None = None,
    group_id: str | None = None,
) -> list[dict]:
    """Create forum topics in the group and persist to DB.

    Returns:
        List of created topics [{name, thread_id, content_type}, ...]
    """
    token = bot_token or settings.subscribe_bot_token
    gid = group_id or settings.group_id

    if not token:
        logger.error("BOT_TOKEN 미설정 — 토픽 생성 불가")
        return []
    if not gid:
        logger.error("GROUP_ID 미설정 — 토픽 생성 불가")
        return []

    bot = Bot(token=token)
    created: list[dict] = []
    existing_types = {t["content_type"] for t in list_topics()}

    for topic_def in DEFAULT_TOPICS:
        if topic_def["content_type"] in existing_types:
            logger.info("토픽 이미 존재: %s — 스킵", topic_def["name"])
            continue
        try:
            result = await bot.create_forum_topic(
                chat_id=int(gid),
                name=topic_def["name"],
                icon_color=topic_def["icon_color"],
            )
            thread_id = result.message_thread_id
            save_topic(
                thread_id=thread_id,
                name=topic_def["name"],
                content_type=topic_def["content_type"],
                icon_color=topic_def["icon_color"],
                description=topic_def["description"],
            )
            created.append({"name": topic_def["name"], "thread_id": thread_id, "content_type": topic_def["content_type"]})
            logger.info("토픽 생성 완료: %s (thread_id=%d)", topic_def["name"], thread_id)
            await asyncio.sleep(1.0)
        except Exception as e:
            logger.exception("토픽 생성 실패 (%s): %s", topic_def["name"], e)

    return created
