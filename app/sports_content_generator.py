"""
Sports Content Generator: per-match preview and review posts with real data.

Pipeline per preview post:
1. Fetch real odds (The Odds API) — optional, graceful fallback
2. Build verified real-data context block (sports_context_builder)
3. Generate AI analysis with data injected (sports_ai_client)
4. Build Pillow match card image (match_card_generator)
5. Record pick to pick_history DB (pick_tracker)
6. Return {text, card_bytes, image_url, content_type, match_id}

Periodic content (standings, weekly roundup, monthly report) →
  see app/sports_periodic_content.py
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


# ── Helpers ──────────────────────────────────────────────────────────────────

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
    if "원정승" in text:
        pick = "away"
    elif "무승부" in text:
        pick = "draw"
    else:
        if "홈승" not in text:
            logger.debug("No explicit pick found in AI text — defaulting to home")
        pick = "home"
    stars, confidence = 3, 72
    for s in range(5, 0, -1):
        if "⭐" * s in text:
            stars = s
            confidence = {5: 92, 4: 83, 3: 72, 2: 60, 1: 52}.get(s, 72)
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


# ── Match Preview ─────────────────────────────────────────────────────────────

async def generate_match_preview(
    match: Match,
    cta_url: str = "",
    odds=None,
    accuracy_line: str = "",
    sd: SportsData | None = None,
) -> dict[str, Any]:
    """Generate premium match preview: AI text + match card + pick record."""
    emoji = LEAGUE_EMOJI.get(match.league_id, "⚽")
    odds_section = build_odds_section(odds)

    real_context = ""
    if sd:
        real_context = build_real_match_context(
            match,
            all_results=sd.recent_results,
            standings=sd.standings,
            scorers=getattr(sd, "scorers", None),
        )
    else:
        logger.warning(
            "No SportsData for %s vs %s — real data context omitted",
            match.home_team, match.away_team,
        )

    user_prompt = (
        f"Generate a match preview for:\n\n{_fmt_match(match, odds_section)}\n\n"
        f"League emoji: {emoji}\nMonthly accuracy: {accuracy_line or 'N/A'}\n\n"
        f"{real_context}"
    )
    text = await generate_text(PREVIEW_SYSTEM_PROMPT, user_prompt, _cta_html(cta_url))
    pick, stars, confidence = _extract_pick(text or "")

    card_bytes = await _build_card(match, pick, stars, confidence, odds, accuracy_line)
    image_url = None
    if not card_bytes:
        image_url = await fetch_sport_image(
            league_id=match.league_id, home_team=match.home_team,
            away_team=match.away_team, league_name=match.league_name,
        )

    try:
        from app.pick_tracker import record_pick
        record_pick(
            match_id=match.match_id or 0, home_team=match.home_team,
            away_team=match.away_team, league_id=match.league_id,
            pick=pick, stars=stars, match_date=match.match_date,
        )
    except Exception:
        pass

    return {
        "text": text or "", "card_bytes": card_bytes, "image_url": image_url,
        "content_type": "sports_preview", "match_id": match.match_id or 0,
    }


# ── Match Review ──────────────────────────────────────────────────────────────

async def generate_match_review(
    match: Match,
    cta_url: str = "",
    odds=None,
    accuracy_line: str = "",
    sd: SportsData | None = None,
) -> dict[str, Any]:
    """Generate post-match review with previous pick lookup and real data context."""
    emoji = LEAGUE_EMOJI.get(match.league_id, "⚽")

    # Record result first to update is_correct in pick_history
    if match.home_score is not None and match.away_score is not None:
        try:
            from app.pick_tracker import record_result
            record_result(match.match_id or 0, match.home_score, match.away_score)
        except Exception:
            pass

    # Look up pre-match pick for accurate review
    prev_pick_kr = ""
    try:
        from app.pick_tracker import get_pick_for_match
        prev_pick = get_pick_for_match(match.match_id or 0)
        if prev_pick:
            prev_pick_kr = _PICK_MAP.get(prev_pick, prev_pick)
    except Exception:
        pass

    # Build real context if SportsData provided
    real_context = ""
    if sd:
        real_context = build_real_match_context(
            match,
            all_results=sd.recent_results,
            standings=sd.standings,
            scorers=getattr(sd, "scorers", None),
        )

    user_prompt = (
        f"Generate a post-match review:\n\n{_fmt_match(match)}\n\n"
        f"League emoji: {emoji}\n"
        f"Pre-match pick: {prev_pick_kr or '없음'}\n"
        f"{real_context}"
    )
    text = await generate_text(REVIEW_SYSTEM_PROMPT, user_prompt, _cta_html(cta_url))
    image_url = await fetch_sport_image(
        league_id=match.league_id, home_team=match.home_team,
        away_team=match.away_team, league_name=match.league_name,
    )
    return {
        "text": text or "", "card_bytes": None, "image_url": image_url,
        "content_type": "sports_review", "match_id": match.match_id or 0,
    }


# ── Daily Batch ───────────────────────────────────────────────────────────────

async def generate_daily_sports_content(
    sports_data: list[SportsData],
    max_posts: int = 6,
    cta_url: str = "",
    odds_by_league: dict[int, list] | None = None,
    accuracy_line: str = "",
) -> list[dict[str, Any]]:
    """Generate daily batch: previews (date-sorted) → reviews → weekly roundup → standings."""
    from app.odds_fetcher import match_odds_to_game
    from app.sports_periodic_content import generate_standings_post, generate_weekly_roundup

    posts: list[dict[str, Any]] = []
    odds_by_league = odds_by_league or {}
    now = datetime.now(timezone.utc)

    # ── Phase 1: Match previews (upcoming, sorted by kickoff) ─────────────────
    for sd in sports_data:
        if len(posts) >= max_posts:
            break
        league_odds = odds_by_league.get(sd.league_id, [])
        # Sort by match_date ascending so most imminent matches post first
        sorted_upcoming = sorted(
            sd.upcoming,
            key=lambda m: m.match_date or datetime(9999, 12, 31, tzinfo=timezone.utc),
        )
        for match in sorted_upcoming[:2]:
            if len(posts) >= max_posts:
                break
            odds = match_odds_to_game(match.home_team, match.away_team, league_odds)
            post = await generate_match_preview(match, cta_url, odds, accuracy_line, sd=sd)
            post.update({
                "media_type": "photo",
                "source": f"api:sports:{sd.league_name}",
                "league_id": sd.league_id,
            })
            posts.append(post)

    # ── Phase 2: Match reviews (recent results) ───────────────────────────────
    for sd in sports_data:
        if len(posts) >= max_posts:
            break
        for match in sd.recent_results[:1]:
            if len(posts) >= max_posts:
                break
            post = await generate_match_review(match, cta_url, accuracy_line=accuracy_line, sd=sd)
            post.update({
                "media_type": "photo",
                "source": f"api:sports:{sd.league_name}",
                "league_id": sd.league_id,
            })
            posts.append(post)

    # ── Phase 3: Weekly roundup (if still under max) ──────────────────────────
    if len(posts) < max_posts:
        try:
            roundup = await generate_weekly_roundup(sports_data, cta_url)
            if roundup:
                roundup.update({
                    "media_type": "photo",
                    "source": "api:sports:weekly",
                    "league_id": 0,
                })
                posts.append(roundup)
        except Exception as e:
            logger.warning("Weekly roundup skipped: %s", e)

    # ── Phase 4: Standings (one league, if still under max) ───────────────────
    if len(posts) < max_posts:
        for sd in sports_data:
            if sd.standings:
                try:
                    post = await generate_standings_post(sd.standings, sd.league_id, cta_url)
                    if post:
                        post.update({
                            "media_type": "photo",
                            "source": f"api:sports:{sd.league_name}",
                            "league_id": sd.league_id,
                        })
                        posts.append(post)
                except Exception as e:
                    logger.warning("Standings post skipped: %s", e)
                break

    logger.info("Generated %d sports posts", len(posts))
    return posts
