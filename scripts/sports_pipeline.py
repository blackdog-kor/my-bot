#!/usr/bin/env python
"""
Sports Content Pipeline: 스포츠 경기 데이터 수집 → AI 분석 생성 → DB 저장 → 게시.

실행 흐름:
1. API-Football에서 경기 일정/결과/순위 수집 (웹 스크래핑 폴백)
2. AI로 분석 게시물 생성 (프리뷰/리뷰/순위)
3. channel_content 테이블에 저장
4. 포럼 토픽 또는 채널에 자동 게시

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
logger = logging.getLogger("sports_pipeline")


async def run_sports_collect_and_generate() -> int:
    """Collect sports data and generate AI content. Returns saved count."""
    from app.config import settings
    from app.pg_broadcast import (
        ensure_channel_content_table,
        is_content_duplicate,
        save_channel_content,
    )
    from app.sports_content_generator import (
        generate_daily_sports_content,
        generate_match_preview_template,
        generate_match_review_template,
    )
    from app.sports_scraper import (
        collect_sports_data,
        collect_sports_data_web_fallback,
    )

    ensure_channel_content_table()

    # ── Phase 1: Data collection ──
    sports_data = []
    if settings.sports_api_key:
        logger.info("=== API-Football 데이터 수집 시작 ===")
        try:
            sports_data = await collect_sports_data()
            total = sum(
                len(sd.upcoming) + len(sd.recent_results)
                for sd in sports_data
            )
            logger.info("API 수집 완료: %d개 리그, %d건 경기 데이터", len(sports_data), total)
        except Exception as e:
            logger.warning("API 수집 실패: %s", e)
    else:
        logger.info("SPORTS_API_KEY 미설정 — 웹 폴백")
        try:
            web_data = await collect_sports_data_web_fallback()
            logger.info("웹 폴백 수집: %d건", len(web_data))
        except Exception as e:
            logger.warning("웹 폴백도 실패: %s", e)

    # ── Phase 2: AI content generation ──
    logger.info("=== AI 스포츠 콘텐츠 생성 시작 ===")

    affiliate_url = settings.affiliate_url or settings.vip_url
    cta_text = f"👉 스포츠 베팅 시작하기"

    posts: list[dict] = []

    if sports_data:
        # AI generation with collected data
        has_ai_key = bool(
            settings.anthropic_api_key
            or settings.openai_api_key
            or os.getenv("OPENAI_API_KEY", "")
            or settings.gemini_api_key
        )

        if has_ai_key:
            posts = await generate_daily_sports_content(
                sports_data,
                max_posts=settings.sports_max_daily_posts,
                cta_text=cta_text,
            )
        else:
            # Template fallback (no AI key)
            logger.info("AI 키 미설정 — 템플릿 폴백 사용")
            for sd in sports_data:
                for match in sd.upcoming[:2]:
                    text = generate_match_preview_template(match)
                    posts.append({
                        "text": text,
                        "content_type": "sports_preview",
                        "media_type": "text",
                        "source": f"template:sports:{sd.league_name}",
                        "match_id": match.match_id,
                        "league_id": sd.league_id,
                    })
                for match in sd.recent_results[:1]:
                    text = generate_match_review_template(match)
                    posts.append({
                        "text": text,
                        "content_type": "sports_review",
                        "media_type": "text",
                        "source": f"template:sports:{sd.league_name}",
                        "match_id": match.match_id,
                        "league_id": sd.league_id,
                    })

    if not posts:
        logger.warning("스포츠 콘텐츠 생성 결과 없음")
        return 0

    # ── Phase 3: Save to DB ──
    logger.info("=== DB 저장 시작 (%d건) ===", len(posts))
    saved_count = 0

    for post in posts:
        source = post.get("source", "sports")
        match_id = post.get("match_id", 0)

        if is_content_duplicate(source, match_id):
            logger.info("중복 스킵: match_id=%d", match_id)
            continue

        content_id = save_channel_content(
            original_text=post["text"],
            rewritten_text=post["text"],  # Already AI-generated
            media_type=post.get("media_type", "text"),
            source_channel=source,
            source_msg_id=match_id,
            source_views=0,
        )

        if content_id:
            saved_count += 1
            logger.info("스포츠 콘텐츠 #%d 저장 (type=%s)", content_id, post["content_type"])

        await asyncio.sleep(1.0)

    logger.info("=== DB 저장 완료: %d건 ===", saved_count)
    return saved_count


async def run_sports_post() -> int:
    """Post saved sports content to forum topic or channel."""
    from app.config import settings
    from app.group_topic_manager import (
        get_topic_by_content_type,
        post_to_topic,
    )
    from app.channel_poster import post_to_channel
    from app.pg_broadcast import (
        get_pending_channel_content,
        mark_content_posted,
    )

    logger.info("=== 스포츠 콘텐츠 게시 시작 ===")

    pending = get_pending_channel_content(limit=settings.sports_max_daily_posts)
    if not pending:
        logger.info("게시 대기 콘텐츠 없음")
        return 0

    posted = 0
    for item in pending:
        text = item.get("rewritten_text") or item.get("original_text", "")
        source = item.get("source_channel", "")

        # Only process sports content
        if "sports" not in source:
            continue

        # Try forum topic first
        if settings.group_id:
            sports_topic = get_topic_by_content_type("sports")
            if sports_topic:
                success = await post_to_topic(
                    content_type="sports",
                    text=text,
                    file_id=None,
                    file_type="text",
                )
                if success:
                    mark_content_posted(item["id"])
                    posted += 1
                    logger.info("토픽 게시 완료: 콘텐츠 #%d", item["id"])
                    await asyncio.sleep(3.0)
                    continue

        # Fallback: channel post
        if settings.channel_id:
            success = await post_to_channel({"text": text, "media_type": "text"})
            if success:
                mark_content_posted(item["id"])
                posted += 1
                logger.info("채널 게시 완료: 콘텐츠 #%d", item["id"])

        await asyncio.sleep(3.0)

    logger.info("=== 스포츠 콘텐츠 게시 완료: %d건 ===", posted)
    return posted


async def main() -> None:
    """Full sports pipeline execution."""
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
        except Exception as e:
            logger.warning("Admin notify failed: %s", e)

    try:
        saved = await run_sports_collect_and_generate()
        posted = await run_sports_post()

        result = (
            f"⚽ [스포츠 자동화] 완료!\n"
            f"• AI 콘텐츠 생성: {saved}건\n"
            f"• 게시 완료: {posted}건"
        )
        logger.info(result)
        notify(result)

    except Exception as e:
        error_msg = f"❌ [스포츠 자동화] 실패: {e}"
        logger.exception(error_msg)
        notify(error_msg)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
