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

import httpx

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
    )
    from app.sports_scraper import collect_sports_data, collect_sports_data_web_fallback

    ensure_channel_content_table()

    # ── Phase 1: Data collection ──
    # Priority: API-Football (if key + data) → Football-Data.org → web fallback
    sports_data = []
    if settings.sports_api_key:
        logger.info("=== API-Football 데이터 수집 시작 ===")
        try:
            sports_data = await collect_sports_data(days_ahead=settings.match_schedule_days_ahead)
            total = sum(len(sd.upcoming) + len(sd.recent_results) for sd in sports_data)
            logger.info("API 수집 완료: %d개 리그, %d건 경기 데이터", len(sports_data), total)
        except Exception as e:
            logger.warning("API-Football 수집 실패: %s", e)

    # Fallback: Football-Data.org (free, current season) when API-Football yields nothing
    if not any(sd.upcoming or sd.recent_results for sd in sports_data):
        if settings.football_data_api_key:
            logger.info("=== Football-Data.org 폴백 시작 ===")
            try:
                from app.football_data_client import collect_sports_data_fd
                sports_data = await collect_sports_data_fd(days_ahead=settings.match_schedule_days_ahead)
                total = sum(len(sd.upcoming) + len(sd.recent_results) for sd in sports_data)
                logger.info("Football-Data.org 수집 완료: %d개 리그, %d건", len(sports_data), total)
            except Exception as e:
                logger.warning("Football-Data.org 수집 실패: %s", e)
        else:
            logger.info("FOOTBALL_DATA_API_KEY 미설정 — 웹 스크래핑 폴백")
            try:
                await collect_sports_data_web_fallback()
            except Exception as e:
                logger.warning("웹 폴백도 실패: %s", e)
    # Supplement: ESPN for non-EU leagues (MLS/J1/Brasileirao — free, no auth)
    try:
        from app.espn_client import LEAGUE_TO_ESPN, collect_sports_data_espn
        from app.sports_scraper import _get_league_ids
        espn_ids = [lid for lid in _get_league_ids() if lid in LEAGUE_TO_ESPN]
        if espn_ids:
            espn_data = await collect_sports_data_espn(espn_ids)
            if espn_data:
                espn_league_ids = {e.league_id for e in espn_data}
                sports_data = [sd for sd in sports_data if sd.league_id not in espn_league_ids]
                sports_data.extend(espn_data)
                logger.info("ESPN 수집 완료: %d리그", len(espn_data))
    except Exception as e:
        logger.warning("ESPN 수집 실패 (non-critical): %s", e)

    # ── Phase 1.5: Populate match_schedule + fetch odds (shared cache) ──
    from app.odds_fetcher import LEAGUE_SPORT_KEY, fetch_odds_for_league
    odds_cache: dict[int, list] = {}

    if sports_data:
        try:
            from app.match_schedule_db import ensure_match_schedule_table, upsert_match
            from app.odds_fetcher import match_odds_to_game

            ensure_match_schedule_table()
            upserted = 0
            for sd in sports_data:
                if settings.odds_api_key and sd.league_id in LEAGUE_SPORT_KEY and sd.league_id not in odds_cache:
                    try:
                        odds_cache[sd.league_id] = await fetch_odds_for_league(sd.league_id)
                    except Exception:
                        odds_cache[sd.league_id] = []
                for match in sd.upcoming:
                    if not match.match_id or not match.match_date:
                        continue
                    league_odds = odds_cache.get(sd.league_id, [])
                    odds = match_odds_to_game(match.home_team, match.away_team, league_odds)
                    odds_dict = None
                    if odds and odds.has_odds:
                        odds_dict = {
                            "home_win": odds.home_win, "draw": odds.draw, "away_win": odds.away_win,
                            "over_2_5": odds.over_2_5, "under_2_5": odds.under_2_5,
                            "btts_yes": odds.btts_yes, "btts_no": odds.btts_no,
                        }
                    if upsert_match(
                        match_id=match.match_id, league_id=sd.league_id,
                        home_team=match.home_team, away_team=match.away_team,
                        kickoff_utc=match.match_date, league_name=match.league_name,
                        venue=match.venue or "", round_name=match.round_name or "",
                        odds_dict=odds_dict,
                    ):
                        upserted += 1
            logger.info("match_schedule 업서트 완료: %d건", upserted)
        except Exception as e:
            logger.warning("match_schedule 업서트 실패: %s", e)

    # ── Phase 2: AI content generation (reuse odds_cache from Phase 1.5) ──
    logger.info("=== AI 스포츠 콘텐츠 생성 시작 ===")

    cta_url = settings.affiliate_url or settings.vip_url or ""

    from app.pick_tracker import ensure_pick_history_table, format_accuracy_line
    ensure_pick_history_table()
    accuracy_line = format_accuracy_line()

    # Fill odds for any leagues not yet fetched during Phase 1.5
    if settings.odds_api_key and sports_data:
        active_ids = [sd.league_id for sd in sports_data if sd.league_id in LEAGUE_SPORT_KEY]
        for lid in active_ids[:4]:
            if lid not in odds_cache:
                league_odds = await fetch_odds_for_league(lid)
                if league_odds:
                    odds_cache[lid] = league_odds
                    logger.info("배당 수집(2차): league_id=%d → %d건", lid, len(league_odds))
                await asyncio.sleep(0.5)

    posts: list[dict] = []

    if sports_data:
        posts = await generate_daily_sports_content(
            sports_data,
            max_posts=settings.sports_max_daily_posts,
            cta_url=cta_url,
            odds_by_league=odds_cache,
            accuracy_line=accuracy_line,
        )

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
            media_type=post.get("media_type", "photo"),
            source_channel=source,
            source_msg_id=match_id,
            source_views=0,
            image_url=post.get("image_url"),
        )

        if content_id:
            saved_count += 1
            logger.info("스포츠 콘텐츠 #%d 저장 (type=%s)", content_id, post["content_type"])

        await asyncio.sleep(1.0)

    logger.info("=== DB 저장 완료: %d건 ===", saved_count)
    return saved_count


