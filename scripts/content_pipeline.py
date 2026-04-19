#!/usr/bin/env python
"""
콘텐츠 자동화 파이프라인: 스크래핑 → AI 리라이팅 → DB 저장 → 채널 게시.

실행 흐름 (3-Layer 안전 수집):
1. Layer 1: 외부 웹사이트 스크래핑 (차단 위험 0%) — 기본 소스
2. Layer 2: Telethon 채널 스크래핑 (차단 위험 높음) — 폴백, 비활성화 가능
3. 중복 필터링 (이미 수집된 콘텐츠 제외)
4. AI 리라이팅 (OpenAI/Gemini)
5. channel_content 테이블에 저장
6. 대기 콘텐츠 채널 게시

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
    from app.content_rewriter import rewrite_content
    from app.pg_broadcast import (
        ensure_channel_content_table,
        is_content_duplicate,
        save_channel_content,
    )
    from app.config import settings

    # 테이블 보장
    ensure_channel_content_table()

    scraped: list[dict] = []

    # ── Layer 1: 외부 웹 스크래핑 (차단 위험 0%) ──
    if settings.web_scrape_enabled:
        logger.info("=== Layer 1: 외부 웹 스크래핑 시작 ===")
        try:
            from app.web_content_scraper import scrape_web_sources
            web_results = await scrape_web_sources()
            scraped.extend(web_results)
            logger.info("웹 스크래핑 완료: %d개 수집", len(web_results))
        except Exception as e:
            logger.warning("웹 스크래핑 실패 (Layer 1): %s", e)

    # ── Layer 2: Telethon 채널 스크래핑 (폴백, 기본 비활성화) ──
    if settings.telegram_scrape_enabled:
        logger.info("=== Layer 2: Telegram 채널 스크래핑 시작 (주의: 차단 위험) ===")
        try:
            from app.content_scraper import scrape_all_sources
            tg_results = await scrape_all_sources()
            scraped.extend(tg_results)
            logger.info("Telegram 스크래핑 완료: %d개 수집", len(tg_results))
        except Exception as e:
            logger.warning("Telegram 스크래핑 실패 (Layer 2): %s", e)
    else:
        logger.info("Telegram 스크래핑 비활성화 (TELEGRAM_SCRAPE_ENABLED=false)")

    if not scraped:
        logger.warning("스크래핑된 콘텐츠 없음 (모든 Layer)")
        return 0

    logger.info("총 스크래핑 완료: %d개 후보", len(scraped))

    # ── 중복 필터 + 리라이팅 + 저장 ──
    saved_count = 0
    max_save = settings.batch_size

    for item in scraped:
        if saved_count >= max_save:
            break

        # 중복 체크
        source = item.get("source_channel", "unknown")
        msg_id = item.get("message_id", 0)
        if is_content_duplicate(source, msg_id):
            continue

        # 텍스트 없으면 스킵
        text = item.get("text", "").strip()
        if not text:
            continue

        # AI 리라이팅
        rewritten = None
        if settings.content_rewrite_enabled:
            try:
                rewritten = await rewrite_content(
                    original_text=text,
                    media_type=item.get("media_type", "text"),
                )
            except Exception as e:
                logger.warning("리라이팅 실패: %s", e)

        # DB 저장
        content_id = save_channel_content(
            original_text=text,
            rewritten_text=rewritten,
            media_type=item.get("media_type", "text"),
            source_channel=source,
            source_msg_id=msg_id,
            source_views=item.get("views", 0),
        )

        if content_id:
            saved_count += 1
            logger.info(
                "콘텐츠 #%d 저장 (src=%s, views=%d)",
                content_id, source, item.get("views", 0),
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

