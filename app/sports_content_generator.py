"""
Sports Content Generator: per-match preview and review posts with real data.

Periodic content (standings, weekly roundup, monthly report, top scorers)
→ see app/sports_periodic_content.py
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.logging_config import get_logger
from app.sports_ai_client import generate_text
from app.sports_image_fetcher import fetch_sport_image
from app.sports_prompts import PREVIEW_SYSTEM_PROMPT, REVIEW_SYSTEM_PROMPT, build_odds_section
from app.sports_context_builder import build_real_match_context
from app.sports_scraper import LEAGUE_EMOJI, Match, SportsData

logger = get_logger("sports_content_generator")

_PICK_MAP = {"home": "홈승", "draw": "무승부", "away": "원정승"}
# Star count → confidence percentage mapping
_STAR_CONFIDENCE: dict[int, int] = {5: 92, 4: 83, 3: 72, 2: 60, 1: 52}


def _cta_html(url: str) -> str:
    return f"👉 <a href='{url}'>스포츠 베팅 시작하기</a>" if url else ""


def _fmt_match(match: Match, odds_section: str = "") -> str:
    date_str = match.match_date.strftime("%Y-%m-%d %H:%M KST") if match.match_date else "TBD"
    score = f"Score: {match.home_score} - {match.away_score}" if match.home_score is not None else ""
    base = (
        f"League: {match.league_name}\nHome: {match.home_team}\nAway: {match.away_team}\n"
        f"Date: {date_str}\nVenue: {match.venue or 'TBD'}\nRound: {match.round_name or 'TBD'}\n"
        f"Status: {match.status}\n{score}"
    ).strip()
    return f"{base}\n\n{odds_section}" if odds_section else base


def _extract_pick(text: str) -> tuple[str, int, int]:
    """Extract pick/stars/confidence from AI text. Returns English pick for DB storage."""
    pick = "away" if "원정승" in text else ("draw" if "무승부" in text else "home")
    if pick == "home" and "홈승" not in text:
        logger.debug("No explicit pick found — defaulting to home")
    stars, confidence = 3, 72
    for s in range(5, 0, -1):
        if "⭐" * s in text:
            stars = s
            confidence = _STAR_CONFIDENCE.get(s, 72)
            break
    return pick, stars, confidence


async def _build_card(
    match: Match, pick: str, stars: int, confidence: int,
    odds=None, accuracy_line: str = "",
) -> bytes | None:
    try:
        from app.match_card_generator import generate_match_card
        date_str = match.match_date.strftime("%m/%d %H:%M KST") if match.match_date else ""
        return generate_match_card(
            home_team=match.home_team, away_team=match.away_team,
            league_name=match.league_name, league_id=match.league_id,
            match_date_str=date_str, pick=pick, stars=stars,
            confidence_pct=confidence, odds=odds, monthly_accuracy=accuracy_line,
        )
    except Exception as e:
        logger.warning("Card generation failed: %s", e)
        return None


async def generate_match_preview(
    match: Match, cta_url: str = "", odds=None,
    accuracy_line: str = "", sd: SportsData | None = None,
) -> dict[str, Any]:
    """Generate premium match preview: AI text + match card + pick record."""
    emoji = LEAGUE_EMOJI.get(match.league_id, "⚽")
    odds_section = build_odds_section(odds)
    real_context = ""
    if sd:
        real_context = build_real_match_context(
            match, all_results=sd.recent_results,
            standings=sd.standings, scorers=getattr(sd, "scorers", None),
        )
    else:
        logger.warning("No SportsData for %s vs %s", match.home_team, match.away_team)

    text = await generate_text(
        PREVIEW_SYSTEM_PROMPT,
        f"Generate a match preview for:\n\n{_fmt_match(match, odds_section)}\n\n"
        f"League emoji: {emoji}\nMonthly accuracy: {accuracy_line or 'N/A'}\n\n{real_context}",
        _cta_html(cta_url),
    )
    pick, stars, confidence = _extract_pick(text or "")
    card_bytes = await _build_card(match, pick, stars, confidence, odds, accuracy_line)
    image_url = None if card_bytes else await fetch_sport_image(
        league_id=match.league_id, home_team=match.home_team,
        away_team=match.away_team, league_name=match.league_name,
        content_type="sports_preview",
    )
    try:
        from app.pick_tracker import record_pick
        record_pick(
            match_id=match.match_id or 0, home_team=match.home_team,
            away_team=match.away_team, league_id=match.league_id,
            pick=pick, stars=stars, match_date=match.match_date,
        )
    except Exception as e:
        logger.debug("record_pick skipped (non-critical): %s", e)
    return {
        "text": text or "", "card_bytes": card_bytes, "image_url": image_url,
        "content_type": "sports_preview", "match_id": match.match_id or 0,
    }


async def generate_match_review(
    match: Match, cta_url: str = "", odds=None,
    accuracy_line: str = "", sd: SportsData | None = None,
) -> dict[str, Any]:
    """Generate post-match review: real data context + previous pick lookup."""
    emoji = LEAGUE_EMOJI.get(match.league_id, "⚽")
    if match.home_score is not None and match.away_score is not None:
        try:
            from app.pick_tracker import record_result
            record_result(match.match_id or 0, match.home_score, match.away_score)
        except Exception as e:
            logger.debug("record_result skipped (non-critical): %s", e)

    prev_pick_kr = ""
    try:
        from app.pick_tracker import get_pick_for_match
        prev = get_pick_for_match(match.match_id or 0)
        if prev:
            prev_pick_kr = _PICK_MAP.get(prev, prev)
    except Exception as e:
        logger.debug("get_pick_for_match skipped (non-critical): %s", e)

    real_context = ""
    if sd:
        real_context = build_real_match_context(
            match, all_results=sd.recent_results,
            standings=sd.standings, scorers=getattr(sd, "scorers", None),
        )

    text = await generate_text(
        REVIEW_SYSTEM_PROMPT,
        f"Generate a post-match review:\n\n{_fmt_match(match)}\n\n"
        f"League emoji: {emoji}\nPre-match pick: {prev_pick_kr or '없음'}\n{real_context}",
        _cta_html(cta_url),
    )
    image_url = await fetch_sport_image(
        league_id=match.league_id, home_team=match.home_team,
        away_team=match.away_team, league_name=match.league_name,
        content_type="sports_review",
    )
    return {
        "text": text or "", "card_bytes": None, "image_url": image_url,
        "content_type": "sports_review", "match_id": match.match_id or 0,
    }


async def generate_daily_sports_content(
    sports_data: list[SportsData],
    max_posts: int = 6,
    cta_url: str = "",
    odds_by_league: dict[int, list] | None = None,
    accuracy_line: str = "",
) -> list[dict[str, Any]]:
    """Generate daily batch: previews → reviews → weekly roundup → standings → top scorers."""
    from app.odds_fetcher import match_odds_to_game
    from app.sports_periodic_content import (
        generate_standings_post, generate_top_scorer_post, generate_weekly_roundup,
    )

    posts: list[dict[str, Any]] = []
    odds_by_league = odds_by_league or {}
    _dt_max = datetime(9999, 12, 31, tzinfo=timezone.utc)

    # Phase 1: previews sorted by kickoff
    for sd in sports_data:
        if len(posts) >= max_posts:
            break
        league_odds = odds_by_league.get(sd.league_id, [])
        espn_odds_map: dict[int, dict] = getattr(sd, "espn_odds", {})
        for match in sorted(sd.upcoming, key=lambda m: m.match_date or _dt_max)[:2]:
            if len(posts) >= max_posts:
                break
            # ESPN embedded odds take priority (per-match); fall back to The Odds API
            if match.match_id in espn_odds_map:
                from app.odds_fetcher import MatchOdds
                od = espn_odds_map[match.match_id]
                odds = MatchOdds(
                    home_team=match.home_team, away_team=match.away_team,
                    home_win=od.get("home_win", 0.0), draw=od.get("draw", 0.0),
                    away_win=od.get("away_win", 0.0),
                    over_2_5=od.get("over_2_5", 0.0), under_2_5=od.get("under_2_5", 0.0),
                    bookmaker="ESPN/DraftKings",
                )
            else:
                odds = match_odds_to_game(match.home_team, match.away_team, league_odds)
            post = await generate_match_preview(match, cta_url, odds, accuracy_line, sd=sd)
            post.update({"media_type": "photo", "source": f"api:sports:{sd.league_name}", "league_id": sd.league_id})
            posts.append(post)

    # Phase 2: reviews
    for sd in sports_data:
        if len(posts) >= max_posts:
            break
        for match in sd.recent_results[:1]:
            if len(posts) >= max_posts:
                break
            post = await generate_match_review(match, cta_url, accuracy_line=accuracy_line, sd=sd)
            post.update({"media_type": "photo", "source": f"api:sports:{sd.league_name}", "league_id": sd.league_id})
            posts.append(post)

    # Phase 3: weekly roundup
    if len(posts) < max_posts:
        try:
            p = await generate_weekly_roundup(sports_data, cta_url)
            if p:
                p.update({"media_type": "photo", "source": "api:sports:weekly", "league_id": 0})
                posts.append(p)
        except Exception as e:
            logger.warning("Weekly roundup skipped: %s", e)

    # Phase 4: standings
    if len(posts) < max_posts:
        for sd in sports_data:
            if sd.standings:
                try:
                    p = await generate_standings_post(sd.standings, sd.league_id, cta_url)
                    if p:
                        p.update({"media_type": "photo", "source": f"api:sports:{sd.league_name}", "league_id": sd.league_id})
                        posts.append(p)
                except Exception as e:
                    logger.warning("Standings skipped: %s", e)
                break

    # Phase 5: top scorer race
    if len(posts) < max_posts:
        for sd in sports_data:
            scorers = getattr(sd, "scorers", None)
            if scorers:
                try:
                    p = await generate_top_scorer_post(scorers, sd.league_id, cta_url)
                    if p:
                        p.update({"media_type": "photo", "source": f"api:sports:{sd.league_name}", "league_id": sd.league_id})
                        posts.append(p)
                except Exception as e:
                    logger.warning("Top scorer skipped: %s", e)
                break

    logger.info("Generated %d sports posts", len(posts))
    return posts