async def run_sports_post() -> tuple[int, int]:
    """스포츠 콘텐츠를 채널 게시 후 그룹 스포츠 토픽에도 게시.

    Returns:
        (채널 게시 수, 그룹 토픽 게시 수)
    """
    from app.config import settings
    from app.channel_poster import post_to_channel
    from app.group_topic_manager import post_channel_content_to_topics
    from app.pg_broadcast import (
        get_pending_channel_content,
        mark_content_posted,
    )

    logger.info("=== 스포츠 콘텐츠 게시 시작 ===")

    pending = get_pending_channel_content(
        limit=settings.sports_max_daily_posts,
        source_prefix="api:sports:",
    )
    sports_pending = pending  # already filtered by source_prefix

    if not sports_pending:
        logger.info("게시 대기 스포츠 콘텐츠 없음")
        return 0, 0

    ch_posted = 0
    for item in sports_pending:
        text = item.get("rewritten_text") or item.get("original_text", "")
        if not text.strip():
            mark_content_posted(item["id"])
            continue

        if settings.channel_id:
            success = await post_to_channel({
                "text": text,
                "media_type": "photo",
                "image_url": item.get("image_url"),
                "affiliate_url": item.get("affiliate_url"),
                "button_text": item.get("button_text", "🎰 스포츠 베팅하기"),
            })
            if success:
                mark_content_posted(item["id"])
                ch_posted += 1
                logger.info("채널 게시 완료: 콘텐츠 #%d", item["id"])

        await asyncio.sleep(3.0)

    # 채널 게시 완료 → 그룹 스포츠 토픽에 자동 반영 (group_posted 흐름)
    grp_posted = 0
    if settings.group_id and ch_posted > 0:
        grp_posted = await post_channel_content_to_topics(limit=ch_posted)

    logger.info("=== 스포츠 게시 완료: 채널 %d건 / 그룹 %d건 ===", ch_posted, grp_posted)
    return ch_posted, grp_posted


async def main() -> None:
    """Full sports pipeline execution."""
    bot_token = os.getenv("SUBSCRIBE_BOT_TOKEN", "")
    admin_id = os.getenv("ADMIN_ID", "")

    async def notify(text: str) -> None:
        if not bot_token or not admin_id:
            return
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json={"chat_id": admin_id, "text": text[:4000]},
                )
        except Exception as e:
            logger.warning("Admin notify failed: %s", e)

    try:
        saved = await run_sports_collect_and_generate()
        ch_posted, grp_posted = await run_sports_post()

        result = (
            f"⚽ [스포츠 자동화] 완료!\n"
            f"• AI 콘텐츠 생성: {saved}건\n"
            f"• 채널 게시: {ch_posted}건\n"
            f"• 그룹 토픽 게시: {grp_posted}건"
        )
        logger.info(result)
        await notify(result)

    except Exception as e:
        error_msg = f"❌ [스포츠 자동화] 실패: {e}"
        logger.exception(error_msg)
        await notify(error_msg)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
