"""
Match Scheduler: real-time match-driven posting engine.

Runs every 30 minutes. Posts previews before kickoff and reviews after.

Posting windows (configurable via env vars):
  Preview: kickoff - MATCH_PREVIEW_HOURS_BEFORE (default 3h) to kickoff - 1h
  Review:  kickoff + MATCH_REVIEW_MINS_AFTER (default 110 min)

Flow per cycle:
  1. populate_schedule()  — fetch upcoming matches from API-Football → match_schedule DB
  2. post_due_previews()  — AI preview + match card → channel + group topic
  3. post_due_reviews()   — AI review + accuracy update → channel + group topic
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.logging_config import get_logger
from app.match_schedule_db import (
    ensure_match_schedule_table,
    get_matches_needing_preview,
    get_matches_needing_review,
    mark_previewed,
    mark_reviewed,
    mark_skipped,
    upsert_match,
)

logger = get_logger("match_scheduler")


# ── Schedule Population ──────────────────────────────────────────────────────

async def populate_schedule(days_ahead: int = 3) -> int:
    """Fetch upcoming matches from API-Football and upsert to match_schedule.

    Returns number of matches added/updated.
    """
    if not settings.sports_api_key:
        logger.info("SPORTS_API_KEY 미설정 — schedule populate 스킵")
        return 0

    from app.sports_scraper import collect_sports_data
    from app.odds_fetcher import fetch_odds_for_league, match_odds_to_game, LEAGUE_SPORT_KEY

    try:
        sports_data = await collect_sports_data(days_ahead=days_ahead)
    except Exception as e:
        logger.warning("sports_data 수집 실패: %s", e)
        return 0

    count = 0
    for sd in sports_data:
        # Fetch odds for this league
        league_odds: list = []
        if settings.odds_api_key and sd.league_id in LEAGUE_SPORT_KEY:
            try:
                league_odds = await fetch_odds_for_league(sd.league_id, hours_ahead=days_ahead * 24)
            except Exception:
                pass

        for match in sd.upcoming:
            if not match.match_id or not match.match_date:
                continue

            odds = match_odds_to_game(match.home_team, match.away_team, league_odds)
            odds_dict: dict | None = None
            if odds and odds.has_odds:
                odds_dict = {
                    "home_win": odds.home_win, "draw": odds.draw, "away_win": odds.away_win,
                    "over_2_5": odds.over_2_5, "under_2_5": odds.under_2_5,
                    "btts_yes": odds.btts_yes, "btts_no": odds.btts_no,
                }

            ok = upsert_match(
                match_id=match.match_id,
                league_id=sd.league_id,
                home_team=match.home_team,
                away_team=match.away_team,
                kickoff_utc=match.match_date,
                league_name=match.league_name,
                venue=match.venue or "",
                round_name=match.round_name or "",
                odds_dict=odds_dict,
            )
            if ok:
                count += 1

        await asyncio.sleep(0.3)

    logger.info("match_schedule populated: %d matches upserted", count)
    return count


# ── Odds Reconstruction ──────────────────────────────────────────────────────

def _rebuild_odds(odds_dict: dict | None):
    """Reconstruct a MatchOdds-like object from stored JSON."""
    if not odds_dict:
        return None
    try:
        from app.odds_fetcher import MatchOdds
        o = MatchOdds()
        o.home_win   = odds_dict.get("home_win", 0.0)
        o.draw       = odds_dict.get("draw", 0.0)
        o.away_win   = odds_dict.get("away_win", 0.0)
        o.over_2_5   = odds_dict.get("over_2_5", 0.0)
        o.under_2_5  = odds_dict.get("under_2_5", 0.0)
        o.btts_yes   = odds_dict.get("btts_yes", 0.0)
        o.btts_no    = odds_dict.get("btts_no", 0.0)
        return o
    except Exception:
        return None


# ── Match Object Construction ────────────────────────────────────────────────

def _to_match_obj(row: dict[str, Any]):
    """Build a minimal Match-like object from match_schedule row."""
    from app.sports_scraper import Match
    from app.sports_scraper import LEAGUE_NAMES
    m = Match(
        match_id=row["match_id"],
        league_id=row["league_id"],
        league_name=row["league_name"] or LEAGUE_NAMES.get(row["league_id"], ""),
        home_team=row["home_team"],
        away_team=row["away_team"],
        match_date=row["kickoff_utc"],
        venue=row["venue"],
        round_name=row["round_name"],
        status="scheduled",
    )
    return m


# ── Posting Helpers ──────────────────────────────────────────────────────────

async def _post_content(text: str, card_bytes: bytes | None, image_url: str | None) -> bool:
    """Post text + image to channel and group topic. Returns True if channel post succeeded."""
    from app.channel_poster import post_to_channel
    from app.group_topic_poster import classify_content, post_to_topic
    from app.group_topic_db import list_topics

    cta_url = settings.affiliate_url or settings.vip_url or ""
    affiliate_url = cta_url

    content: dict = {
        "text": text,
        "media_type": "photo",
        "affiliate_url": affiliate_url,
        "button_text": "⚽ 스포츠 베팅하기",
        "image_url": image_url,
    }

    # If card bytes present, pass directly to channel_poster (Priority 0 path)
    if card_bytes:
        content["card_bytes"] = card_bytes
        content["image_url"] = None

    ch_ok = await post_to_channel(content)

    if settings.group_id and list_topics():
        content_type = classify_content(text)
        if content_type not in ("sports",):
            content_type = "sports"
        await post_to_topic(
            content_type=content_type,
            text=text,
            image_url=image_url,
            affiliate_url=affiliate_url,
            button_text="⚽ 스포츠 베팅하기",
        )

    return ch_ok


# ── Core Scheduling ──────────────────────────────────────────────────────────

async def post_due_previews() -> int:
    """Find and post previews for matches kicking off soon."""
    from app.pick_tracker import format_accuracy_line
    from app.sports_content_generator import generate_match_preview

    hours_before = settings.match_preview_hours_before
    rows = get_matches_needing_preview(hours_before=hours_before)

    if not rows:
        logger.info("예정된 프리뷰 없음")
        return 0

    accuracy_line = format_accuracy_line()
    cta_url = settings.affiliate_url or settings.vip_url or ""
    posted = 0

    for row in rows:
        match = _to_match_obj(row)
        odds = _rebuild_odds(row.get("odds_dict"))
        kickoff_str = row["kickoff_utc"].strftime("%m/%d %H:%M KST") if row["kickoff_utc"] else ""
        logger.info("프리뷰 게시 시작: %s vs %s (킥오프 %s)", match.home_team, match.away_team, kickoff_str)

        try:
            result = await generate_match_preview(match, cta_url, odds, accuracy_line)
            ok = await _post_content(result["text"], result.get("card_bytes"), result.get("image_url"))
            if ok:
                mark_previewed(match.match_id)
                posted += 1
                logger.info("프리뷰 게시 완료: match_id=%d", match.match_id)
            else:
                logger.warning("프리뷰 게시 실패: match_id=%d", match.match_id)
        except Exception as e:
            logger.exception("프리뷰 생성 오류: match_id=%d — %s", match.match_id, e)
            mark_skipped(match.match_id)

        await asyncio.sleep(3.0)

    return posted


async def post_due_reviews() -> int:
    """Find and post reviews for matches that have ended."""
    from app.sports_content_generator import generate_match_review

    mins_after = settings.match_review_mins_after
    rows = get_matches_needing_review(mins_after=mins_after)

    if not rows:
        logger.info("예정된 리뷰 없음")
        return 0

    cta_url = settings.affiliate_url or settings.vip_url or ""
    posted = 0

    for row in rows:
        match = _to_match_obj(row)
        match.status = "finished"
        logger.info("리뷰 게시 시작: %s vs %s", match.home_team, match.away_team)

        try:
            result = await generate_match_review(match, cta_url)
            ok = await _post_content(result["text"], result.get("card_bytes"), result.get("image_url"))
            if ok:
                mark_reviewed(match.match_id)
                posted += 1
                logger.info("리뷰 게시 완료: match_id=%d", match.match_id)
            else:
                logger.warning("리뷰 게시 실패: match_id=%d", match.match_id)
        except Exception as e:
            logger.exception("리뷰 생성 오류: match_id=%d — %s", match.match_id, e)

        await asyncio.sleep(3.0)

    return posted


async def run_match_scheduler_cycle() -> dict[str, int]:
    """Full scheduler cycle: populate → previews → reviews."""
    ensure_match_schedule_table()

    populated  = await populate_schedule(days_ahead=settings.match_schedule_days_ahead)
    previewed  = await post_due_previews()
    reviewed   = await post_due_reviews()

    result = {"populated": populated, "previewed": previewed, "reviewed": reviewed}
    logger.info("매치 스케줄러 사이클 완료: %s", result)
    return result
