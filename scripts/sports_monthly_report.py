#!/usr/bin/env python
"""
Monthly pick accuracy report: query pick_history → generate AI post → publish.

Scheduled: 1st of each month at 01:00 UTC (10:00 KST).
Also callable manually: python scripts/sports_monthly_report.py
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("sports_monthly_report")

_SOURCE = "api:sports:monthly_report"  # stable source identifier for dedup


async def run() -> None:
    from app.config import settings
    from app.pg_broadcast import (
        ensure_channel_content_table,
        is_content_duplicate,
        mark_content_posted,
        save_channel_content,
    )
    from app.pick_tracker import ensure_pick_history_table
    from app.sports_periodic_content import generate_monthly_report

    ensure_channel_content_table()
    ensure_pick_history_table()

    if is_content_duplicate(_SOURCE, 0):
        logger.info("월간 리포트: 이미 이번 달 게시됨 — 스킵")
        return

    cta_url = settings.affiliate_url or settings.vip_url or ""

    try:
        post = await generate_monthly_report(cta_url=cta_url)
    except Exception as e:
        logger.exception("월간 리포트 생성 실패: %s", e)
        return

    if not post:
        logger.info("월간 리포트: 데이터 부족 — 스킵")
        return

    try:
        content_id = save_channel_content(
            original_text=post["text"],
            rewritten_text=post["text"],
            media_type="photo",
            source_channel=_SOURCE,
            source_msg_id=0,
            source_views=0,
            image_url=post.get("image_url"),
        )
    except Exception as e:
        logger.exception("월간 리포트 DB 저장 실패: %s", e)
        return

    if not content_id:
        logger.warning("월간 리포트 DB 저장 실패 (content_id=None)")
        return

    logger.info("월간 픽 성적표 저장 완료 — content_id=%d", content_id)

    if not settings.channel_id:
        logger.info("CHANNEL_ID 미설정 — 채널 게시 스킵")
        return

    try:
        from app.channel_poster import post_to_channel
        success = await post_to_channel({
            "text": post["text"],
            "media_type": "photo",
            "image_url": post.get("image_url"),
        })
        if success:
            mark_content_posted(content_id)
            logger.info("월간 픽 성적표 채널 게시 완료")
        else:
            logger.warning("채널 게시 실패 — content_id=%d는 DB에 보존됨", content_id)
    except Exception as e:
        logger.exception("채널 게시 중 예외: %s", e)


if __name__ == "__main__":
    asyncio.run(run())
