#!/usr/bin/env python
"""
콘텐츠 자동화 파이프라인: 스크래핑 → AI 리라이팅 → DB 저장 → 채널 게시.

실행 흐름:
1. 소스 채널에서 인기 콘텐츠 스크래핑 (Telethon)
2. 중복 필터링 (이미 수집된 콘텐츠 제외)
3. AI 리라이팅 (OpenAI/Gemini)
4. channel_content 테이블에 저장
5. 대기 콘텐츠 채널 게시

scheduler.py에서 subprocess로 실행됨.
"""
from __future__ import annotations

import asyncio
import logging
import os
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
logger = logging.getLogger("content_pipeline")


async def run_scrape_and_rewrite() -> int:
    """스크래핑 + 리라이팅 + DB 저장. 저장된 수 반환."""
    from app.content_scraper import scrape_all_sources
    from app.content_rewriter import rewrite_content
    from app.pg_broadcast import (
        ensure_channel_content_table,
        is_content_duplicate,
        save_channel_content,
    )
    from app.config import settings

    # 테이블 보장
    ensure_channel_content_table()

    # 1. 스크래핑
    logger.info("=== 콘텐츠 스크래핑 시작 ===")
    scraped = await scrape_all_sources()
    if not scraped:
        logger.warning("스크래핑된 콘텐츠 없음")
        return 0

    logger.info("스크래핑 완료: %d개 후보", len(scraped))

    # 2. 중복 필터 + 리라이팅 + 저장
    saved_count = 0
    max_save = 10  # 한 번에 최대 저장 수

    for item in scraped:
        if saved_count >= max_save:
            break

        # 중복 체크
        if is_content_duplicate(item["source_channel"], item["message_id"]):
            continue

        # 텍스트 없으면 스킵
        if not item["text"].strip():
            continue

        # AI 리라이팅
        rewritten = None
        if settings.content_rewrite_enabled:
            try:
                rewritten = await rewrite_content(
                    original_text=item["text"],
                    media_type=item["media_type"],
                )
            except Exception as e:
                logger.warning("리라이팅 실패: %s", e)

        # DB 저장
        content_id = save_channel_content(
            original_text=item["text"],
            rewritten_text=rewritten,
            media_type=item["media_type"],
            source_channel=item["source_channel"],
            source_msg_id=item["message_id"],
            source_views=item["views"],
        )

        if content_id:
            saved_count += 1
            logger.info(
                "콘텐츠 #%d 저장 (src=%s, views=%d)",
                content_id, item["source_channel"], item["views"],
            )

        # API rate limit 방지
        await asyncio.sleep(1.5)

    logger.info("=== 저장 완료: %d개 ===", saved_count)
    return saved_count


async def run_channel_post() -> int:
    """대기 콘텐츠 채널 게시. 게시된 수 반환."""
    from app.channel_poster import check_and_post

    logger.info("=== 채널 게시 시작 ===")
    posted = await check_and_post()
    logger.info("=== 채널 게시 완료: %d개 ===", posted)
    return posted


async def main() -> None:
    """전체 파이프라인 실행."""
    import httpx

    bot_token = os.getenv("BOT_TOKEN", "")
    admin_id = os.getenv("ADMIN_ID", "")

    def notify(text: str) -> None:
        if not bot_token or not admin_id:
            return
        try:
            httpx.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": admin_id, "text": text[:4000]},
                timeout=10,
            )
        except Exception:
            pass

    try:
        # Phase 1: 스크래핑 + 리라이팅
        saved = await run_scrape_and_rewrite()

        # Phase 2: 채널 게시
        posted = await run_channel_post()

        result = (
            f"📺 [콘텐츠 자동화] 완료!\n"
            f"• 새 콘텐츠 수집: {saved}개\n"
            f"• 채널 게시: {posted}개"
        )
        logger.info(result)
        notify(result)

    except Exception as e:
        error_msg = f"❌ [콘텐츠 자동화] 실패: {e}"
        logger.exception(error_msg)
        notify(error_msg)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
